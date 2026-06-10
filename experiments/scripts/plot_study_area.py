#!/usr/bin/env python3
"""
Generate study-area map for the SIGSPATIAL paper.

Run from repository root:
    python experiments/scripts/plot_study_area.py

Outputs:
    figures/study_area.pdf
    figures/study_area.png
"""

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from pyrosm import OSM


# ---------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------
PBF_PATH = Path("dataset/OSM_DATA/melton_osm.pbf")
NODES_CSV = Path("files/inputs/melton_nodes_lat_lon.csv")
COMMUTERS_CSV = Path("files/inputs/commuters_residential.csv")

OUT_PDF = Path("figures/study_area.pdf")
OUT_PNG = Path("figures/study_area.png")

STATION_NODE_ID = 19858

# GDA2020 / MGA Zone 55, suitable for Melbourne/Victoria metric plotting
PROJECTED_CRS = "EPSG:7855"


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def require_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")


def main() -> None:
    require_file(PBF_PATH)
    require_file(NODES_CSV)
    require_file(COMMUTERS_CSV)

    print("[load] nodes")
    nodes = pd.read_csv(NODES_CSV)
    required_node_cols = {"node_id", "lat", "lon"}
    missing = required_node_cols - set(nodes.columns)
    if missing:
        raise ValueError(f"{NODES_CSV} missing columns: {sorted(missing)}")

    print("[load] commuters")
    commuters = pd.read_csv(COMMUTERS_CSV)
    required_commuter_cols = {"origin_node", "destination_node"}
    missing = required_commuter_cols - set(commuters.columns)
    if missing:
        raise ValueError(f"{COMMUTERS_CSV} missing columns: {sorted(missing)}")

    # Join commuter origins to node coordinates.
    origins_df = commuters[["origin_node"]].merge(
        nodes,
        left_on="origin_node",
        right_on="node_id",
        how="left",
    )

    if origins_df[["lat", "lon"]].isna().any().any():
        missing_count = origins_df["lat"].isna().sum()
        raise ValueError(
            f"{missing_count} commuter origins could not be matched to {NODES_CSV}"
        )

    station_row = nodes.loc[nodes["node_id"] == STATION_NODE_ID]
    if station_row.empty:
        raise ValueError(f"Station node {STATION_NODE_ID} not found in {NODES_CSV}")

    # GeoDataFrames in WGS84 first.
    origins = gpd.GeoDataFrame(
        origins_df,
        geometry=gpd.points_from_xy(origins_df["lon"], origins_df["lat"]),
        crs="EPSG:4326",
    ).to_crs(PROJECTED_CRS)

    station = gpd.GeoDataFrame(
        {"name": ["Melton Station"], "node_id": [STATION_NODE_ID]},
        geometry=gpd.points_from_xy(station_row["lon"], station_row["lat"]),
        crs="EPSG:4326",
    ).to_crs(PROJECTED_CRS)

    # Bounding box from commuter origins + station.
    all_points = pd.concat(
        [origins.geometry, station.geometry],
        ignore_index=True,
    )
    minx, miny, maxx, maxy = all_points.total_bounds

    # Padding in metres.
    pad = 100
    bbox = (minx - pad, miny - pad, maxx + pad, maxy + pad)



    print("[load] OSM road network from PBF")
    osm = OSM(str(PBF_PATH))
    roads = osm.get_network(network_type="driving")

    if roads is None or roads.empty:
        raise RuntimeError("No driving roads loaded from PBF.")

    roads = roads.to_crs(PROJECTED_CRS)
    roads_clip = roads.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]

    if roads_clip.empty:
        raise RuntimeError("Road network is empty after clipping to study-area bbox.")

    print("[plot] study area")
    fig, ax = plt.subplots(figsize=(4.2, 4.8))

    # Road network
    roads_clip.plot(
        ax=ax,
        linewidth=0.25,
        color="0.72",
        alpha=0.9,
        zorder=1,
    )

    origins.plot(
        ax=ax,
        markersize=2.8,
        color="0.05",
        alpha=0.25,
        label="Inferred commuter origins",
        zorder=2,
    )

    station.plot(
        ax=ax,
        markersize=90,
        marker="*",
        color="white",
        edgecolor="black",
        linewidth=1.0,
        label="Melton Station",
        zorder=3,
    )



    ax.set_xlim(bbox[0], bbox[2])
    ax.set_ylim(bbox[1], bbox[3])
    ax.set_aspect("equal", adjustable="box")
    ax.margins(0)
    ax.set_axis_off()

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)


    legend = ax.legend(
        loc="lower left",
        frameon=True,
        fontsize=7,
        borderpad=0.4,
        handletextpad=0.4,
    )

    legend.get_frame().set_linewidth(0.4)
    legend.get_frame().set_edgecolor("0.4")
    legend.get_frame().set_alpha(0.95)

    plt.tight_layout(pad=0.2)

    OUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PDF, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)

    print(f"[saved] {OUT_PDF}")
    print(f"[saved] {OUT_PNG}")
    print(f"[info] plotted {len(origins)} commuter requests")
    print(f"[info] unique origin nodes: {origins_df['origin_node'].nunique()}")


if __name__ == "__main__":
    main()