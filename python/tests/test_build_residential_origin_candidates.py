import json
import os
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from build_residential_origin_candidates import (
    CandidatePoint,
    map_candidates_to_road_nodes,
    write_metadata,
)


def candidate(candidate_id, lat):
    return CandidatePoint(
        candidate_id=candidate_id,
        source_type="node",
        osm_id=int(candidate_id),
        lat=lat,
        lon=0.0,
        candidate_kind="residential_building",
        building="house",
        has_address=False,
        addr_housenumber="",
        addr_street="",
        addr_suburb="",
        addr_postcode="",
    )


def test_optional_outer_catchment_filters_by_direct_distance():
    road_nodes = pd.DataFrame(
        [
            {"node_id": 1, "lat": 0.0, "lon": 0.0},
            {"node_id": 2, "lat": 0.01, "lon": 0.0},
            {"node_id": 3, "lat": 0.03, "lon": 0.0},
        ]
    )

    mapping, nodes, stats = map_candidates_to_road_nodes(
        [candidate("1", 0.005), candidate("2", 0.01), candidate("3", 0.03)],
        road_nodes,
        station_node=1,
        walking_threshold_m=800.0,
        max_station_distance_m=2000.0,
    )

    assert mapping["filter_reason"].tolist() == [
        "within_walking_threshold",
        "kept",
        "beyond_max_station_distance",
    ]
    assert nodes["node_id"].tolist() == [2]
    assert stats["removed_by_walking_threshold"] == 1
    assert stats["removed_by_outer_catchment"] == 1

    mapping_without_outer_filter, _, _ = map_candidates_to_road_nodes(
        [candidate("3", 0.03)],
        road_nodes,
        station_node=1,
        walking_threshold_m=800.0,
    )
    assert mapping_without_outer_filter.iloc[0]["filter_reason"] == "kept"


def test_metadata_candidate_source_uses_supplied_osm_pbf(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    osm_pbf = Path("dataset/OSM_DATA/footscray_osm.pbf")
    mapping_stats = {
        "walking_threshold_m": 800.0,
        "max_station_distance_m": 3000.0,
        "raw_candidates": 10,
        "kept_candidate_rows_after_filter": 8,
        "unique_candidate_road_nodes_after_filter": 7,
        "removed_by_walking_threshold": 1,
        "removed_by_outer_catchment": 1,
    }

    write_metadata(
        metadata_path,
        osm_pbf=osm_pbf,
        road_nodes=Path("files/inputs/footscray_nodes_lat_lon.csv"),
        out_nodes=tmp_path / "nodes.csv",
        out_points=tmp_path / "points.csv",
        out_mapping=tmp_path / "mapping.csv",
        handler_stats=Counter(),
        mapping_stats=mapping_stats,
        include_debug_columns_in_nodes=False,
    )

    metadata = json.loads(metadata_path.read_text())
    assert metadata["candidate_source"] == (
        "Residential/address candidates extracted from supplied OSM PBF: "
        "dataset/OSM_DATA/footscray_osm.pbf"
    )
    assert "Melton" not in metadata["candidate_source"]
