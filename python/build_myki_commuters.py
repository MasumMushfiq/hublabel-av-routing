"""
build_myki_commuters.py
───────────────────────
Builds commuters.csv for simulate_first_mile_pyvrp.py using:
  - Real tap-on times from Myki ScanOnTransaction data  (drop_off_latest)
  - Spatially-sampled, reachability-verified origin nodes from build_commuters (C++)

Usage (called from Makefile):
  python build_myki_commuters.py \
      --myki-root  dataset/MYKI/Samp_9 \
      --nodes-file files/inputs/melton_nodes_lat_lon.csv \
      --dest-node  19858 \
      --cpp-bin    bin/build_commuters_reachable \
      --labels     dataset/MELTON/melton_dist \
      --out        files/inputs/commuters.csv \
      --year 2018 --week 26 --date 2018-06-25

Pipeline:
  1. Extract Myki tap-on times at Melton Station (morning peak, one day).
  2. Call C++ binary for N spatially-sampled, reachability-verified origins.
  3. Pair Myki time windows with C++ origins by distance bracket:
       random pairing (seed-controlled for reproducibility)
     With a fixed pickup_buffer all windows are the same width, so there
     is no meaningful spatial signal to sort on. Incompatible pairs are
     removed by the feasibility filter.
  4. Drop commuters whose haversine travel time cannot fit the window.
  5. Write commuters.csv.

MYKI COLUMN MAPPING  (pipe-delimited, 9 columns, 0-based index)
  Col 0  Mode            1=Bus 2=Train 3=Tram
  Col 1  BusinessDate    YYYY-MM-DD
  Col 2  DateTime        YYYY-MM-DD HH:MM:SS  <- tap-on timestamp
  Col 3  CardID          anonymised card identifier
  Col 7  StopLocationID  <- boarding stop

MELTON STATION STOP IDs  (from DimStopLocation)
  18, 19980, 21131, 21132, 21183, 21184, 21185
"""

import argparse
import csv
import gzip
import json
import math
import os
import subprocess
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

MELTON_STOP_IDS = {18, 19980, 21131, 21132, 21183, 21184, 21185}
TRAIN_MODE      = 2
COL_MODE        = 0
COL_DATETIME    = 2
COL_CARD_ID     = 3
COL_STOP_ID     = 7
WEEKDAY_CODES   = {0, 1, 2, 3, 4}   # Mon-Fri

_R_KM = 6371.0088
_DEFAULT_AV_SPEED_KMH = 25.0   # conservative speed for feasibility check


# ── Geo ────────────────────────────────────────────────────────────────────

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return _R_KM * 2 * math.asin(math.sqrt(a))


# ── Config loader ─────────────────────────────────────────────────────────

def load_peak_window(config_path: str) -> tuple[str, str]:
    """
    Read peak window from the experiment config JSON.
    Returns (peak_start_hhmm, peak_end_hhmm).

    Only reads start_time_minutes and end_time_minutes from time_window.
    buffer_before_deadline_minutes is the solver grace parameter (Aamir),
    NOT the pickup window width — do not read it here.
    """
    with open(config_path) as f:
        cfg = json.load(f)
    tw = cfg["time_window"]

    def mins_to_hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    start = mins_to_hhmm(tw["start_time_minutes"])
    end   = mins_to_hhmm(tw["end_time_minutes"])
    return start, end


# ── Step 1: Find files ─────────────────────────────────────────────────────

def find_gz_files(myki_root: str, year: int | None, week: int | None) -> list[Path]:
    root     = Path(myki_root)
    scan_dir = root / "ScanOnTransaction"
    if not scan_dir.exists():
        raise FileNotFoundError(
            f"ScanOnTransaction/ not found under {myki_root}.\n"
            f"Expected: {scan_dir}"
        )
    files = []
    for gz in sorted(scan_dir.rglob("*.txt.gz")):
        parts = gz.parts
        try:
            file_year = int([p for p in parts if p.isdigit() and len(p) == 4][0])
            file_week = int([p for p in parts if p.startswith("Week")][0].replace("Week", ""))
        except (IndexError, ValueError):
            continue
        if year is not None and file_year != year:
            continue
        if week is not None and file_week != week:
            continue
        files.append(gz)
    return files


# ── Step 2: Extract tap-ons ────────────────────────────────────────────────

def _fmt(minutes: float) -> str:
    """Round to nearest minute, format as HH:MM."""
    total = round(minutes)
    return f"{total // 60:02d}:{total % 60:02d}"


def extract_tap_ons(files: list[Path],
                    peak_start: time,
                    peak_end: time,
                    pickup_buffer_min: float,
                    date_filter: str | None) -> list[dict]:
    """
    Returns one record per unique card_id (earliest tap-on wins).

    tap-on time is treated as station arrival (drop_off_latest = tap_time).
    pickup_earliest = tap_time - pickup_buffer_min.

    date_str is derived from the parsed datetime (not from raw col 1) to avoid
    dependence on an undocumented column.
    """
    seen: dict[str, dict] = {}

    for gz in files:
        try:
            with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as f:
                for raw in f:
                    cols = raw.rstrip("\r\n").split("|")
                    if len(cols) < 9:
                        continue

                    try:
                        if int(cols[COL_MODE]) != TRAIN_MODE:
                            continue
                        if int(cols[COL_STOP_ID]) not in MELTON_STOP_IDS:
                            continue
                    except ValueError:
                        continue

                    # Parse datetime first; derive date from it (not from col 1)
                    dt_str = cols[COL_DATETIME].strip()
                    try:
                        dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue

                    if date_filter and dt.date().isoformat() != date_filter:
                        continue
                    if dt.weekday() not in WEEKDAY_CODES:
                        continue
                    if not (peak_start <= dt.time() <= peak_end):
                        continue

                    card_id = cols[COL_CARD_ID].strip()
                    tap_min = dt.hour * 60 + dt.minute + dt.second / 60.0

                    if card_id not in seen or tap_min < seen[card_id]["tap_min"]:
                        pickup = max(0.0, tap_min - pickup_buffer_min)
                        seen[card_id] = {
                            "tap_min":         tap_min,
                            "pickup_earliest": _fmt(pickup),
                            "drop_off_latest": _fmt(tap_min),
                            "window_min":      tap_min - pickup,
                        }
        except Exception as e:
            print(f"  WARNING {gz.name}: {e}", file=sys.stderr)

    return list(seen.values())


# ── Step 3: Call C++ binary ────────────────────────────────────────────────

def run_cpp_binary(cpp_bin: str, nodes_file: str, dest_node: int,
                   n: int, labels: str, seed: int) -> tuple[list[dict], str]:
    """
    Calls build_commuters_reachable. Returns (rows, tmp_path).
    Caller must os.unlink(tmp_path) when done.
    """
    tmp      = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cmd = [
        cpp_bin,
        "--nodes",           nodes_file,
        "--dest-node",       str(dest_node),
        "--n",               str(n),
        "--labels",          labels,
        "--seed",            str(seed),
        "--out",             tmp_path,
        "--tw-policy",       "fixed",
        "--pickup-earliest", "07:00",   # placeholder — overwritten in merge
        "--drop-off-latest", "09:30",
    ]
    print(f"  Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        os.unlink(tmp_path)
        print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"build_commuters exited {result.returncode}")

    with open(tmp_path, newline="") as f:
        rows = list(csv.DictReader(f))

    # Schema check — fail loudly if C++ output format ever changes
    required = {"origin_node", "destination_node"}
    if rows and not required.issubset(rows[0].keys()):
        os.unlink(tmp_path)
        raise RuntimeError(
            f"C++ output missing required columns. "
            f"Got: {list(rows[0].keys())}. Expected: {sorted(required)}"
        )

    return rows, tmp_path


# ── Step 4: Distance-aware pairing + feasibility filter ───────────────────
def load_node_coords(nodes_file: str) -> dict[int, tuple[float, float]]:
    coords: dict[int, tuple[float, float]] = {}
    with open(nodes_file, newline="") as f:
        for row in csv.DictReader(f):
            lc  = {k.lower(): v for k, v in row.items()}
            nid_raw = lc.get("node_id") or lc.get("id") or lc.get("node") or lc.get("osmid")
            lat_raw = lc.get("lat") or lc.get("latitude") or lc.get("y")
            lon_raw = lc.get("lon") or lc.get("lng") or lc.get("longitude") or lc.get("x")
            if not nid_raw or not lat_raw or not lon_raw:
                continue
            try:
                nid = int(nid_raw)
                lat = float(lat_raw)
                lon = float(lon_raw)
            except (TypeError, ValueError):
                continue
            coords[nid] = (lat, lon)
    return coords


def pair_and_filter(myki_rows: list[dict],
                    cpp_rows: list[dict],
                    nodes_file: str,
                    dest_node: int,
                    av_speed_kmh: float,
                    seed: int) -> list[dict]:
    """
    Pairs time windows with origin nodes in a distance-consistent way:
      shuffle both lists with the same seed for reproducibility
      pair by rank -> random assignment, no spatial bias
      feasibility filter drops pairs where travel time exceeds window width

    Then drop any pair where minimum travel time > window width.
    """
    coords     = load_node_coords(nodes_file)
    dest_coord = coords.get(dest_node)
    if dest_coord is None:
        print(f"  WARNING: dest_node {dest_node} not in nodes file — "
              f"skipping distance-aware pairing and feasibility filter.",
              file=sys.stderr)

    av_km_per_min = av_speed_kmh / 60.0

    # Pairing is random (shuffled by seed for reproducibility).
    # With a fixed pickup_buffer every commuter has the same window width,
    # so there is no meaningful signal to sort on — tap-on time does not
    # predict how far someone lives from the station.
    # The feasibility filter below handles incompatible pairs.
    import random as _random
    rng = _random.Random(seed)
    myki_sorted = list(myki_rows)
    rng.shuffle(myki_sorted)
    cpp_sorted  = list(cpp_rows)
    rng.shuffle(cpp_sorted)

    n         = min(len(myki_sorted), len(cpp_sorted))
    merged    = []
    n_dropped = 0

    for i in range(n):
        myki = myki_sorted[i]
        cpp  = cpp_sorted[i]

        # Feasibility: haversine travel time must fit inside window
        if dest_coord:
            c = coords.get(int(cpp["origin_node"]))
            if c:
                dist_km    = haversine_km(c[0], c[1], dest_coord[0], dest_coord[1])
                min_travel = dist_km / av_km_per_min
                if min_travel > myki["window_min"]:
                    n_dropped += 1
                    continue

        merged.append({
            "pickup_earliest":  myki["pickup_earliest"],
            "drop_off_latest":  myki["drop_off_latest"],
            "origin_node":      cpp["origin_node"],
            "destination_node": cpp["destination_node"],
        })

    if n_dropped:
        print(f"  Feasibility filter: dropped {n_dropped} "
              f"(min travel time > window at {av_speed_kmh} km/h)")
    print(f"  Kept: {len(merged)}")
    return merged


# ── Step 5: Write ──────────────────────────────────────────────────────────

def write_csv(rows: list[dict], out_path: str) -> None:
    fields = ["id", "origin_node", "destination_node",
              "pickup_earliest", "drop_off_latest"]
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for i, row in enumerate(rows):
            w.writerow({
                "id":               i,
                "origin_node":      row["origin_node"],
                "destination_node": row["destination_node"],
                "pickup_earliest":  row["pickup_earliest"],
                "drop_off_latest":  row["drop_off_latest"],
            })


def default_metadata_path(out_path: str) -> str:
    out = Path(out_path)
    return str(out.with_name(f"{out.stem}_metadata.json"))


def write_metadata(metadata_path: str,
                   output_csv: str,
                   destination_node: int,
                   myki_root: str,
                   nodes_file: str,
                   cpp_bin: str,
                   labels: str,
                   config: str,
                   year: int | None,
                   week: int | None,
                   date: str | None,
                   peak_start: str,
                   peak_end: str,
                   pickup_buffer_min: float,
                   av_speed_kmh: float,
                   seed: int,
                   tap_ons_extracted: int,
                   reachable_origins_generated: int,
                   commuters_written: int) -> None:
    metadata = {
        "source": "Myki ScanOnTransaction",
        "station_name": "Melton",
        "destination_node": destination_node,
        "myki_stop_ids": sorted(MELTON_STOP_IDS),
        "myki_root": myki_root,
        "nodes_file": nodes_file,
        "cpp_bin": cpp_bin,
        "labels": labels,
        "config": config,
        "year": year,
        "week": week,
        "date": date,
        "peak_start": peak_start,
        "peak_end": peak_end,
        "pickup_buffer_min": pickup_buffer_min,
        "av_speed_kmh": av_speed_kmh,
        "seed": seed,
        "tap_ons_extracted": tap_ons_extracted,
        "reachable_origins_generated": reachable_origins_generated,
        "commuters_written": commuters_written,
        "origin_candidate_source": "road_network_nodes",
        "origin_sampling_backend": "build_commuters_reachable",
        "origin_sampling_method": (
            "farthest_point_ordering_then_bidirectional_reachability"
        ),
        "residential_address_based": False,
        "temporal_demand_source": "Myki tap-on times",
        "temporal_spatial_pairing": "seeded_random_pairing",
        "origin_generation_method": (
            "reachable_random_pairing_with_haversine_feasibility_filter"
        ),
        "feasibility_filter": {
            "speed_kmh": av_speed_kmh,
            "description": (
                "Drops origin/time-window pairs when haversine travel time "
                "at speed_kmh exceeds the pickup window width."
            ),
        },
        "output_csv": output_csv,
    }
    Path(metadata_path).parent.mkdir(parents=True, exist_ok=True)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Build commuters.csv: Myki tap-on times + C++ spatial origins."
    )
    p.add_argument("--myki-root",      required=True)
    p.add_argument("--nodes-file",     required=True)
    p.add_argument("--dest-node",      required=True, type=int)
    p.add_argument("--cpp-bin",        required=True)
    p.add_argument("--labels",         required=True)
    p.add_argument("--out",            default="files/inputs/commuters.csv")
    p.add_argument("--config",         required=True,
                   help="Experiment config JSON (same file used by PyVRP). "
                        "Reads start_time_minutes and end_time_minutes from "
                        "time_window block — single source of truth for peak window.")
    p.add_argument("--year",           type=int, default=None)
    p.add_argument("--week",           type=int, default=None)
    p.add_argument("--date",           default=None,
                   help="Single day YYYY-MM-DD (strongly recommended).")
    p.add_argument("--pickup-buffer",  type=float, default=30.0,
                   help="Pickup window width in minutes: pickup_earliest = "
                        "drop_off_latest - N. Separate from solver grace period. "
                        "(default: 30)")
    p.add_argument("--av-speed-kmh",   type=float, default=_DEFAULT_AV_SPEED_KMH,
                   help=f"AV speed for feasibility check in km/h (default: {_DEFAULT_AV_SPEED_KMH})")
    p.add_argument("--seed",           type=int, default=42)
    p.add_argument("--metadata-out",   default=None,
                   help="Metadata JSON path. Defaults to <out_stem>_metadata.json next to --out.")
    args = p.parse_args()

    peak_start_str, peak_end_str = load_peak_window(args.config)
    peak_start    = datetime.strptime(peak_start_str, "%H:%M").time()
    peak_end      = datetime.strptime(peak_end_str,   "%H:%M").time()
    pickup_buffer = args.pickup_buffer

    print(f"\n{'='*56}\n  BUILD MYKI COMMUTERS\n{'='*56}")

    print(f"\n-- Step 1: Extract Myki tap-ons --")
    files = find_gz_files(args.myki_root, args.year, args.week)
    if not files:
        sys.exit("ERROR: No ScanOnTransaction files found.")
    print(f"  Config:  {args.config}")
    print(f"  Window:  {peak_start_str} – {peak_end_str}  (pickup buffer {pickup_buffer} min)")
    print(f"  Files:   {len(files)}")
    if args.date:
        print(f"  Date:    {args.date}")
    else:
        print(f"  WARNING: no --date; all weekdays in the week will be pooled.")
    myki_rows = extract_tap_ons(
        files, peak_start, peak_end,
        pickup_buffer,
        date_filter=args.date,
    )
    if not myki_rows:
        sys.exit("ERROR: No tap-ons matched filters.")
    print(f"  Extracted: {len(myki_rows)}")

    print(f"\n-- Step 2: Spatial origin nodes (C++) --")
    cpp_rows, tmp_path = run_cpp_binary(
        args.cpp_bin, args.nodes_file, args.dest_node,
        len(myki_rows), args.labels, args.seed,
    )
    print(f"  Reachable origins: {len(cpp_rows)}")

    print(f"\n-- Step 3: Pair by distance + feasibility filter --")
    print(f"  AV speed: {args.av_speed_kmh} km/h")
    merged = pair_and_filter(
        myki_rows, cpp_rows,
        args.nodes_file, args.dest_node, args.av_speed_kmh,
        seed=args.seed,
    )

    print(f"\n-- Step 4: Write --")
    write_csv(merged, args.out)
    metadata_out = args.metadata_out or default_metadata_path(args.out)
    write_metadata(
        metadata_out,
        output_csv=args.out,
        destination_node=args.dest_node,
        myki_root=args.myki_root,
        nodes_file=args.nodes_file,
        cpp_bin=args.cpp_bin,
        labels=args.labels,
        config=args.config,
        year=args.year,
        week=args.week,
        date=args.date,
        peak_start=peak_start_str,
        peak_end=peak_end_str,
        pickup_buffer_min=pickup_buffer,
        av_speed_kmh=args.av_speed_kmh,
        seed=args.seed,
        tap_ons_extracted=len(myki_rows),
        reachable_origins_generated=len(cpp_rows),
        commuters_written=len(merged),
    )
    print(f"  Done: {len(merged)} commuters -> {args.out}\n")
    print(f"  Metadata: {metadata_out}\n")

    try:
        os.unlink(tmp_path)
    except OSError:
        pass


if __name__ == "__main__":
    main()
