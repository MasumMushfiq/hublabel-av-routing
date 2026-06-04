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
    calculate_cost_metrics,
    compare,
    Commuter,
    TripStop,
    TimeWindowConfig,
    VehicleConfig,
    ExperimentConfig,
    CostModel,
    COST_METRIC_FIELDS,
    iteratively_prune_late_commuters,
    recompute_trip_timing,
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


def make_trip_stop(
        commuter_id,
        matrix_idx,
        deadline,
        original_pickup=100,
        earliest=0,
        pickup_latest=10_000):
    return TripStop(
        commuter_id=commuter_id,
        matrix_idx=matrix_idx,
        pickup_earliest_sec=earliest,
        pickup_latest_sec=pickup_latest,
        station_deadline_sec=deadline,
        original_pickup_time_sec=original_pickup,
    )


def test_prune_no_late_commuters():
    dur = np.array([[0, 10, 20], [10, 0, 5], [20, 5, 0]])
    stops = [
        make_trip_stop(1, 1, deadline=130),
        make_trip_stop(2, 2, deadline=130),
    ]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.kept_stops] == [1, 2]
    assert result.removed_late_stops == []
    assert result.station_arrival_sec == 125
    assert result.iterations == 0


def test_prune_uses_station_deadline_not_transformed_pickup_latest():
    dur = np.array([[0, 10], [10, 0]])
    stops = [
        make_trip_stop(
            1,
            1,
            deadline=120,
            original_pickup=100,
            pickup_latest=60,
        ),
    ]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.kept_stops] == [1]
    assert result.removed_late_stops == []
    assert result.station_arrival_sec == 110


def test_prune_one_late_commuter_keeps_other_after_recompute():
    dur = np.array([[0, 10, 50], [10, 0, 50], [50, 50, 0]])
    stops = [
        make_trip_stop(1, 1, deadline=220),
        make_trip_stop(2, 2, deadline=180),
    ]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.removed_late_stops] == [2]
    assert [s.commuter_id for s in result.kept_stops] == [1]
    assert result.station_arrival_sec == 110


def test_prune_iterative_rescue_keeps_newly_on_time_commuter():
    dur = np.array([[0, 10, 10], [10, 0, 80], [10, 80, 0]])
    stops = [
        make_trip_stop(1, 1, deadline=150, original_pickup=100),
        make_trip_stop(2, 2, deadline=185, original_pickup=100),
    ]
    initial = recompute_trip_timing(stops, dur)
    assert initial.station_arrival_sec == 190

    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.removed_late_stops] == [1]
    assert [s.commuter_id for s in result.kept_stops] == [2]
    assert result.station_arrival_sec == 110
    assert result.iterations == 1


def test_prune_single_commuter_late_trip():
    dur = np.array([[0, 10], [10, 0]])
    stops = [make_trip_stop(1, 1, deadline=105)]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.removed_late_stops] == [1]
    assert result.kept_stops == []
    assert result.pickup_times_sec == {}
    assert result.station_arrival_sec == 0


def test_prune_identical_origin_commuters():
    dur = np.array([[0, 10], [10, 0]])
    stops = [
        make_trip_stop(1, 1, deadline=120, earliest=100),
        make_trip_stop(2, 1, deadline=120, earliest=105),
    ]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.kept_stops] == [1, 2]
    assert result.pickup_times_sec == {1: 100, 2: 105}
    assert result.station_arrival_sec == 115


def test_prune_pickup_earliest_waiting_after_pruning():
    dur = np.array([[0, 10, 10], [10, 0, 5], [10, 5, 0]])
    stops = [
        make_trip_stop(1, 1, deadline=150, original_pickup=100),
        make_trip_stop(2, 2, deadline=220, original_pickup=90, earliest=200),
    ]
    result = iteratively_prune_late_commuters(stops, dur)
    assert [s.commuter_id for s in result.removed_late_stops] == [1]
    assert [s.commuter_id for s in result.kept_stops] == [2]
    assert result.pickup_times_sec[2] == 200
    assert result.station_arrival_sec == 210


def test_calculate_baseline_and_compare():
    # two feasible commuters
    commuters = [Commuter(id=1, origin_node=101, destination_node=0, pickup_earliest_min=0, drop_off_latest_min=0),
                 Commuter(id=2, origin_node=102, destination_node=0, pickup_earliest_min=0, drop_off_latest_min=0)]
    feasible_idx = [0,1]
    # raw_dist_sub shape (3,3): depot + 2 commuters
    raw = np.array([[0, 1000000, 2000000],[1000000,0,1500000],[2000000,1500000,0]])
    # minimal config
    vc = VehicleConfig(name="car", capacity=4, max_speed_kmph=50, energy_kwh_per_km=0.155, fleet_size=1, lower_km=0, upper_km=10, fixed_cost_km_equiv=0)
    tw = TimeWindowConfig(mode="fixed_slots", interval_minutes=10, start_time_minutes=420, end_time_minutes=480, buffer_before_deadline_sec=0)
    cfg = ExperimentConfig(experiment_name="tst", vehicle_types=[vc], time_window=tw, time_limit_seconds=60, alpha=1.0, beta=1.0, private_car_energy_kwh_per_km=0.155, electricity_cost_per_kwh=0.27, grid_co2_kg_per_kwh=0.78, private_car_speed_kmph=50)
    baseline = calculate_baseline(commuters, feasible_idx, raw, original_count=2, cfg=cfg)
    assert math.isclose(baseline["total_vmt_km"], 3.0, rel_tol=1e-6)
    assert math.isclose(baseline["total_energy_kwh"], 0.465, rel_tol=1e-6)
    assert math.isclose(baseline["total_co2_kg"], 0.3627, rel_tol=1e-6)
    assert math.isclose(baseline["baseline_energy_cost"], 0.1255, rel_tol=1e-6)
    assert baseline["feasible_commuters"] == 2

    # compare
    av = {"total_vmt_km": 2.4, "total_energy_kwh": 0.372, "total_co2_kg": 0.29016,
          "system_total_vmt_km": 3.0, "system_total_energy_kwh": 0.465, "system_total_co2_kg": 0.3627,
          "fallback_private_car_vmt_km": 0.6, "fallback_private_car_energy_kwh": 0.093, "fallback_private_car_co2_kg": 0.07254,
          "fallback_private_car_avg_trip_km": 0.6, "fallback_private_car_share_pct": 50.0,
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
    assert comp["raw_av_total_vmt_km"] == av["total_vmt_km"]
    assert comp["adjusted_av_total_vmt_km"] == av["total_vmt_km"]
    assert comp["system_total_vmt_km"] == av["system_total_vmt_km"]
    assert comp["raw_av_total_energy_kwh"] == av["total_energy_kwh"]
    assert comp["adjusted_av_total_energy_kwh"] == av["total_energy_kwh"]
    assert comp["system_total_energy_kwh"] == av["system_total_energy_kwh"]
    assert comp["raw_av_total_co2_kg"] == av["total_co2_kg"]
    assert comp["adjusted_av_total_co2_kg"] == av["total_co2_kg"]
    assert comp["system_total_co2_kg"] == av["system_total_co2_kg"]
    assert comp["fallback_private_car_vmt_km"] == av["fallback_private_car_vmt_km"]
    assert comp["vmt_change_pct"] == -20.0
    assert comp["system_vmt_change_pct"] == 0.0
    assert comp["energy_change_pct"] == -20.0
    assert comp["system_energy_change_pct"] == 0.0
    assert comp["system_co2_change_pct"] == 0.0
    assert PARKING_FIELDS.issubset(comp)
    assert comp["fleet_storage_equiv_spaces"] == 1.0


def test_calculate_parking_metrics_validation_example():
    vehicle_types = [
        VehicleConfig(name="Scooters", capacity=1, max_speed_kmph=25, energy_kwh_per_km=0.016, fleet_size=56, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Moped", capacity=2, max_speed_kmph=45, energy_kwh_per_km=0.058, fleet_size=28, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Car", capacity=4, max_speed_kmph=50, energy_kwh_per_km=0.155, fleet_size=14, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
        VehicleConfig(name="Mini Bus", capacity=8, max_speed_kmph=50, energy_kwh_per_km=0.330, fleet_size=7, lower_km=0, upper_km=10, fixed_cost_km_equiv=0),
    ]
    tw = TimeWindowConfig(mode="fixed_slots", interval_minutes=10, start_time_minutes=420, end_time_minutes=480, buffer_before_deadline_sec=0)
    cfg = ExperimentConfig(experiment_name="parking", vehicle_types=vehicle_types, time_window=tw, time_limit_seconds=60, alpha=1.0, beta=1.0, private_car_energy_kwh_per_km=0.155, electricity_cost_per_kwh=0.27, grid_co2_kg_per_kwh=0.78, private_car_speed_kmph=50)
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


# ══════════════════════════════════════════════════════════════════════════════
# COST METRICS TESTS
# ══════════════════════════════════════════════════════════════════════════════

def _make_cost_cfg(fixed_per_vehicle=None, maint_per_km=None):
    """Helper: build a minimal ExperimentConfig with cost_model."""
    vc_scooter = VehicleConfig(
        name="scooter", capacity=1, max_speed_kmph=25,
        energy_kwh_per_km=0.016,
        fleet_size=10, lower_km=0, upper_km=2, fixed_cost_km_equiv=0,
    )
    vc_car = VehicleConfig(
        name="car", capacity=4, max_speed_kmph=80,
        energy_kwh_per_km=0.155,
        fleet_size=5, lower_km=4, upper_km=12, fixed_cost_km_equiv=0,
    )
    tw = TimeWindowConfig(
        mode="fixed_slots", interval_minutes=20,
        start_time_minutes=420, end_time_minutes=570,
        buffer_before_deadline_sec=0,
    )
    cm = CostModel(
        fixed_cost_per_vehicle=fixed_per_vehicle or {},
        maintenance_cost_per_km=maint_per_km or {},
    )
    return ExperimentConfig(
        experiment_name="cost_test",
        vehicle_types=[vc_scooter, vc_car],
        time_window=tw,
        time_limit_seconds=60,
        alpha=1.0, beta=1.0,
        private_car_energy_kwh_per_km=0.155,
        electricity_cost_per_kwh=0.27,
        grid_co2_kg_per_kwh=0.78,
        private_car_speed_kmph=80.0,
        cost_model=cm,
    )


def _make_av_dict(served=80, total=100, vmt_km=200.0,
                  adj_energy=24.05, pax_km=300.0,
                  per_type=None):
    """Helper: minimal av metrics dict for cost tests."""
    per_vehicle_type = per_type or {
        "scooter": {"vmt_km": 50.0},
        "car":     {"vmt_km": 150.0},
    }
    return {
        "total_commuters":           total,
        "served_commuters":          served,
        "total_vmt_km":              vmt_km,
        "adjusted_av_total_vmt_km":  vmt_km,
        "adjusted_av_total_energy_kwh": adj_energy,
        "total_energy_kwh":          adj_energy,
        "passenger_km":              pax_km,
        "per_vehicle_type":          per_vehicle_type,
    }


def test_cost_metrics_all_fields_present():
    """calculate_cost_metrics must return all COST_METRIC_FIELDS."""
    cfg = _make_cost_cfg()
    av  = _make_av_dict()
    result = calculate_cost_metrics(av, cfg)
    assert COST_METRIC_FIELDS.issubset(result), (
        f"Missing fields: {COST_METRIC_FIELDS - result.keys()}"
    )


def test_cost_metrics_energy_cost_when_no_cost_model():
    """Energy cost is still computed from electricity config without fixed/maintenance rates."""
    tw = TimeWindowConfig("fixed_slots", 20, 420, 570, 0)
    vc = VehicleConfig("car", 4, 80, 0.155, 5, 0, 12, 0)
    cfg = ExperimentConfig(
        "no_cost", [vc], tw, 60, 1.0, 1.0, 0.155, 0.27, 0.78, 80.0,
        cost_model=None,
    )
    av = _make_av_dict(adj_energy=15.5, per_type={"car": {"vmt_km": 100.0}})
    result = calculate_cost_metrics(av, cfg)
    assert result["av_fleet_fixed_cost"]        == 0.0
    assert result["av_distance_operating_cost"] == 0.0
    assert result["av_energy_cost"]             == 4.185
    assert result["av_total_operating_cost"]    == 4.185


def test_cost_metrics_zero_when_cost_model_has_no_rates():
    """Existing configs without fixed/maintenance rates still include energy cost."""
    cfg = _make_cost_cfg()
    av = _make_av_dict()
    result = calculate_cost_metrics(av, cfg)
    assert result["av_fleet_fixed_cost"] == 0.0
    assert result["av_distance_operating_cost"] == 0.0
    assert result["av_energy_cost"] == 6.4935
    assert result["av_total_operating_cost"] == 6.4935
    assert result["av_cost_by_vehicle_type"]["scooter"]["total_operating_cost"] == 0.216
    assert result["av_cost_by_vehicle_type"]["car"]["total_operating_cost"] == 6.2775


def test_cost_metrics_fixed_cost_uses_fleet_size():
    """Fixed cost = fleet_size × rate, independent of vehicles actually used."""
    cfg = _make_cost_cfg(
        fixed_per_vehicle={"scooter": 10.0, "car": 50.0},
    )
    av = _make_av_dict()
    result = calculate_cost_metrics(av, cfg)
    # scooter: 10 × 10 = 100, car: 5 × 50 = 250
    assert result["av_fleet_fixed_cost"] == 350.0
    assert result["av_cost_by_vehicle_type"]["scooter"]["fixed_cost"] == 100.0
    assert result["av_cost_by_vehicle_type"]["car"]["fixed_cost"]     == 250.0


def test_cost_metrics_maintenance_uses_adjusted_vmt():
    """Distance operating cost uses per-type VMT from per_vehicle_type dict."""
    cfg = _make_cost_cfg(
        maint_per_km={"scooter": 0.10, "car": 0.20},
    )
    av = _make_av_dict(per_type={"scooter": {"vmt_km": 50.0}, "car": {"vmt_km": 150.0}})
    result = calculate_cost_metrics(av, cfg)
    # scooter: 50 × 0.10 = 5, car: 150 × 0.20 = 30  → total 35
    assert result["av_distance_operating_cost"] == 35.0
    assert result["av_cost_by_vehicle_type"]["scooter"]["distance_operating_cost"] == 5.0
    assert result["av_cost_by_vehicle_type"]["car"]["distance_operating_cost"]     == 30.0


def test_cost_metrics_energy_by_vehicle_type():
    """Per-type energy and cost use per-type VMT and kWh/km rates."""
    cfg = _make_cost_cfg()
    av  = _make_av_dict()
    result = calculate_cost_metrics(av, cfg)
    assert result["av_cost_by_vehicle_type"]["scooter"]["energy_kwh"] == 0.8
    assert result["av_cost_by_vehicle_type"]["car"]["energy_kwh"] == 23.25
    assert result["av_cost_by_vehicle_type"]["scooter"]["energy_cost"] == 0.216
    assert result["av_cost_by_vehicle_type"]["car"]["energy_cost"] == 6.2775
    assert result["av_energy_cost"] == 6.4935


def test_cost_metrics_energy_total_sums_per_type_energy_cost():
    """Top-level energy cost is the sum of per-type energy costs."""
    cfg = _make_cost_cfg()
    av = _make_av_dict()
    result = calculate_cost_metrics(av, cfg)
    per_type_energy_cost = sum(
        v["energy_cost"]
        for v in result["av_cost_by_vehicle_type"].values()
    )
    assert result["av_energy_cost"] == 6.4935
    assert result["av_energy_cost"] == per_type_energy_cost


def test_cost_metrics_excludes_fallback_energy_cost():
    """Fallback private-car energy must not appear in AV fleet operating cost."""
    cfg = _make_cost_cfg()
    av = _make_av_dict(
        adj_energy=24.05,
        per_type={"scooter": {"vmt_km": 50.0}, "car": {"vmt_km": 150.0}},
    )
    av["fallback_private_car_energy_kwh"] = 50.0
    av["fallback_private_car_energy_cost"] = 13.5

    result = calculate_cost_metrics(av, cfg)

    assert result["av_energy_cost"] == 6.4935
    assert result["av_total_operating_cost"] == 6.4935
    assert "fallback_private_car_energy_cost" not in result


def test_cost_metrics_total_and_normalised():
    """Total and per-unit rates are consistent."""
    cfg = _make_cost_cfg(
        fixed_per_vehicle={"scooter": 10.0, "car": 50.0},
        maint_per_km={"scooter": 0.10, "car": 0.20},
    )
    av = _make_av_dict(
        served=80, total=100, vmt_km=200.0, adj_energy=24.05, pax_km=300.0,
        per_type={"scooter": {"vmt_km": 50.0}, "car": {"vmt_km": 150.0}},
    )
    result = calculate_cost_metrics(av, cfg)
    # fixed=350, distance=35, energy=6.4935 -> total=391.4935
    assert result["av_total_operating_cost"] == 391.4935
    assert result["av_cost_by_vehicle_type"]["scooter"]["total_operating_cost"] == 105.216
    assert result["av_cost_by_vehicle_type"]["car"]["total_operating_cost"] == 286.2775
    assert math.isclose(result["av_cost_per_commuter_total"],  391.4935 / 100, rel_tol=1e-6)
    assert math.isclose(result["av_cost_per_served_commuter"], 391.4935 / 80,  rel_tol=1e-6)
    assert math.isclose(result["av_cost_per_passenger_km"],    391.4935 / 300, rel_tol=1e-6)
    assert math.isclose(result["av_cost_per_vehicle_km"],      391.4935 / 200, rel_tol=1e-6)


def test_cost_metrics_zero_denominators_do_not_raise():
    """Safe division: zero passengers/vmt must return 0.0, not divide-by-zero."""
    cfg = _make_cost_cfg(fixed_per_vehicle={"scooter": 10.0, "car": 50.0})
    av  = _make_av_dict(served=0, total=0, vmt_km=0.0, adj_energy=0.0, pax_km=0.0,
                        per_type={"scooter": {"vmt_km": 0.0}, "car": {"vmt_km": 0.0}})
    result = calculate_cost_metrics(av, cfg)
    assert result["av_cost_per_commuter_total"]  == 0.0
    assert result["av_cost_per_served_commuter"] == 0.0
    assert result["av_cost_per_passenger_km"]    == 0.0
    assert result["av_cost_per_vehicle_km"]      == 0.0


def test_cost_metrics_missing_vehicle_type_in_rates():
    """Vehicle types absent from cost dicts should default to rate=0."""
    cfg = _make_cost_cfg(
        fixed_per_vehicle={"car": 50.0},   # scooter missing
        maint_per_km={"scooter": 0.10},    # car missing
    )
    av = _make_av_dict(per_type={"scooter": {"vmt_km": 40.0}, "car": {"vmt_km": 100.0}})
    result = calculate_cost_metrics(av, cfg)
    # scooter fixed: 0 (missing → 0), car fixed: 5 × 50 = 250
    # scooter maint: 40 × 0.10 = 4, car maint: 0 (missing → 0)
    assert result["av_cost_by_vehicle_type"]["scooter"]["fixed_cost"]       == 0.0
    assert result["av_cost_by_vehicle_type"]["car"]["fixed_cost"]           == 250.0
    assert result["av_cost_by_vehicle_type"]["scooter"]["distance_operating_cost"] == 4.0
    assert result["av_cost_by_vehicle_type"]["car"]["distance_operating_cost"]     == 0.0


def test_cost_metrics_passed_through_compare():
    """compare() must forward all COST_METRIC_FIELDS into the output dict."""
    cfg = _make_cost_cfg(fixed_per_vehicle={"scooter": 5.0, "car": 20.0})
    av  = _make_av_dict()
    cost = calculate_cost_metrics(av, cfg)
    av.update(cost)
    # Minimal extras needed by compare()
    av.update({
        "service_rate": 80.0, "on_time_rate": 100.0, "late_deliveries": 0,
        "avg_passengers_per_trip": 2.0, "vehicles_used": 5, "vehicle_trips": 40,
        "solo_trips": 10, "shared_trips": 30,
        "avg_in_vehicle_time_min": 8.0, "max_in_vehicle_time_min": 15.0,
        "avg_detour_ratio": 1.2, "max_detour_ratio": 2.0,
        "total_co2_kg": 18.759,
        "system_total_vmt_km": 200.0, "system_total_energy_kwh": 24.05,
        "system_total_co2_kg": 18.759,
        "fallback_private_car_vmt_km": 0.0, "fallback_private_car_energy_kwh": 0.0,
        "fallback_private_car_co2_kg": 0.0, "fallback_private_car_avg_trip_km": 0.0,
        "fallback_private_car_share_pct": 0.0,
        "fallback_private_cars": 0, "baseline_parking_spaces": 100,
        "station_commuter_parking_spaces": 0, "station_parking_reduction_pct": 100.0,
        "fleet_storage_equiv_spaces": 8.0,
        "net_parking_equiv_if_fleet_stored_at_station": 8.0,
        "net_parking_reduction_pct_if_fleet_stored_at_station": 92.0,
    })
    baseline = {
        "total_vmt_km": 250.0, "total_energy_kwh": 38.75, "total_co2_kg": 30.225,
        "avg_trip_km": 2.5, "feasible_commuters": 100, "private_car_speed_kmph": 80.0,
    }
    comp = compare(av, baseline, "cost_test", seed=0, cfg=cfg)
    for field in COST_METRIC_FIELDS:
        assert field in comp, f"Field '{field}' missing from compare() output"
    assert comp["av_total_operating_cost"] == cost["av_total_operating_cost"]
