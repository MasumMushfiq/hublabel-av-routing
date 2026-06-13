import argparse
import gzip
import json
import os
import sys
from datetime import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from build_myki_commuters import (
    add_stop_id_column_argument,
    extract_tap_ons,
    load_config_windows,
    parse_stop_ids,
    write_metadata,
)


def test_pickup_buffer_remains_independent_of_demand_window(tmp_path):
    source = tmp_path / "ScanOnTransaction_2018_11.txt.gz"
    row = "|".join([
        "2", "2018-03-15", "2018-03-15 07:01:00", "card-1",
        "", "", "", "", "20025",
    ])
    with gzip.open(source, "wt", encoding="utf-8") as handle:
        handle.write(row + "\n")

    records = extract_tap_ons(
        [source], time(7, 0), time(9, 30), 30.0,
        date_filter="2018-03-15", stop_ids=(20025,), stop_id_column=8,
    )

    assert records == [{
        "tap_min": 421.0,
        "pickup_earliest": "06:31",
        "drop_off_latest": "07:01",
        "window_min": 30.0,
    }]


def test_stop_id_column_defaults_to_dim_stop_location_id():
    parser = argparse.ArgumentParser()
    add_stop_id_column_argument(parser)

    assert parser.parse_args([]).stop_id_column == 8


def test_demand_window_takes_precedence_over_service_horizon(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "demand_window": {
            "start_time_minutes": 420,
            "end_time_minutes": 570,
        },
        "time_window": {
            "start_time_minutes": 420,
            "end_time_minutes": 570,
        },
        "service_horizon": {
            "start_time_minutes": 390,
            "end_time_minutes": 570,
        },
    }))

    assert load_config_windows(str(config_path)) == {
        "demand_start": "07:00",
        "demand_end": "09:30",
        "demand_window_source": "demand_window",
        "service_start": "06:30",
        "service_end": "09:30",
        "deadline_start": "07:00",
        "deadline_end": "09:30",
    }


def test_demand_window_falls_back_to_legacy_time_window(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "time_window": {
            "start_time_minutes": 420,
            "end_time_minutes": 570,
        },
    }))

    windows = load_config_windows(str(config_path))

    assert windows["demand_start"] == "07:00"
    assert windows["demand_end"] == "09:30"
    assert windows["demand_window_source"] == "time_window_fallback"
    assert windows["service_start"] == "07:00"
    assert windows["service_end"] == "09:30"
    assert windows["deadline_start"] == "07:00"
    assert windows["deadline_end"] == "09:30"


def test_metadata_records_explicit_footscray_pipeline_fields(tmp_path):
    metadata_path = tmp_path / "metadata.json"
    write_metadata(
        str(metadata_path),
        output_csv="files/inputs/footscray_commuters_residential.csv",
        station_name="Footscray",
        destination_node=240615,
        myki_root="dataset/MYKI/Samp_9",
        nodes_file="files/inputs/footscray_residential_candidate_nodes_3km.csv",
        coord_nodes_file="files/inputs/footscray_nodes_lat_lon.csv",
        cpp_bin="bin/build_commuters_reachable",
        labels="dataset/FOOTSCRAY/footscray_dist",
        config="config/footscray_base_config.json",
        year=2018,
        week=11,
        date="2018-03-15",
        peak_start="07:00",
        peak_end="09:30",
        peak_window_source="demand_window",
        service_start="06:30",
        service_end="09:30",
        deadline_start="07:00",
        deadline_end="09:30",
        pickup_buffer_min=30.0,
        av_speed_kmh=25.0,
        seed=42,
        origin_sampling="random",
        origin_candidate_source="osm_residential_address_candidate_nodes_3km",
        residential_candidate_metadata=(
            "files/inputs/footscray_residential_candidate_metadata_3km.json"
        ),
        stop_ids=(20025,),
        stop_id_column=8,
        tap_ons_extracted=586,
        reachable_origins_generated=586,
        commuters_written=586,
    )

    metadata = json.loads(metadata_path.read_text())

    assert metadata["station_name"] == "Footscray"
    assert metadata["stop_ids"] == [20025]
    assert metadata["stop_id_column"] == 8
    assert metadata["stop_id_column_description"] == "DimStopLocation.StopLocationID"
    assert metadata["date"] == "2018-03-15"
    assert metadata["year"] == 2018
    assert metadata["week"] == 11
    assert metadata["demand_window"] == {
        "start": "07:00",
        "end": "09:30",
        "source": "demand_window",
    }
    assert metadata["service_horizon"] == {
        "start": "06:30",
        "end": "09:30",
    }
    assert metadata["time_window"] == {
        "start": "07:00",
        "end": "09:30",
        "meaning": "fixed station-arrival deadline slots",
    }
    assert metadata["pickup_buffer_minutes"] == 30.0
    assert metadata["tap_ons_extracted"] == 586
    assert metadata["reachable_origins"] == 586
    assert metadata["feasible_commuters"] == 586
    assert metadata["output_commuters"] == 586
    assert metadata["origin_candidate_source"] == (
        "osm_residential_address_candidate_nodes_3km"
    )
    assert metadata["residential_candidate_metadata"] == (
        "files/inputs/footscray_residential_candidate_metadata_3km.json"
    )


def test_parse_stop_ids_accepts_comma_separated_integers_with_whitespace():
    assert parse_stop_ids("18, 19980,21131 , 21132") == (
        18,
        19980,
        21131,
        21132,
    )


def test_parse_stop_ids_accepts_single_integer():
    assert parse_stop_ids("18") == (18,)


def test_parse_stop_ids_rejects_empty_values():
    for value in ("", "18,", "18,,19980", "18, ,19980"):
        try:
            parse_stop_ids(value)
        except argparse.ArgumentTypeError as exc:
            assert "empty value" in str(exc)
        else:
            raise AssertionError(f"expected argparse error for {value!r}")


def test_parse_stop_ids_rejects_non_integer_values():
    try:
        parse_stop_ids("18,abc,19980")
    except argparse.ArgumentTypeError as exc:
        assert "not an integer" in str(exc)
    else:
        raise AssertionError("expected argparse error for non-integer stop ID")
