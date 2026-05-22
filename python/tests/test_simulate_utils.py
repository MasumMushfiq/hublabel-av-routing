import sys, os
import numpy as np
import math

# Ensure the module path finds simulate_first_mile_utils in the parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PARKING_FIELDS = {
    "fallback_private_cars",
    "baseline_parking_spaces",
    "station_commuter_parking_spaces",
    "station_parking_reduction_pct",
    "fleet_storage_equiv_spaces",
    "net_parking_equiv_if_fleet_stored_at_station",
    "net_parking_reduction_pct_if_fleet_stored_at_station",
}

from simulate_first_mile_utils import (
    smooth_penalty,
    build_cost_matrix,
    generate_windows_sec,
    assign_latest_feasible_window,
    assign_individual_windows,
    calculate_baseline,
    calculate_parking_metrics,
    compare,
    Commuter,
    TimeWindowConfig,
    VehicleConfig,
    ExperimentConfig,
)


def test_smooth_penalty_basic():
    # inside band -> 1.0
    assert smooth_penalty(1.0, 0.5, 2.0, alpha=2.0, beta=1.0) == 1.0
    # below lower -> >1
    assert smooth_penalty(0.1, 0.5, 2.0, alpha=2.0, beta=1.0) > 1.0
    # above upper -> >1
    assert smooth_penalty(3.0, 0.5, 2.0, alpha=2.0, beta=1.0) > 1.0
    # zero upper handled
    v = smooth_penalty(1.0, 0.5, 0.0, alpha=2.0, beta=1.0)
    assert isinstance(v, float)


def test_build_cost_matrix_modes():
    dist_m = np.array([[0, 1000, 2000], [1000, 0, 1500], [2000, 1500, 0]], dtype=np.int64)
    # multiplicative: with alpha/beta that produce p>1 for long legs
    cm_mul = build_cost_matrix(dist_m, lower_km=0.5, upper_km=1.0, alpha=2.0, beta=1.0, penalty_mode="multiplicative")
    cm_none = build_cost_matrix(dist_m, lower_km=0.5, upper_km=1.0, alpha=2.0, beta=1.0, penalty_mode="none")
    cm_add = build_cost_matrix(dist_m, lower_km=0.5, upper_km=1.0, alpha=2.0, beta=1.0, penalty_mode="additive", preference_scale_m=100)
    # diagonal zeros
    assert cm_mul[0,0] == 0 and cm_none[1,1] == 0
    # off-diagonal: none equals original distance
    assert cm_none[0,1] == 1000
    # multiplicative should be >= none
    assert cm_mul[0,2] >= cm_none[0,2]
    # additive should be >= none
    assert cm_add[0,2] >= cm_none[0,2]


def test_generate_windows_sec():
    tw = TimeWindowConfig(mode="fixed_slots", interval_minutes=10, start_time_minutes=420, end_time_minutes=440, buffer_before_deadline_sec=0)
    wins = generate_windows_sec(tw)
    assert wins == [420*60, 430*60, 440*60]


def test_assign_latest_feasible_window_and_individual():
    # two commuters, durations such that one fits, one doesn't
    commuters = [
        Commuter(id=1, origin_node=101, destination_node=0, pickup_earliest_min=7*60, drop_off_latest_min=8*60),
        Commuter(id=2, origin_node=102, destination_node=0, pickup_earliest_min=7*60, drop_off_latest_min=7*60+5),
    ]
    # node_to_idx mapping
    node_to_idx = {101:1, 102:2, 0:0}
    # duration matrix in seconds: rows=nodes [station,101,102]
    # commuter 1 travel 10 min, commuter 2 travel 10 min
    dur = np.array([[0, 600, 600],[600,0,300],[600,300,0]])
    windows_sec = [7*3600+30*60, 8*3600]
    assign = assign_latest_feasible_window(commuters, windows_sec, dur, node_to_idx, station_idx=0, buffer_sec=0)
    # commuter 1 earliest arrival 7:00+10min=7:10 -> assigned to latest window index 1 (8:00)
    assert assign[0] == 1
    # commuter 2 drop_off_latest = 7:05, earliest arrival 7:10 -> no feasible window
    assert assign[1] == -1

    # test individual windows
    ind = assign_individual_windows(commuters, dur, node_to_idx, station_idx=0)
    assert ind[0][0] == 7*3600
    assert ind[1] == (-1, -1)


def test_calculate_baseline_and_compare():
    # two feasible commuters
    commuters = [Commuter(id=1, origin_node=101, destination_node=0, pickup_earliest_min=0, drop_off_latest_min=0),
                 Commuter(id=2, origin_node=102, destination_node=0, pickup_earliest_min=0, drop_off_latest_min=0)]
    feasible_idx = [0,1]
    # raw_dist_sub shape (3,3): depot + 2 commuters
    raw = np.array([[0, 1000000, 2000000],[1000000,0,1500000],[2000000,1500000,0]])
    # minimal config
    vc = VehicleConfig(name="car", capacity=4, max_speed_kmph=50, fuel_l_per_100km=8.0, co2_kg_per_liter=2.3, fleet_size=1, lower_km=0, upper_km=10, fixed_cost_km_equiv=0)
    tw = TimeWindowConfig(mode="fixed_slots", interval_minutes=10, start_time_minutes=420, end_time_minutes=480, buffer_before_deadline_sec=0)
    cfg = ExperimentConfig(experiment_name="tst", vehicle_types=[vc], time_window=tw, time_limit_seconds=60, alpha=1.0, beta=1.0, private_car_fuel_l_per_100km=8.0, private_car_co2_kg_per_liter=2.3, private_car_speed_kmph=50)
    baseline = calculate_baseline(commuters, feasible_idx, raw, original_count=2, cfg=cfg)
    assert math.isclose(baseline["total_vmt_km"], 3.0, rel_tol=1e-6)
    assert baseline["feasible_commuters"] == 2

    # compare
    av = {"total_vmt_km": 2.4, "total_fuel_liters": 0.192, "total_co2_kg": 0.4416,
          "service_rate": 100.0, "on_time_rate": 100.0, "late_deliveries": 0,
          "avg_passengers_per_trip":1.0, "vehicles_used":1, "vehicle_trips":2,
          "solo_trips":2, "shared_trips":0, "avg_in_vehicle_time_min":0.0, "max_in_vehicle_time_min":0.0, "avg_detour_ratio":1.0, "max_detour_ratio":1.0,
          "fallback_private_cars":0, "baseline_parking_spaces":2,
          "station_commuter_parking_spaces":0, "station_parking_reduction_pct":100.0,
          "fleet_storage_equiv_spaces":1.0, "net_parking_equiv_if_fleet_stored_at_station":1.0,
          "net_parking_reduction_pct_if_fleet_stored_at_station":50.0}
    comp = compare(av, baseline, "exp", seed=1, cfg=cfg)
    assert "vmt_change_pct" in comp
    assert isinstance(comp["vmt_change_pct"], float)
    assert PARKING_FIELDS.issubset(comp)
    assert comp["fleet_storage_equiv_spaces"] == 1.0


def test_calculate_parking_metrics_validation_example():
    vehicle_types = [
        VehicleConfig(name="Scooters", capacity=1, max_speed_kmph=25, fuel_l_per_100km=0.0, co2_kg_per_liter=0.0, fleet_size=56, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Moped", capacity=2, max_speed_kmph=45, fuel_l_per_100km=0.0, co2_kg_per_liter=0.0, fleet_size=28, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Car", capacity=4, max_speed_kmph=50, fuel_l_per_100km=8.0, co2_kg_per_liter=2.3, fleet_size=14, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Mini Bus", capacity=8, max_speed_kmph=50, fuel_l_per_100km=12.0, co2_kg_per_liter=2.3, fleet_size=7, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
    ]
    tw = TimeWindowConfig(mode="fixed_slots", interval_minutes=10, start_time_minutes=420, end_time_minutes=480, buffer_before_deadline_sec=0)
    cfg = ExperimentConfig(experiment_name="parking", vehicle_types=vehicle_types, time_window=tw, time_limit_seconds=60, alpha=1.0, beta=1.0, private_car_fuel_l_per_100km=8.0, private_car_co2_kg_per_liter=2.3, private_car_speed_kmph=50)
    av = {
        "total_commuters": 1465,
        "unserved_commuters": 0,
        "late_deliveries": 36,
    }

    parking = calculate_parking_metrics(av, cfg)

    assert PARKING_FIELDS.issubset(parking)
    assert parking["fallback_private_cars"] == 36
    assert parking["fleet_storage_equiv_spaces"] == 56.0
    assert parking["station_parking_reduction_pct"] == 97.54
    assert parking["net_parking_equiv_if_fleet_stored_at_station"] == 92.0
    assert parking["net_parking_reduction_pct_if_fleet_stored_at_station"] == 93.72
