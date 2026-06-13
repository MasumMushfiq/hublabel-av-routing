import copy
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from simulate_first_mile_pyvrp import load_config, routing_cost_log_wording
from simulate_first_mile_utils import (
    Commuter,
    assign_latest_feasible_window,
    generate_windows_sec,
)


def minimal_config():
    return {
        "experiment_name": "config_test",
        "fleet": {
            "vehicle_types": [
                {
                    "name": "Car",
                    "capacity": 4,
                    "max_speed_kmph": 80.0,
                    "energy_kwh_per_km": 0.155,
                    "fleet_size": 1,
                }
            ]
        },
        "time_window": {
            "mode": "fixed_slots",
            "interval_minutes": 20,
            "start_time_minutes": 420,
            "end_time_minutes": 570,
        },
        "solver_config": {"time_limit_seconds": 300},
        "baseline_parameters": {
            "private_car_energy_kwh_per_km": 0.155,
            "private_car_speed_kmph": 80.0,
        },
        "energy_model": {
            "electricity_cost_per_kwh": 0.27,
            "grid_co2_kg_per_kwh": 0.78,
        },
    }


def write_config(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    return path


def test_minimal_raw_distance_config_uses_neutral_defaults(tmp_path):
    config = load_config(write_config(tmp_path, minimal_config()))

    assert config.penalty_mode == "none"
    assert config.preference_scale_m == 0
    assert config.time_window.buffer_before_deadline_sec == 0.0
    assert config.vehicle_types[0].lower_km == 0.0
    assert config.vehicle_types[0].upper_km == 0.0
    assert config.vehicle_types[0].fixed_cost_km_equiv == 0.0
    assert config.operating_horizon.start_time_minutes == 420
    assert config.operating_horizon.end_time_minutes == 570


def test_fixed_slots_and_service_horizon_are_separate(tmp_path):
    raw = minimal_config()
    raw["service_horizon"] = {
        "start_time_minutes": 390,
        "end_time_minutes": 570,
    }

    config = load_config(write_config(tmp_path, raw))

    windows = generate_windows_sec(config.time_window)
    assert windows[0] == 7 * 60 * 60
    assert 6 * 60 * 60 + 50 * 60 not in windows

    assignment = assign_latest_feasible_window(
        [Commuter(1, 101, 1, 391, 421)],
        windows,
        np.zeros((2, 2), dtype=np.int64),
        {1: 0, 101: 1},
        0,
        0,
    )
    assert windows[assignment[0]] == 7 * 60 * 60
    assert config.operating_horizon.start_time_minutes == 390
    assert config.operating_horizon.end_time_minutes == 570
    assert (
        config.operating_horizon.end_time_minutes
        - config.operating_horizon.start_time_minutes
    ) == 180


def test_legacy_config_uses_time_window_as_service_horizon(tmp_path):
    config = load_config(write_config(tmp_path, minimal_config()))

    assert config.service_horizon is not None
    assert config.operating_horizon.start_time_minutes == 420
    assert config.operating_horizon.end_time_minutes == 570


def test_active_penalty_requires_distance_preference_fields(tmp_path):
    config = copy.deepcopy(minimal_config())
    config["penalty_parameters"] = {
        "penalty_mode": "multiplicative",
        "alpha": 1.0,
        "beta": 1.0,
    }

    with pytest.raises(ValueError, match="requires distance_band"):
        load_config(write_config(tmp_path, config))


def test_raw_distance_reconciliation_wording_is_not_penalty_wording():
    objective, gap = routing_cost_log_wording("none")

    assert objective == "routing cost; raw distance under current config"
    assert gap == (
        "Gap (B)→(C) reflects extraction, rounding, or "
        "distance-accounting differences."
    )
    assert "penalty effect" not in gap


def test_active_penalty_reconciliation_wording_is_conditional():
    objective, gap = routing_cost_log_wording("multiplicative")

    assert objective == "routing cost; penalty-adjusted"
    assert "penalty adjustment" in gap
