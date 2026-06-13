#!/usr/bin/env python3
"""
build_residential_origin_candidates.py
──────────────────────────────────────
Extract residential/address origin candidates from an OSM .pbf file, map them
onto the existing road-network node set, remove candidates within a walking
threshold of the station, and write a road-node candidate CSV that can be passed
unchanged to build_myki_commuters.py as --nodes-file.

This script does NOT generate commuters.csv. It only builds a better candidate
origin pool for the existing reachability-validated Myki commuter pipeline.

Example:
  python python/build_residential_origin_candidates.py \
    --osm-pbf dataset/OSM_DATA/melton_osm.pbf \
    --road-nodes files/inputs/melton_nodes_lat_lon.csv \
    --station-node 19858 \
    --walking-threshold-m 800 \
    --out-nodes files/inputs/melton_residential_candidate_nodes.csv \
    --out-points files/inputs/melton_residential_candidate_points.csv \
    --out-mapping files/inputs/melton_residential_candidate_node_mapping.csv \
    --metadata-out files/inputs/melton_residential_candidates_metadata.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import osmium
import pandas as pd
from scipy.spatial import KDTree


R_EARTH_M = 6_371_008.8

# Residential building values commonly used in OSM.
RESIDENTIAL_BUILDING_VALUES = {
    "house",
    "residential",
    "apartments",
    "detached",
    "semidetached_house",
    "semi_detached",
    "terrace",
    "bungalow",
    "cabin",
    "dormitory",
    "static_caravan",
}

# Values that are clearly not residential homes for this first-mile origin pool.
EXCLUDED_BUILDING_VALUES = {
    "commercial",
    "industrial",
    "retail",
    "warehouse",
    "school",
    "university",
    "college",
    "hospital",
    "church",
    "chapel",
    "cathedral",
    "mosque",
    "temple",
    "synagogue",
    "public",
    "civic",
    "train_station",
    "transportation",
    "garage",
    "garages",
    "shed",
    "roof",
    "service",
    "kiosk",
    "toilets",
    "parking",
    "sports_centre",
    "stadium",
    "grandstand",
    "farm_auxiliary",
    "barn",
}

ADDRESS_KEYS = {
    "addr:housenumber",
    "addr:street",
    "addr:unit",
    "addr:flats",
    "addr:suburb",
    "addr:postcode",
}


@dataclass(frozen=True)
class CandidatePoint:
    candidate_id: str
    source_type: str
    osm_id: int
    lat: float
    lon: float
    candidate_kind: str
    building: str
    has_address: bool
    addr_housenumber: str
    addr_street: str
    addr_suburb: str
    addr_postcode: str


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R_EARTH_M * 2 * math.asin(math.sqrt(a))


def latlon_to_local_xy_m(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """Equirectangular local projection, sufficient for nearest-node lookup in one station catchment."""
    x = math.radians(lon - ref_lon) * R_EARTH_M * math.cos(math.radians(ref_lat))
    y = math.radians(lat - ref_lat) * R_EARTH_M
    return x, y


def tags_to_dict(tags: Any) -> dict[str, str]:
    return {tag.k: tag.v for tag in tags}


def has_address_tags(tags: dict[str, str]) -> bool:
    return any(k in tags for k in ADDRESS_KEYS) or any(k.startswith("addr:") for k in tags)


def classify_candidate(tags: dict[str, str]) -> tuple[bool, str]:
    """
    Return (keep, candidate_kind).

    Conservative first-pass policy:
      - keep address-tagged objects unless explicitly non-residential by building tag;
      - keep residential building types;
      - keep building=yes only when it has address tags;
      - exclude clearly non-residential buildings.
    """
    building = tags.get("building", "").strip().lower()
    has_addr = has_address_tags(tags)

    if building in EXCLUDED_BUILDING_VALUES:
        return False, "excluded_non_residential_building"

    if has_addr and building not in EXCLUDED_BUILDING_VALUES:
        if building:
            return True, "addressed_building_or_object"
        return True, "address_point_or_object"

    if building in RESIDENTIAL_BUILDING_VALUES:
        return True, "residential_building"

    return False, "not_residential_candidate"


class ResidentialCandidateHandler(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[CandidatePoint] = []
        self.stats: Counter[str] = Counter()

    def _append_candidate(
        self,
        *,
        source_type: str,
        osm_id: int,
        lat: float,
        lon: float,
        tags: dict[str, str],
        candidate_kind: str,
    ) -> None:
        if not math.isfinite(lat) or not math.isfinite(lon):
            self.stats["invalid_coordinate"] += 1
            return

        building = tags.get("building", "")
        self.candidates.append(
            CandidatePoint(
                candidate_id=f"{source_type}/{osm_id}",
                source_type=source_type,
                osm_id=int(osm_id),
                lat=float(lat),
                lon=float(lon),
                candidate_kind=candidate_kind,
                building=building,
                has_address=has_address_tags(tags),
                addr_housenumber=tags.get("addr:housenumber", ""),
                addr_street=tags.get("addr:street", ""),
                addr_suburb=tags.get("addr:suburb", ""),
                addr_postcode=tags.get("addr:postcode", ""),
            )
        )
        self.stats[f"kept_{candidate_kind}"] += 1

    def node(self, n: osmium.osm.Node) -> None:
        tags = tags_to_dict(n.tags)
        keep, kind = classify_candidate(tags)
        if not keep:
            self.stats[kind] += 1
            return
        if not n.location.valid():
            self.stats["node_missing_location"] += 1
            return
        self._append_candidate(
            source_type="node",
            osm_id=n.id,
            lat=n.location.lat,
            lon=n.location.lon,
            tags=tags,
            candidate_kind=kind,
        )

    def way(self, w: osmium.osm.Way) -> None:
        tags = tags_to_dict(w.tags)
        keep, kind = classify_candidate(tags)
        if not keep:
            self.stats[kind] += 1
            return

        coords: list[tuple[float, float]] = []
        for node in w.nodes:
            try:
                if node.location.valid():
                    coords.append((node.location.lat, node.location.lon))
            except Exception:
                continue

        if not coords:
            self.stats["way_missing_locations"] += 1
            return

        # If the polygon is closed, avoid double-counting the duplicated last point.
        if len(coords) > 1 and coords[0] == coords[-1]:
            coords = coords[:-1]

        lat = sum(c[0] for c in coords) / len(coords)
        lon = sum(c[1] for c in coords) / len(coords)

        self._append_candidate(
            source_type="way",
            osm_id=w.id,
            lat=lat,
            lon=lon,
            tags=tags,
            candidate_kind=kind,
        )


def load_road_nodes(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Road-node CSV not found: {path}")

    df = pd.read_csv(path)
    lower = {c.lower(): c for c in df.columns}

    node_col = lower.get("node_id") or lower.get("id") or lower.get("node") or lower.get("osmid")
    lat_col = lower.get("lat") or lower.get("latitude") or lower.get("y")
    lon_col = lower.get("lon") or lower.get("lng") or lower.get("longitude") or lower.get("x")

    if not node_col or not lat_col or not lon_col:
        raise ValueError(
            f"{path} must contain node_id/id, lat, lon columns. Got columns: {list(df.columns)}"
        )

    out = df[[node_col, lat_col, lon_col]].rename(
        columns={node_col: "node_id", lat_col: "lat", lon_col: "lon"}
    )
    out = out.dropna(subset=["node_id", "lat", "lon"]).copy()
    out["node_id"] = out["node_id"].astype(int)
    out["lat"] = out["lat"].astype(float)
    out["lon"] = out["lon"].astype(float)
    out = out.drop_duplicates(subset=["node_id"]).reset_index(drop=True)

    if out.empty:
        raise ValueError(f"No valid road nodes found in {path}")
    return out


def write_candidate_points(candidates: list[CandidatePoint], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "candidate_id",
        "source_type",
        "osm_id",
        "lat",
        "lon",
        "candidate_kind",
        "building",
        "has_address",
        "addr_housenumber",
        "addr_street",
        "addr_suburb",
        "addr_postcode",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for c in candidates:
            writer.writerow(c.__dict__)


def map_candidates_to_road_nodes(
    candidates: list[CandidatePoint],
    road_nodes: pd.DataFrame,
    station_node: int,
    walking_threshold_m: float,
    max_station_distance_m: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    station_rows = road_nodes.loc[road_nodes["node_id"] == station_node]
    if station_rows.empty:
        raise ValueError(f"Station node {station_node} not found in road-node CSV")

    station_lat = float(station_rows.iloc[0]["lat"])
    station_lon = float(station_rows.iloc[0]["lon"])

    node_xy = [
        latlon_to_local_xy_m(float(r.lat), float(r.lon), station_lat, station_lon)
        for r in road_nodes.itertuples(index=False)
    ]
    tree = KDTree(node_xy)

    mapping_rows: list[dict[str, Any]] = []
    node_candidate_counts: Counter[int] = Counter()
    node_kind_counts: dict[int, Counter[str]] = defaultdict(Counter)

    for c in candidates:
        qx, qy = latlon_to_local_xy_m(c.lat, c.lon, station_lat, station_lon)
        _, idx = tree.query((qx, qy))
        node = road_nodes.iloc[int(idx)]
        nearest_node = int(node["node_id"])
        nearest_lat = float(node["lat"])
        nearest_lon = float(node["lon"])

        snap_distance_m = haversine_m(c.lat, c.lon, nearest_lat, nearest_lon)
        direct_station_distance_m = haversine_m(c.lat, c.lon, station_lat, station_lon)

        kept = True
        reason = "kept"
        if direct_station_distance_m <= walking_threshold_m:
            kept = False
            reason = "within_walking_threshold"
        elif (
            max_station_distance_m is not None
            and direct_station_distance_m > max_station_distance_m
        ):
            kept = False
            reason = "beyond_max_station_distance"
        elif nearest_node == station_node:
            kept = False
            reason = "mapped_to_station_node"

        if kept:
            node_candidate_counts[nearest_node] += 1
            node_kind_counts[nearest_node][c.candidate_kind] += 1

        mapping_rows.append(
            {
                "candidate_id": c.candidate_id,
                "source_type": c.source_type,
                "osm_id": c.osm_id,
                "candidate_lat": c.lat,
                "candidate_lon": c.lon,
                "candidate_kind": c.candidate_kind,
                "building": c.building,
                "has_address": c.has_address,
                "nearest_node": nearest_node,
                "nearest_node_lat": nearest_lat,
                "nearest_node_lon": nearest_lon,
                "snap_distance_m": snap_distance_m,
                "direct_station_distance_m": direct_station_distance_m,
                "kept": kept,
                "filter_reason": reason,
            }
        )

    mapping_df = pd.DataFrame(mapping_rows)

    kept_node_ids = sorted(node_candidate_counts.keys())
    nodes_df = road_nodes.loc[road_nodes["node_id"].isin(kept_node_ids), ["node_id", "lat", "lon"]].copy()
    nodes_df["candidate_count"] = nodes_df["node_id"].map(node_candidate_counts).astype(int)
    nodes_df["dominant_candidate_kind"] = nodes_df["node_id"].map(
        lambda nid: node_kind_counts[int(nid)].most_common(1)[0][0] if node_kind_counts[int(nid)] else ""
    )
    nodes_df = nodes_df.sort_values(["node_id"]).reset_index(drop=True)

    stats = {
        "station_node": station_node,
        "station_lat": station_lat,
        "station_lon": station_lon,
        "walking_threshold_m": walking_threshold_m,
        "max_station_distance_m": max_station_distance_m,
        "raw_candidates": len(candidates),
        "mapped_candidate_rows": int(len(mapping_df)),
        "kept_candidate_rows_after_filter": int(mapping_df["kept"].sum()) if not mapping_df.empty else 0,
        "unique_candidate_road_nodes_after_filter": int(len(nodes_df)),
        "filtered_candidate_rows": int((~mapping_df["kept"]).sum()) if not mapping_df.empty else 0,
        "removed_by_walking_threshold": int(
            (mapping_df["filter_reason"] == "within_walking_threshold").sum()
        ) if not mapping_df.empty else 0,
        "removed_by_outer_catchment": int(
            (mapping_df["filter_reason"] == "beyond_max_station_distance").sum()
        ) if not mapping_df.empty else 0,
        "filter_reason_counts": mapping_df["filter_reason"].value_counts().to_dict() if not mapping_df.empty else {},
    }

    if not mapping_df.empty:
        for col in ["snap_distance_m", "direct_station_distance_m"]:
            kept_values = mapping_df.loc[mapping_df["kept"], col]
            if not kept_values.empty:
                stats[f"{col}_kept_summary"] = {
                    "min": float(kept_values.min()),
                    "p25": float(kept_values.quantile(0.25)),
                    "median": float(kept_values.median()),
                    "p75": float(kept_values.quantile(0.75)),
                    "p95": float(kept_values.quantile(0.95)),
                    "max": float(kept_values.max()),
                }

    return mapping_df, nodes_df, stats


def write_nodes_for_cpp(nodes_df: pd.DataFrame, out_path: Path, include_debug_columns: bool) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if include_debug_columns:
        nodes_df.to_csv(out_path, index=False)
    else:
        nodes_df[["node_id", "lat", "lon"]].to_csv(out_path, index=False)


def write_metadata(
    path: Path,
    *,
    osm_pbf: Path,
    road_nodes: Path,
    out_nodes: Path,
    out_points: Path,
    out_mapping: Path,
    handler_stats: Counter[str],
    mapping_stats: dict[str, Any],
    include_debug_columns_in_nodes: bool,
) -> None:
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "python/build_residential_origin_candidates.py",
        "purpose": "Build residential/address candidate road-node pool for Myki commuter generation.",
        "origin_generation_stage": "candidate_pool_preprocessing_only",
        "osm_pbf": str(osm_pbf),
        "road_nodes": str(road_nodes),
        "out_nodes": str(out_nodes),
        "out_points": str(out_points),
        "out_mapping": str(out_mapping),
        "out_nodes_schema": (
            "node_id,lat,lon plus debug columns" if include_debug_columns_in_nodes else "node_id,lat,lon"
        ),
        "candidate_source": f"Residential/address candidates extracted from supplied OSM PBF: {osm_pbf}",
        "candidate_extraction_policy": {
            "kept": {
                "address_tagged_objects": "objects with addr:* tags unless clearly non-residential by building tag",
                "residential_buildings": sorted(RESIDENTIAL_BUILDING_VALUES),
                "building_yes_with_address": True,
            },
            "excluded_building_values": sorted(EXCLUDED_BUILDING_VALUES),
        },
        "nearest_node_mapping": {
            "method": "KDTree over local equirectangular meter coordinates from existing road-node CSV",
            "distance_reported": "haversine meters between candidate point and nearest road node",
        },
        "walking_filter": {
            "method": "direct haversine distance from candidate point to station node",
            "note": "This is not pedestrian-network distance; it is a reproducible first-pass exclusion threshold.",
        },
        "walking_threshold_m": mapping_stats["walking_threshold_m"],
        "max_station_distance_m": mapping_stats["max_station_distance_m"],
        "raw_candidates": mapping_stats["raw_candidates"],
        "kept_candidate_rows": mapping_stats["kept_candidate_rows_after_filter"],
        "unique_candidate_road_nodes": mapping_stats["unique_candidate_road_nodes_after_filter"],
        "removed_by_walking_threshold": mapping_stats["removed_by_walking_threshold"],
        "removed_by_outer_catchment": mapping_stats["removed_by_outer_catchment"],
        "handler_stats": dict(handler_stats),
        "mapping_stats": mapping_stats,
        "next_pipeline_step": (
            "Pass out_nodes to python/build_myki_commuters.py as --nodes-file with --origin-sampling random; "
            "build_commuters_reachable then performs bidirectional reachability validation."
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Extract residential/address OSM candidates and map them to existing road-network nodes."
    )
    p.add_argument("--osm-pbf", required=True, type=Path, help="Input OSM .pbf file, e.g. dataset/OSM_DATA/melton_osm.pbf")
    p.add_argument("--road-nodes", required=True, type=Path, help="Road-node CSV with node_id,lat,lon")
    p.add_argument("--station-node", required=True, type=int, help="Station/depot road node id, e.g. 19858")
    p.add_argument("--walking-threshold-m", type=float, default=800.0, help="Exclude candidates at or below this direct distance to station")
    p.add_argument(
        "--max-station-distance-m",
        type=float,
        default=None,
        help="Optional outer direct-distance catchment in metres; defaults to no outer filter",
    )
    p.add_argument("--out-nodes", required=True, type=Path, help="Output road-node candidate CSV for build_myki_commuters.py --nodes-file")
    p.add_argument("--out-points", required=True, type=Path, help="Output raw extracted residential/address candidate points CSV")
    p.add_argument("--out-mapping", required=True, type=Path, help="Output candidate-to-road-node mapping diagnostics CSV")
    p.add_argument("--metadata-out", required=True, type=Path, help="Output metadata JSON")
    p.add_argument(
        "--include-debug-columns-in-nodes",
        action="store_true",
        help="Write candidate_count and dominant_candidate_kind into --out-nodes. Default keeps only node_id,lat,lon for maximum C++ compatibility.",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if (
        args.max_station_distance_m is not None
        and args.max_station_distance_m <= args.walking_threshold_m
    ):
        sys.exit(
            "ERROR: --max-station-distance-m must be greater than "
            "--walking-threshold-m"
        )

    if not args.osm_pbf.exists():
        sys.exit(f"ERROR: OSM PBF not found: {args.osm_pbf}")

    print("\n" + "=" * 64)
    print("  BUILD RESIDENTIAL ORIGIN CANDIDATE NODES")
    print("=" * 64)
    print(f"OSM PBF             : {args.osm_pbf}")
    print(f"Road nodes          : {args.road_nodes}")
    print(f"Station node        : {args.station_node}")
    print(f"Walking threshold   : {args.walking_threshold_m:.1f} m")
    if args.max_station_distance_m is None:
        print("Outer catchment     : no outer catchment filter")
    else:
        print(f"Outer catchment     : {args.max_station_distance_m:.1f} m")

    print("\n-- Step 1: Load road nodes --")
    road_nodes = load_road_nodes(args.road_nodes)
    print(f"  Road nodes loaded: {len(road_nodes):,}")

    print("\n-- Step 2: Extract OSM residential/address candidates --")
    handler = ResidentialCandidateHandler()
    try:
        # locations=True allows way node coordinates to be available for centroid approximation.
        handler.apply_file(str(args.osm_pbf), locations=True)
    except Exception as e:
        raise RuntimeError(f"Failed while reading OSM PBF {args.osm_pbf}: {e}") from e

    candidates = handler.candidates
    print(f"  Raw candidates extracted: {len(candidates):,}")
    if not candidates:
        sys.exit("ERROR: No residential/address candidates found. Check OSM extract/tags.")

    write_candidate_points(candidates, args.out_points)
    print(f"  Candidate points written: {args.out_points}")

    print("\n-- Step 3: Map candidates to nearest road nodes and apply distance filters --")
    mapping_df, nodes_df, mapping_stats = map_candidates_to_road_nodes(
        candidates=candidates,
        road_nodes=road_nodes,
        station_node=args.station_node,
        walking_threshold_m=args.walking_threshold_m,
        max_station_distance_m=args.max_station_distance_m,
    )

    args.out_mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping_df.to_csv(args.out_mapping, index=False)
    write_nodes_for_cpp(nodes_df, args.out_nodes, args.include_debug_columns_in_nodes)

    print(f"  Mapping diagnostics written: {args.out_mapping}")
    print(f"  Candidate road nodes written: {args.out_nodes}")
    print(f"  Kept candidate rows: {mapping_stats['kept_candidate_rows_after_filter']:,}")
    print(f"  Unique candidate road nodes: {mapping_stats['unique_candidate_road_nodes_after_filter']:,}")

    if mapping_stats["unique_candidate_road_nodes_after_filter"] < 1465:
        print(
            "  WARNING: fewer than 1,465 unique candidate road nodes after filtering. "
            "The Myki commuter builder may not be able to produce the full demand.",
            file=sys.stderr,
        )

    print("\n-- Step 4: Write metadata --")
    write_metadata(
        args.metadata_out,
        osm_pbf=args.osm_pbf,
        road_nodes=args.road_nodes,
        out_nodes=args.out_nodes,
        out_points=args.out_points,
        out_mapping=args.out_mapping,
        handler_stats=handler.stats,
        mapping_stats=mapping_stats,
        include_debug_columns_in_nodes=args.include_debug_columns_in_nodes,
    )
    print(f"  Metadata written: {args.metadata_out}")

    print("\nDone. Next step: use --out-nodes as build_myki_commuters.py --nodes-file with --origin-sampling random.\n")


if __name__ == "__main__":
    main()
