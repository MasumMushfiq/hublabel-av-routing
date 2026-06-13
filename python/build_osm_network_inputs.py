#!/usr/bin/env python3
from __future__ import annotations

"""
build_osm_network_inputs.py

Convert an OSM PBF file into hub-label-compatible graph and coordinate files.

This replaces the old map_processor/src/osm_convert.py dependency and keeps the
full station data-preparation pipeline inside the hub_label project.

Outputs:
  files/inputs/<station>_nodes_lat_lon.csv
  files/inputs/<station>_graph_speed.txt
  files/inputs/<station>_graph_distance.txt
  files/inputs/<station>_graph_time.txt
  files/inputs/<station>_network_metadata.json

Formats:
  <station>_nodes_lat_lon.csv:
      node_id,lat,lon

  <station>_graph_speed.txt:
      u v length_m speed_kph

  <station>_graph_distance.txt:
      u v distance_mm

  <station>_graph_time.txt:
      u v time_ms
"""

from pyrosm import OSM

import argparse
import importlib.metadata as importlib_metadata
import json
import math
import re
import sys
from pathlib import Path


_DEFAULT_SPEEDS_KPH = {
    "motorway": 110.0,
    "trunk": 100.0,
    "primary": 90.0,
    "secondary": 80.0,
    "tertiary": 70.0,
    "residential": 50.0,
    "service": 30.0,
}

_NUM = re.compile(r"\d+(\.\d+)?")

def get_package_version(package: str) -> str:
    try:
        return importlib_metadata.version(package)
    except importlib_metadata.PackageNotFoundError:
        return "not found"


def parse_speed_kph(maxspeed, highway) -> float:
    """
    Return speed in km/h.

    Handles values such as:
      60
      60 km/h
      60mph
      list-like pyrosm values
      missing / NaN

    Falls back by OSM highway class and clamps to [10, 130].
    """
    if isinstance(maxspeed, (list, tuple)):
        maxspeed = maxspeed[0] if maxspeed else None

    if maxspeed is None or str(maxspeed) == "nan":
        s = ""
    else:
        s = str(maxspeed).lower().strip()

    match = _NUM.search(s)
    if match:
        value = float(match.group(0))
        if "mph" in s:
            value *= 1.60934
        return max(10.0, min(130.0, value))

    highway_key = str(highway).lower().strip() if highway is not None else ""
    return _DEFAULT_SPEEDS_KPH.get(highway_key, 50.0)


def edge_time_ms(length_m: float, speed_kph: float) -> int:
    """Convert edge length and speed to integer milliseconds."""
    meters_per_second = max(0.1, float(speed_kph)) * (1000.0 / 3600.0)
    return int(math.ceil((float(length_m) / meters_per_second) * 1000.0))


def is_oneway(flag) -> bool:
    """
    True if the way is forward-only.

    Matching old behavior:
      - yes / true / 1 => one-way
      - no / false / 0 / missing => two-way
      - -1 is treated as two-way rather than reverse-only
    """
    if flag is None:
        return False

    s = str(flag).strip().lower()

    if s in {"yes", "true", "1"}:
        return True

    if s == "-1":
        return False

    return False


def row_value(row, name: str, default=None):
    return getattr(row, name) if hasattr(row, name) else default


def process_osm_to_graph_data(
    pbf_path: Path,
    station: str,
    output_dir: Path,
) -> None:
    pbf_path = Path(pbf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    station = station.lower().strip()

    if not station:
        raise ValueError("--station cannot be empty")

    if not pbf_path.exists():
        raise FileNotFoundError(f"PBF not found: {pbf_path}")

    print(f"Loading PBF and extracting driving network: {pbf_path}")
    osm = OSM(str(pbf_path))
    nodes, edges = osm.get_network(nodes=True, network_type="driving")

    if edges is None or len(edges) == 0:
        raise RuntimeError("No edges extracted using network_type='driving'.")

    for col in ("u", "v", "length"):
        if col not in edges.columns:
            raise RuntimeError(
                f"Edges missing required column '{col}'. "
                f"Available columns: {list(edges.columns)}"
            )

    if "id" not in nodes.columns:
        raise RuntimeError(f"Nodes missing required column 'id'. Columns: {list(nodes.columns)}")

    lat_col = "lat" if "lat" in nodes.columns else ("y" if "y" in nodes.columns else None)
    lon_col = "lon" if "lon" in nodes.columns else ("x" if "x" in nodes.columns else None)

    if lat_col is None or lon_col is None:
        raise RuntimeError(f"Nodes missing lat/lon columns. Columns: {list(nodes.columns)}")

    # OSM node ID -> compact 0-based node ID.
    id_series = nodes["id"].reset_index(drop=True)
    nodes_dict = {int(osm_id): idx for idx, osm_id in id_series.items()}

    nodes_csv = output_dir / f"{station}_nodes_lat_lon.csv"
    graph_debug_txt = output_dir / f"{station}_graph.txt"
    dist_txt = output_dir / f"{station}_graph_distance.txt"
    time_txt = output_dir / f"{station}_graph_time.txt"
    speed_txt = output_dir / f"{station}_graph_speed.txt"
    metadata_json = output_dir / f"{station}_network_metadata.json"

    print("Writing node coordinate file...")
    with nodes_csv.open("w", encoding="utf-8") as f:
        f.write("node_id,lat,lon\n")
        for row in nodes.itertuples(index=False):
            osm_id = int(getattr(row, "id"))
            node_id = nodes_dict[osm_id]
            lat = getattr(row, lat_col)
            lon = getattr(row, lon_col)
            f.write(f"{node_id},{lat},{lon}\n")

    print("Writing debug graph file...")
    with graph_debug_txt.open("w", encoding="utf-8") as f:
        f.write(f"{len(nodes)}\n")
        f.write(f"{len(edges)}\n")
        for row in edges.itertuples(index=False):
            speed = parse_speed_kph(row_value(row, "maxspeed"), row_value(row, "highway"))
            f.write(f"{getattr(row, 'u')} {getattr(row, 'v')} {getattr(row, 'length')} {speed}\n")

    print("Writing distance graph...")
    distance_edges_written = 0
    with dist_txt.open("w", encoding="utf-8") as f:
        for row in edges.itertuples(index=False):
            u_osm = int(getattr(row, "u"))
            v_osm = int(getattr(row, "v"))

            if u_osm not in nodes_dict or v_osm not in nodes_dict:
                continue

            u = nodes_dict[u_osm]
            v = nodes_dict[v_osm]
            distance_mm = int(round(1000.0 * float(getattr(row, "length"))))

            f.write(f"{u} {v} {distance_mm}\n")
            distance_edges_written += 1

            if not is_oneway(row_value(row, "oneway")):
                f.write(f"{v} {u} {distance_mm}\n")
                distance_edges_written += 1

    print("Writing time graph...")
    time_edges_written = 0
    with time_txt.open("w", encoding="utf-8") as f:
        for row in edges.itertuples(index=False):
            u_osm = int(getattr(row, "u"))
            v_osm = int(getattr(row, "v"))

            if u_osm not in nodes_dict or v_osm not in nodes_dict:
                continue

            u = nodes_dict[u_osm]
            v = nodes_dict[v_osm]
            speed = parse_speed_kph(row_value(row, "maxspeed"), row_value(row, "highway"))
            time_ms = edge_time_ms(float(getattr(row, "length")), speed)

            f.write(f"{u} {v} {time_ms}\n")
            time_edges_written += 1

            if not is_oneway(row_value(row, "oneway")):
                f.write(f"{v} {u} {time_ms}\n")
                time_edges_written += 1

    print("Writing speed graph...")
    speed_edges_written = 0
    with speed_txt.open("w", encoding="utf-8") as f:
        for row in edges.itertuples(index=False):
            u_osm = int(getattr(row, "u"))
            v_osm = int(getattr(row, "v"))

            if u_osm not in nodes_dict or v_osm not in nodes_dict:
                continue

            u = nodes_dict[u_osm]
            v = nodes_dict[v_osm]
            length_m = getattr(row, "length")
            speed = parse_speed_kph(row_value(row, "maxspeed"), row_value(row, "highway"))

            f.write(f"{u} {v} {length_m} {speed}\n")
            speed_edges_written += 1

            if not is_oneway(row_value(row, "oneway")):
                f.write(f"{v} {u} {length_m} {speed}\n")
                speed_edges_written += 1

    metadata = {
        "station": station,
        "osm_pbf": str(pbf_path),
        "network_type": "driving",
        "raw_nodes": int(len(nodes)),
        "raw_edges": int(len(edges)),
        "compact_node_count": int(len(nodes_dict)),
        "distance_edges_written": int(distance_edges_written),
        "time_edges_written": int(time_edges_written),
        "speed_edges_written": int(speed_edges_written),
        "speed_defaults_kph": _DEFAULT_SPEEDS_KPH,
        "outputs": {
            "nodes_lat_lon": str(nodes_csv),
            "graph_debug": str(graph_debug_txt),
            "graph_distance": str(dist_txt),
            "graph_time": str(time_txt),
            "graph_speed": str(speed_txt),
        },
        "formats": {
            "nodes_lat_lon": "node_id,lat,lon",
            "graph_speed": "u v length_m speed_kph",
            "graph_distance": "u v distance_mm",
            "graph_time": "u v time_ms",
        },
        "environment": {
        "python": sys.version,
        "packages": {
            package: get_package_version(package)
            for package in ["pyrosm", "geopandas", "shapely", "pandas", "numpy", "pyproj"]
        },
},
    }

    with metadata_json.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print("\nDone.")
    print(f"  nodes        : {nodes_csv}")
    print(f"  graph speed  : {speed_txt}")
    print(f"  graph dist   : {dist_txt}")
    print(f"  graph time   : {time_txt}")
    print(f"  metadata     : {metadata_json}")
    print(f"  nodes        : {len(nodes_dict)}")
    print(f"  speed edges  : {speed_edges_written}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert OSM PBF into hub-label-compatible graph files."
    )
    parser.add_argument("--osm-pbf", required=True, help="Path to station OSM PBF file.")
    parser.add_argument("--station", required=True, help="Station prefix, e.g. melton, caulfield.")
    parser.add_argument("--out-dir", default="files/inputs", help="Output directory.")
    args = parser.parse_args()

    process_osm_to_graph_data(
        pbf_path=Path(args.osm_pbf),
        station=args.station,
        output_dir=Path(args.out_dir),
    )


if __name__ == "__main__":
    main()