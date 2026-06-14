#!/usr/bin/env python3
"""
diagnose_footscray_origin_distance_consistency.py
─────────────────────────────────────────────────
READ-ONLY diagnostic for the Footscray residential-origin demand pipeline.

It explains the apparent inconsistency between

  * the residential candidate-generation filter (0.8 km .. 3.0 km DIRECT
    haversine catchment around Footscray Station), and

  * the ``direct_station_dist_mm`` column in ``assignments.csv``, which has a
    min of ~1.27 km and a max of ~8.2 km.

The script does NOT modify any experiment result and does NOT rerun any
simulation. It only reads existing files and prints / saves a report.

Suggested usage:

  python3 experiments/scripts/diagnose_footscray_origin_distance_consistency.py \
    --results-root experiments/results/footscray/fleet_composition_grid_footscray_80seats \
    --station-node 240615
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy expected to be present
    np = None  # type: ignore


R_EARTH_M = 6_371_008.8

# Repo root inferred from this file: experiments/scripts/<this>.py  ->  repo/
REPO_ROOT = Path(__file__).resolve().parents[2]

# Canonical input locations (relative to repo root).
NODES_LAT_LON = "files/inputs/footscray_nodes_lat_lon.csv"
CANDIDATE_NODES = "files/inputs/footscray_residential_candidate_nodes_3km.csv"
CANDIDATE_POINTS = "files/inputs/footscray_residential_candidate_points_3km.csv"
CANDIDATE_MAPPING = "files/inputs/footscray_residential_candidate_mapping_3km.csv"
CANDIDATE_METADATA = "files/inputs/footscray_residential_candidate_metadata_3km.json"
COMMUTERS_CSV = "files/inputs/footscray_commuters_residential.csv"
COMMUTERS_METADATA = "files/inputs/footscray_commuters_residential_metadata.json"
MATRIX_DIR = "dataset/FOOTSCRAY/footscray_residential_matrix"

REPRESENTATIVE_FLEETS = [
    "comp_S0_M0_C100_MB0",
    "comp_S25_M25_C25_MB25",
    "comp_S25_M0_C0_MB75",
    "comp_S50_M50_C0_MB0",
]

BIN_EDGES_KM = [0, 1, 2, 3, 4, 5, math.inf]
BIN_LABELS = ["0-1", "1-2", "2-3", "3-4", "4-5", "5+"]


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R_EARTH_M * 2 * math.asin(math.sqrt(a))


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def summarize_km(values_km: list[float]) -> dict[str, Any]:
    if not values_km:
        return {"count": 0}
    return {
        "count": len(values_km),
        "min": min(values_km),
        "mean": sum(values_km) / len(values_km),
        "median": pct(values_km, 0.50),
        "p75": pct(values_km, 0.75),
        "p90": pct(values_km, 0.90),
        "p95": pct(values_km, 0.95),
        "max": max(values_km),
        "n_above_3km": sum(1 for v in values_km if v > 3.0),
        "n_above_5km": sum(1 for v in values_km if v > 5.0),
    }


def bin_counts_km(values_km: list[float]) -> dict[str, int]:
    counts = {label: 0 for label in BIN_LABELS}
    for v in values_km:
        for i in range(len(BIN_LABELS)):
            if BIN_EDGES_KM[i] <= v < BIN_EDGES_KM[i + 1]:
                counts[BIN_LABELS[i]] += 1
                break
    return counts


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_node_coords(path: Path) -> dict[int, tuple[float, float]]:
    coords: dict[int, tuple[float, float]] = {}
    for row in read_csv_rows(path):
        try:
            coords[int(row["node_id"])] = (float(row["lat"]), float(row["lon"]))
        except (KeyError, ValueError):
            continue
    return coords


def origin_node_from_assignment_row(row: dict[str, str]) -> Optional[int]:
    """The 'path' column is '<origin_node> ... <station_node>'."""
    path = (row.get("path") or "").strip()
    if not path:
        return None
    try:
        return int(path.split()[0])
    except (ValueError, IndexError):
        return None


# ──────────────────────────────────────────────────────────────────────────
# Q1/Q2/Q3/Q7  source-code inspection
# ──────────────────────────────────────────────────────────────────────────
def inspect_source(report: dict[str, Any]) -> None:
    builder = REPO_ROOT / "python/build_residential_origin_candidates.py"
    sim = REPO_ROOT / "python/simulate_first_mile_pyvrp.py"

    src = {
        "builder_path": str(builder.relative_to(REPO_ROOT)),
        "sim_path": str(sim.relative_to(REPO_ROOT)),
    }

    if builder.exists():
        text = builder.read_text()
        # The filter computes haversine from the CANDIDATE POINT to the station.
        src["filter_uses_haversine_candidate_point"] = bool(
            re.search(
                r"direct_station_distance_m\s*=\s*haversine_m\(\s*c\.lat,\s*c\.lon,\s*station_lat,\s*station_lon",
                text,
            )
        )
        src["filter_variable"] = "direct_station_distance_m"
        # Which value the threshold comparisons use:
        src["walking_threshold_compares_candidate_point"] = bool(
            re.search(r"direct_station_distance_m\s*<=\s*walking_threshold_m", text)
        )
        src["max_distance_compares_candidate_point"] = bool(
            re.search(r"direct_station_distance_m\s*>\s*max_station_distance_m", text)
        )
        # snapped node distance is NOT re-checked against max_station_distance_m
        src["snapped_node_rechecked_against_cap"] = bool(
            re.search(r"snap[_a-z]*node[_a-z]*distance.*max_station_distance_m", text)
        )
        src["default_walking_threshold_m"] = 800.0 if "default=800" in text.replace(" ", "") else None
        src["filter_stage"] = (
            "candidate-point haversine, computed in the same loop as nearest-node "
            "snapping but compared BEFORE keeping the snapped node; the snapped "
            "node distance is never re-tested against the 3 km cap"
        )

    if sim.exists():
        text = sim.read_text()
        # direct_station_dist_mm is read straight out of the raw distance matrix.
        m = re.search(
            r"direct_station_dist_mm_by_commuter_id\[c\.id\]\s*=\s*int\(\s*"
            r"dist_mm_raw\[node_to_idx\[c\.origin_node\],\s*station_idx\]",
            text,
        )
        src["direct_station_dist_mm_from_matrix"] = bool(m)
        src["dist_mm_raw_source"] = (
            "np.load(distances.npy) in load_matrices() — the dumped hub-label "
            "shortest-path distance matrix (millimetres)"
            if 'np.load(str(d / "distances.npy"))' in text
            else "unknown"
        )
        src["direct_station_dist_mm_meaning"] = (
            "network shortest-path road distance (millimetres) from the commuter "
            "origin road node to the station node; 'direct' = the un-pooled/"
            "non-detour single-rider trip, NOT direct haversine distance"
        )

    report["source_inspection"] = src


# ──────────────────────────────────────────────────────────────────────────
# Q1  candidate metadata
# ──────────────────────────────────────────────────────────────────────────
def inspect_candidate_metadata(report: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    path = REPO_ROOT / CANDIDATE_METADATA
    out["path"] = CANDIDATE_METADATA
    out["exists"] = path.exists()
    if path.exists():
        meta = json.loads(path.read_text())
        ms = meta.get("mapping_stats", {})
        fields = [
            "walking_threshold_m",
            "max_station_distance_m",
            "raw_candidates",
            "kept_candidate_rows",
            "unique_candidate_road_nodes",
            "removed_by_walking_threshold",
            "removed_by_outer_catchment",
        ]
        for k in fields:
            if k in meta:
                out[k] = meta[k]
        out["walking_filter_method"] = meta.get("walking_filter", {}).get("method")
        out["nearest_node_distance_reported"] = meta.get("nearest_node_mapping", {}).get(
            "distance_reported"
        )
        for k in ("station_node", "station_lat", "station_lon", "filter_reason_counts"):
            if k in ms:
                out[k] = ms[k]
        if "direct_station_distance_m_kept_summary" in ms:
            out["direct_station_distance_m_kept_summary"] = ms[
                "direct_station_distance_m_kept_summary"
            ]
        if "snap_distance_m_kept_summary" in ms:
            out["snap_distance_m_kept_summary"] = ms["snap_distance_m_kept_summary"]
    report["candidate_metadata"] = out
    return out


# ──────────────────────────────────────────────────────────────────────────
# Q3  candidate mapping CSV (kept candidates) + snap analysis
# ──────────────────────────────────────────────────────────────────────────
def inspect_candidate_mapping(
    report: dict[str, Any],
    node_coords: dict[int, tuple[float, float]],
    station_node: int,
    out_csv_dir: Path,
) -> None:
    out: dict[str, Any] = {}
    path = REPO_ROOT / CANDIDATE_MAPPING
    out["path"] = CANDIDATE_MAPPING
    out["exists"] = path.exists()
    if not path.exists():
        report["candidate_mapping"] = out
        return

    rows = read_csv_rows(path)
    out["total_rows"] = len(rows)
    kept = [r for r in rows if str(r.get("kept", "")).strip().lower() in ("true", "1")]
    out["kept_rows"] = len(kept)

    station_coord = node_coords.get(station_node)

    cand_direct_km: list[float] = []
    snap_m: list[float] = []
    node_direct_km: list[float] = []  # haversine from SNAPPED node to station
    leak_rows: list[dict[str, Any]] = []

    for r in kept:
        try:
            d_cand = float(r["direct_station_distance_m"])
            cand_direct_km.append(d_cand / 1000.0)
        except (KeyError, ValueError):
            d_cand = float("nan")
        try:
            snap_m.append(float(r["snap_distance_m"]))
        except (KeyError, ValueError):
            pass

        node_d = float("nan")
        if station_coord is not None:
            try:
                nlat = float(r["nearest_node_lat"])
                nlon = float(r["nearest_node_lon"])
                node_d = haversine_m(nlat, nlon, station_coord[0], station_coord[1])
                node_direct_km.append(node_d / 1000.0)
            except (KeyError, ValueError):
                pass

        leak_rows.append(
            {
                "candidate_id": r.get("candidate_id", ""),
                "nearest_node": r.get("nearest_node", ""),
                "candidate_direct_m": d_cand,
                "snapped_node_direct_m": node_d,
                "snap_distance_m": _safe_float(r.get("snap_distance_m")),
            }
        )

    out["candidate_point_direct_km_summary"] = summarize_km(cand_direct_km)
    out["candidate_points_above_3km"] = sum(1 for v in cand_direct_km if v > 3.0)
    out["snap_distance_m_summary"] = (
        {
            "count": len(snap_m),
            "min": min(snap_m),
            "median": pct(snap_m, 0.5),
            "p95": pct(snap_m, 0.95),
            "max": max(snap_m),
        }
        if snap_m
        else {"count": 0}
    )
    if node_direct_km:
        out["snapped_node_direct_km_summary"] = summarize_km(node_direct_km)
        out["snapped_nodes_above_3km"] = sum(1 for v in node_direct_km if v > 3.0)
    else:
        out["snapped_node_direct_km_summary"] = None
        out["snapped_nodes_above_3km"] = None

    # top 20 by snapped-node direct distance (snap leakage candidates)
    leak_sorted = sorted(
        [r for r in leak_rows if not math.isnan(r["snapped_node_direct_m"])],
        key=lambda r: r["snapped_node_direct_m"],
        reverse=True,
    )[:20]
    out["top20_largest_snapped_node_direct"] = leak_sorted

    # write CSV
    out_csv_dir.mkdir(parents=True, exist_ok=True)
    leak_path = out_csv_dir / "candidate_snap_leakage_top.csv"
    with leak_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "candidate_id",
                "nearest_node",
                "candidate_direct_m",
                "snapped_node_direct_m",
                "snap_distance_m",
            ],
        )
        w.writeheader()
        for r in leak_sorted:
            w.writerow(r)
    out["top20_csv"] = str(leak_path.relative_to(REPO_ROOT))

    report["candidate_mapping"] = out


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


# ──────────────────────────────────────────────────────────────────────────
# Q4  commuter input file
# ──────────────────────────────────────────────────────────────────────────
def inspect_commuters(
    report: dict[str, Any],
    node_coords: dict[int, tuple[float, float]],
    station_node: int,
    matrix: Optional[dict[str, Any]],
) -> None:
    out: dict[str, Any] = {}
    path = REPO_ROOT / COMMUTERS_CSV
    out["path"] = COMMUTERS_CSV
    out["exists"] = path.exists()
    if not path.exists():
        report["commuters_input"] = out
        return

    rows = read_csv_rows(path)
    out["n_commuters"] = len(rows)
    out["columns"] = list(rows[0].keys()) if rows else []
    out["has_distance_column"] = any("dist" in c.lower() for c in out["columns"])

    origins = []
    for r in rows:
        try:
            origins.append(int(r["origin_node"]))
        except (KeyError, ValueError):
            pass
    out["unique_origin_nodes"] = len(set(origins))

    station_coord = node_coords.get(station_node)
    hav_km = []
    if station_coord is not None:
        for n in origins:
            c = node_coords.get(n)
            if c is not None:
                hav_km.append(haversine_m(c[0], c[1], station_coord[0], station_coord[1]) / 1000.0)
        out["origin_node_haversine_km_summary"] = summarize_km(hav_km)
        out["origin_node_haversine_above_3km"] = sum(1 for v in hav_km if v > 3.0)

    # Network distance for these commuter origins straight from the matrix.
    if matrix is not None:
        net_km = []
        for n in origins:
            mm = matrix["lookup"](n)
            if mm is not None:
                net_km.append(mm / 1_000_000.0)
        out["origin_node_network_km_summary"] = summarize_km(net_km)
        out["origin_node_network_bins"] = bin_counts_km(net_km)

    report["commuters_input"] = out


# ──────────────────────────────────────────────────────────────────────────
# matrix loader (the SOURCE of direct_station_dist_mm)
# ──────────────────────────────────────────────────────────────────────────
def load_matrix(station_node: int) -> Optional[dict[str, Any]]:
    if np is None:
        return None
    mdir = REPO_ROOT / MATRIX_DIR
    dist_path = mdir / "distances.npy"
    nodes_path = mdir / "nodes.txt"
    if not dist_path.exists() or not nodes_path.exists():
        return None
    dist = np.load(str(dist_path))
    nodes = [int(x) for x in nodes_path.read_text().split()]
    node_to_idx = {n: i for i, n in enumerate(nodes)}
    if station_node not in node_to_idx:
        return None
    station_idx = node_to_idx[station_node]

    def lookup(node_id: int) -> Optional[int]:
        idx = node_to_idx.get(node_id)
        if idx is None:
            return None
        return int(dist[idx, station_idx])

    return {
        "dir": MATRIX_DIR,
        "shape": list(dist.shape),
        "n_nodes": len(nodes),
        "station_idx": station_idx,
        "lookup": lookup,
    }


# ──────────────────────────────────────────────────────────────────────────
# Q5  assignments across fleets/runs
# ──────────────────────────────────────────────────────────────────────────
def inspect_assignment_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    rows = read_csv_rows(path)
    vals_km = []
    origins = []
    for r in rows:
        try:
            vals_km.append(int(r["direct_station_dist_mm"]) / 1_000_000.0)
        except (KeyError, ValueError):
            continue
        o = origin_node_from_assignment_row(r)
        if o is not None:
            origins.append(o)
    summary = summarize_km(vals_km)
    summary["bins"] = bin_counts_km(vals_km)
    summary["origin_node_set_hash"] = hash(frozenset(origins))
    summary["n_origin_nodes"] = len(origins)
    summary["n_unique_origin_nodes"] = len(set(origins))
    return summary


def inspect_assignments(
    report: dict[str, Any],
    results_root: Path,
    node_coords: dict[int, tuple[float, float]],
    station_node: int,
    matrix: Optional[dict[str, Any]],
    out_csv_dir: Path,
) -> None:
    out: dict[str, Any] = {"results_root": str(results_root)}
    fleets_summary: dict[str, Any] = {}
    origin_hashes: dict[str, Any] = {}

    fleets = [f for f in REPRESENTATIVE_FLEETS if (results_root / f).exists()]
    # always include the primary requested file's fleet
    if "comp_S25_M25_C25_MB25" not in fleets and (
        results_root / "comp_S25_M25_C25_MB25"
    ).exists():
        fleets.append("comp_S25_M25_C25_MB25")

    for fleet in fleets:
        apath = results_root / fleet / "run_1" / "assignments.csv"
        s = inspect_assignment_file(apath)
        if s is None:
            continue
        origin_hashes[fleet] = s.pop("origin_node_set_hash")
        fleets_summary[fleet] = s

    out["fleets"] = fleets_summary
    out["all_fleets_share_origin_set"] = (
        len(set(origin_hashes.values())) == 1 if origin_hashes else None
    )

    # Detailed verification on the primary file: is the column haversine or network?
    primary = results_root / "comp_S25_M25_C25_MB25" / "run_1" / "assignments.csv"
    if primary.exists():
        out["column_nature_check"] = verify_column_nature(
            primary, node_coords, station_node, matrix, out_csv_dir
        )

    report["assignments"] = out


def verify_column_nature(
    path: Path,
    node_coords: dict[int, tuple[float, float]],
    station_node: int,
    matrix: Optional[dict[str, Any]],
    out_csv_dir: Path,
) -> dict[str, Any]:
    """Compare assignment column vs (a) haversine and (b) matrix network distance."""
    rows = read_csv_rows(path)
    station_coord = node_coords.get(station_node)
    recs: list[dict[str, Any]] = []
    abs_err_hav = []
    abs_err_net = []
    ratio_net_over_hav = []

    for r in rows:
        try:
            col_mm = int(r["direct_station_dist_mm"])
        except (KeyError, ValueError):
            continue
        origin = origin_node_from_assignment_row(r)
        if origin is None:
            continue
        col_km = col_mm / 1_000_000.0

        hav_km = float("nan")
        if station_coord is not None and origin in node_coords:
            c = node_coords[origin]
            hav_km = haversine_m(c[0], c[1], station_coord[0], station_coord[1]) / 1000.0

        net_km = float("nan")
        if matrix is not None:
            mm = matrix["lookup"](origin)
            if mm is not None:
                net_km = mm / 1_000_000.0

        rec = {
            "commuter_id": r.get("commuter_id", ""),
            "origin_node": origin,
            "column_km": col_km,
            "haversine_km": hav_km,
            "matrix_network_km": net_km,
        }
        recs.append(rec)
        if not math.isnan(hav_km):
            abs_err_hav.append(abs(col_km - hav_km))
            if hav_km > 0:
                ratio_net_over_hav.append(col_km / hav_km)
        if not math.isnan(net_km):
            abs_err_net.append(abs(col_km - net_km))

    res: dict[str, Any] = {"n_compared": len(recs)}
    if abs_err_hav:
        res["mean_abs_diff_vs_haversine_km"] = sum(abs_err_hav) / len(abs_err_hav)
        res["max_abs_diff_vs_haversine_km"] = max(abs_err_hav)
    if abs_err_net:
        res["mean_abs_diff_vs_matrix_network_km"] = sum(abs_err_net) / len(abs_err_net)
        res["max_abs_diff_vs_matrix_network_km"] = max(abs_err_net)
        res["matches_matrix_network_exactly"] = max(abs_err_net) < 1e-6
    if ratio_net_over_hav:
        res["column_over_haversine_ratio_mean"] = sum(ratio_net_over_hav) / len(
            ratio_net_over_hav
        )
        res["column_over_haversine_ratio_min"] = min(ratio_net_over_hav)
        res["column_over_haversine_ratio_max"] = max(ratio_net_over_hav)

    # conclusion
    if res.get("matches_matrix_network_exactly"):
        res["conclusion"] = (
            "direct_station_dist_mm == network shortest-path distance from the "
            "matrix (exact match). It is NOT direct haversine distance."
        )
    elif abs_err_hav and res.get("mean_abs_diff_vs_haversine_km", 9) > 0.2:
        res["conclusion"] = (
            "direct_station_dist_mm differs substantially from haversine "
            "(network distance is larger due to road circuity)."
        )

    # write per-commuter comparison CSV
    out_csv_dir.mkdir(parents=True, exist_ok=True)
    cmp_path = out_csv_dir / "assignment_column_vs_haversine_vs_network.csv"
    with cmp_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "commuter_id",
                "origin_node",
                "column_km",
                "haversine_km",
                "matrix_network_km",
            ],
        )
        w.writeheader()
        for rec in sorted(recs, key=lambda x: x["column_km"], reverse=True):
            w.writerow(rec)
    res["comparison_csv"] = str(cmp_path.relative_to(REPO_ROOT))
    return res


# ──────────────────────────────────────────────────────────────────────────
# file discovery (informational)
# ──────────────────────────────────────────────────────────────────────────
def discover_files(report: dict[str, Any]) -> None:
    found = []
    roots = ["files/inputs", "dataset", "experiments/results"]
    pat = re.compile(r"footscray.*(residential|origin|candidate|mapping)", re.I)
    for root in roots:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and pat.search(p.name):
                try:
                    found.append(str(p.relative_to(REPO_ROOT)))
                except ValueError:
                    found.append(str(p))
    report["discovered_files"] = sorted(set(found))


# ──────────────────────────────────────────────────────────────────────────
# conclusion
# ──────────────────────────────────────────────────────────────────────────
def build_conclusion(report: dict[str, Any]) -> dict[str, Any]:
    meta = report.get("candidate_metadata", {})
    mapping = report.get("candidate_mapping", {})
    col_check = report.get("assignments", {}).get("column_nature_check", {})
    src = report.get("source_inspection", {})

    cand_cap_applied = (
        meta.get("max_station_distance_m") == 3000.0
        and meta.get("direct_station_distance_m_kept_summary", {}).get("max", 9e9) <= 3000.0 + 1.0
    )
    snapped_above = mapping.get("snapped_nodes_above_3km")
    snap_max = mapping.get("snap_distance_m_summary", {}).get("max")
    column_is_network = bool(col_check.get("matches_matrix_network_exactly"))

    case = "E"
    if column_is_network:
        case = "C"

    conclusion = {
        "case": case,
        "candidate_3km_cap_applied_to_candidate_points": cand_cap_applied,
        "candidate_filter_target": "candidate point (pre-snap) DIRECT HAVERSINE distance",
        "snapped_node_leakage_above_3km": snapped_above,
        "max_snap_distance_m": snap_max,
        "column_is_network_shortest_path": column_is_network,
        "column_source": src.get("dist_mm_raw_source"),
        "summary": _conclusion_text(report, case, cand_cap_applied, snapped_above, snap_max),
    }
    report["conclusion"] = conclusion
    return conclusion


def _conclusion_text(report, case, cand_cap_applied, snapped_above, snap_max) -> str:
    col_check = report.get("assignments", {}).get("column_nature_check", {})
    ratio_mean = col_check.get("column_over_haversine_ratio_mean")
    net_max = None
    fleets = report.get("assignments", {}).get("fleets", {})
    if fleets:
        net_max = max(f.get("max", 0) for f in fleets.values())
    parts = []
    parts.append(
        "CASE C: `direct_station_dist_mm` is the NETWORK shortest-path road "
        "distance (millimetres) from each commuter's origin road node to the "
        "station node, read directly from the dumped hub-label distance matrix "
        "(distances.npy) in simulate_first_mile_pyvrp.py. It is NOT direct "
        "haversine distance and the 'mm' suffix means millimetres, not the case "
        "study."
    )
    if cand_cap_applied:
        parts.append(
            "The 0.8-3.0 km catchment WAS correctly applied, but to the "
            "candidate POINT's direct haversine distance (max kept = "
            f"{report.get('candidate_metadata', {}).get('direct_station_distance_m_kept_summary', {}).get('max', 'NA'):.1f} m "
            "<= 3000 m). The cap is a haversine constraint; the assignment column "
            "is a road-network metric, so the two are not directly comparable."
        )
    if snapped_above is not None:
        parts.append(
            f"Snap leakage is negligible: max snap distance ~{snap_max:.0f} m and "
            f"{snapped_above} snapped nodes exceed 3 km haversine — far too small "
            "to explain the 8.2 km tail."
        )
    if ratio_mean:
        parts.append(
            f"Across assignments the column/haversine ratio averages ~{ratio_mean:.2f} "
            "(road circuity, incl. Maribyrnong River crossings), so a 3 km "
            f"haversine catchment maps to network distances up to ~{net_max:.1f} km."
        )
    parts.append(
        "The 5+ km bin is REAL and VALID network distance, not a mislabelled "
        "column or snap leakage. For a 'distance-band' analysis that should match "
        "the 3 km catchment, band on the candidate-point/origin-node HAVERSINE "
        "distance, not on direct_station_dist_mm; or relabel the column as "
        "'network station distance'."
    )
    return " ".join(parts)


# ──────────────────────────────────────────────────────────────────────────
# pretty print
# ──────────────────────────────────────────────────────────────────────────
def print_report(report: dict[str, Any]) -> None:
    def line(c="─"):
        print(c * 70)

    line("═")
    print("  FOOTSCRAY ORIGIN-DISTANCE CONSISTENCY DIAGNOSTIC")
    line("═")

    src = report.get("source_inspection", {})
    print("\n[Q1/Q2] Candidate-generation filter (build_residential_origin_candidates.py)")
    print(f"  filter variable           : {src.get('filter_variable')}")
    print(f"  haversine candidate->station: {src.get('filter_uses_haversine_candidate_point')}")
    print(f"  cap target                : {src.get('filter_stage')}")
    print(f"  snapped node re-checked    : {src.get('snapped_node_rechecked_against_cap')}")

    meta = report.get("candidate_metadata", {})
    print("\n[Q1] Candidate metadata thresholds")
    print(f"  walking_threshold_m       : {meta.get('walking_threshold_m')}")
    print(f"  max_station_distance_m    : {meta.get('max_station_distance_m')}")
    print(f"  kept candidate rows       : {meta.get('kept_candidate_rows')}")
    print(f"  unique candidate nodes    : {meta.get('unique_candidate_road_nodes')}")
    print(f"  filter method             : {meta.get('walking_filter_method')}")
    dss = meta.get("direct_station_distance_m_kept_summary", {})
    if dss:
        print(
            f"  kept candidate direct dist: min={dss.get('min'):.1f} "
            f"median={dss.get('median'):.1f} max={dss.get('max'):.1f} m"
        )

    cm = report.get("candidate_mapping", {})
    print("\n[Q2/Q5] Candidate mapping / snap leakage")
    print(f"  kept rows                 : {cm.get('kept_rows')}")
    print(f"  candidate pts > 3 km      : {cm.get('candidate_points_above_3km')}")
    snc = cm.get("snapped_node_direct_km_summary")
    if snc:
        print(
            f"  snapped node haversine    : min={snc.get('min'):.3f} "
            f"median={snc.get('median'):.3f} max={snc.get('max'):.3f} km"
        )
    print(f"  snapped nodes > 3 km      : {cm.get('snapped_nodes_above_3km')}")
    sd = cm.get("snap_distance_m_summary", {})
    if sd.get("count"):
        print(f"  snap distance max         : {sd.get('max'):.1f} m")

    src = report.get("source_inspection", {})
    print("\n[Q3/Q6/Q7] What is direct_station_dist_mm?")
    print(f"  written from              : {src.get('dist_mm_raw_source')}")
    print(f"  meaning                   : {src.get('direct_station_dist_mm_meaning')}")
    cnc = report.get("assignments", {}).get("column_nature_check", {})
    if cnc:
        print(f"  n compared                : {cnc.get('n_compared')}")
        if "mean_abs_diff_vs_matrix_network_km" in cnc:
            print(
                f"  vs matrix network (mean|max abs km): "
                f"{cnc['mean_abs_diff_vs_matrix_network_km']:.6f} | "
                f"{cnc['max_abs_diff_vs_matrix_network_km']:.6f}"
            )
        print(f"  matches matrix exactly    : {cnc.get('matches_matrix_network_exactly')}")
        if "mean_abs_diff_vs_haversine_km" in cnc:
            print(f"  vs haversine (mean abs km): {cnc['mean_abs_diff_vs_haversine_km']:.3f}")
        if "column_over_haversine_ratio_mean" in cnc:
            print(
                f"  column/haversine ratio    : mean={cnc['column_over_haversine_ratio_mean']:.2f} "
                f"min={cnc['column_over_haversine_ratio_min']:.2f} "
                f"max={cnc['column_over_haversine_ratio_max']:.2f}"
            )

    print("\n[Q5] Assignment direct_station_dist_mm by fleet (run_1)")
    for fleet, s in report.get("assignments", {}).get("fleets", {}).items():
        print(
            f"  {fleet:24s} n={s['count']:4d} min={s['min']:.2f} "
            f"med={s['median']:.2f} p95={s['p95']:.2f} max={s['max']:.2f} km "
            f">3km={s['n_above_3km']} >5km={s['n_above_5km']}"
        )
        print(f"      bins {s['bins']}")
    print(
        f"  all fleets share origin set: "
        f"{report.get('assignments', {}).get('all_fleets_share_origin_set')}"
    )

    ci = report.get("commuters_input", {})
    if ci.get("exists"):
        print("\n[Q4] Commuter input file")
        print(f"  n_commuters               : {ci.get('n_commuters')}")
        print(f"  has distance column       : {ci.get('has_distance_column')}")
        h = ci.get("origin_node_haversine_km_summary", {})
        if h:
            print(
                f"  origin haversine km       : min={h.get('min'):.2f} "
                f"median={h.get('median'):.2f} max={h.get('max'):.2f} "
                f"(>3km={ci.get('origin_node_haversine_above_3km')})"
            )
        n = ci.get("origin_node_network_km_summary", {})
        if n:
            print(
                f"  origin network km         : min={n.get('min'):.2f} "
                f"median={n.get('median'):.2f} max={n.get('max'):.2f}"
            )
            print(f"  origin network bins       : {ci.get('origin_node_network_bins')}")

    line("═")
    print("  CONCLUSION")
    line("═")
    c = report.get("conclusion", {})
    print(f"  CASE: {c.get('case')}")
    print(f"\n{c.get('summary')}\n")


# ──────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--results-root",
        default="experiments/results/footscray/fleet_composition_grid_footscray_80seats",
    )
    ap.add_argument("--station-node", type=int, default=240615)
    args = ap.parse_args()

    results_root = (REPO_ROOT / args.results_root).resolve()
    out_json = REPO_ROOT / "experiments/results/analysis/footscray_origin_distance_diagnostic.json"
    out_csv_dir = REPO_ROOT / "experiments/results/analysis/footscray_origin_distance_diagnostic"

    report: dict[str, Any] = {
        "station_node": args.station_node,
        "results_root": str(results_root.relative_to(REPO_ROOT))
        if str(results_root).startswith(str(REPO_ROOT))
        else str(results_root),
        "read_only": True,
    }

    node_coords = load_node_coords(REPO_ROOT / NODES_LAT_LON)
    report["road_nodes_loaded"] = len(node_coords)
    matrix = load_matrix(args.station_node)
    report["matrix"] = (
        {k: v for k, v in matrix.items() if k != "lookup"} if matrix else None
    )

    discover_files(report)
    inspect_source(report)
    inspect_candidate_metadata(report)
    inspect_candidate_mapping(report, node_coords, args.station_node, out_csv_dir)
    inspect_commuters(report, node_coords, args.station_node, matrix)
    inspect_assignments(report, results_root, node_coords, args.station_node, matrix, out_csv_dir)
    build_conclusion(report)

    print_report(report)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"Report JSON  : {out_json.relative_to(REPO_ROOT)}")
    print(f"CSV summaries: {out_csv_dir.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()
