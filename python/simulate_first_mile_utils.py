"""
simulate_first_mile_utils.py
Utility functions extracted from simulate_first_mile_pyvrp.py for unit testing.
"""
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import numpy as np

PARKING_EQUIV_BY_VEHICLE_TYPE = {
    "scooter": 0.25,
    "moped": 0.50,
    "car": 1.00,
    "minibus": 2.00,
}


@dataclass
class Commuter:
    id: int
    origin_node: int
    destination_node: int
    pickup_earliest_min: float
    drop_off_latest_min: float

@dataclass
class VehicleConfig:
    name: str
    capacity: int
    max_speed_kmph: float
    fuel_l_per_100km: float
    co2_kg_per_liter: float
    fleet_size: int
    lower_km: float
    upper_km: float
    fixed_cost_km_equiv: float

@dataclass
class TimeWindowConfig:
    mode: str
    interval_minutes: int
    start_time_minutes: int
    end_time_minutes: int
    buffer_before_deadline_sec: float

@dataclass
class ExperimentConfig:
    experiment_name: str
    vehicle_types: List[VehicleConfig]
    time_window: TimeWindowConfig
    time_limit_seconds: int
    alpha: float
    beta: float
    private_car_fuel_l_per_100km: float
    private_car_co2_kg_per_liter: float
    private_car_speed_kmph: float
    penalty_mode: str = "multiplicative"
    preference_scale_m: int = 500


@dataclass
class TripStop:
    commuter_id: int
    matrix_idx: int
    pickup_earliest_sec: int
    pickup_latest_sec: int
    station_deadline_sec: int
    original_pickup_time_sec: int


@dataclass
class TripTimingResult:
    kept_stops: List[TripStop]
    pickup_times_sec: Dict[int, int]
    station_arrival_sec: int
    total_duration_sec: int


@dataclass
class PrunedTripResult:
    kept_stops: List[TripStop]
    removed_late_stops: List[TripStop]
    pickup_times_sec: Dict[int, int]
    station_arrival_sec: int
    iterations: int


def recompute_trip_timing(
        stops: List[TripStop],
        duration_matrix_sec,
        depot_idx: int = 0) -> TripTimingResult:
    if not stops:
        return TripTimingResult([], {}, 0, 0)

    first = stops[0]
    trip_start_time = (
        first.original_pickup_time_sec
        - int(duration_matrix_sec[depot_idx, first.matrix_idx])
    )
    current_time = trip_start_time
    current_location = depot_idx
    pickup_times_sec = {}

    for stop in stops:
        arrival_at_origin = (
            current_time
            + int(duration_matrix_sec[current_location, stop.matrix_idx])
        )
        pickup_time = max(arrival_at_origin, stop.pickup_earliest_sec)
        pickup_times_sec[stop.commuter_id] = pickup_time
        current_time = pickup_time
        current_location = stop.matrix_idx

    station_arrival_sec = (
        current_time
        + int(duration_matrix_sec[current_location, depot_idx])
    )
    return TripTimingResult(
        kept_stops=list(stops),
        pickup_times_sec=pickup_times_sec,
        station_arrival_sec=station_arrival_sec,
        total_duration_sec=station_arrival_sec - trip_start_time,
    )


def iteratively_prune_late_commuters(
        stops: List[TripStop],
        duration_matrix_sec,
        depot_idx: int = 0) -> PrunedTripResult:
    """Remove late stops one at a time, recomputing timing after each prune.

    The tightest-deadline late stop is removed first. This is intentional to
    avoid over-pruning: removing one stop may make other initially late stops
    feasible after the route timing is replayed.
    """
    remaining = list(stops)
    removed = []
    timing = recompute_trip_timing(remaining, duration_matrix_sec, depot_idx)
    iterations = 0
    max_iterations = len(remaining)

    while remaining and iterations < max_iterations:
        late_stops = [
            stop for stop in remaining
            if timing.station_arrival_sec > stop.station_deadline_sec
        ]
        if not late_stops:
            break

        tightest_late_stop = min(
            late_stops,
            key=lambda stop: (stop.station_deadline_sec, stop.commuter_id),
        )
        removed.append(tightest_late_stop)
        remaining = [
            stop for stop in remaining
            if stop.commuter_id != tightest_late_stop.commuter_id
        ]
        iterations += 1
        timing = recompute_trip_timing(remaining, duration_matrix_sec, depot_idx)

    return PrunedTripResult(
        kept_stops=timing.kept_stops,
        removed_late_stops=removed,
        pickup_times_sec=timing.pickup_times_sec,
        station_arrival_sec=timing.station_arrival_sec,
        iterations=iterations,
    )


def parking_equiv_for_vehicle_type(name: str) -> float:
    normalized = "".join(ch for ch in name.lower() if ch.isalnum())
    if "minibus" in normalized or "minivan" in normalized or "shuttle" in normalized:
        return PARKING_EQUIV_BY_VEHICLE_TYPE["minibus"]
    if "scooter" in normalized:
        return PARKING_EQUIV_BY_VEHICLE_TYPE["scooter"]
    if "moped" in normalized:
        return PARKING_EQUIV_BY_VEHICLE_TYPE["moped"]
    if "car" in normalized:
        return PARKING_EQUIV_BY_VEHICLE_TYPE["car"]
    return PARKING_EQUIV_BY_VEHICLE_TYPE["car"]


def calculate_parking_metrics(av: dict, cfg: ExperimentConfig) -> dict:
    baseline_parking_spaces = av.get("total_commuters", 0)
    fallback_private_cars = av.get("unserved_commuters", 0) + av.get("late_deliveries", 0)
    station_commuter_parking_spaces = fallback_private_cars
    fleet_storage_equiv_spaces = sum(
        vc.fleet_size * parking_equiv_for_vehicle_type(vc.name)
        for vc in cfg.vehicle_types
    )
    net_parking_equiv = station_commuter_parking_spaces + fleet_storage_equiv_spaces

    if baseline_parking_spaces:
        station_reduction_pct = 100.0 * (
            1.0 - station_commuter_parking_spaces / baseline_parking_spaces
        )
        net_reduction_pct = 100.0 * (
            1.0 - net_parking_equiv / baseline_parking_spaces
        )
    else:
        station_reduction_pct = 0.0
        net_reduction_pct = 0.0

    return {
        "fallback_private_cars": fallback_private_cars,
        "baseline_parking_spaces": baseline_parking_spaces,
        "station_commuter_parking_spaces": station_commuter_parking_spaces,
        "station_parking_reduction_pct": round(station_reduction_pct, 2),
        "fleet_storage_equiv_spaces": round(fleet_storage_equiv_spaces, 4),
        "net_parking_equiv_if_fleet_stored_at_station": round(net_parking_equiv, 4),
        "net_parking_reduction_pct_if_fleet_stored_at_station": round(net_reduction_pct, 2),
    }


def smooth_penalty(d_km: float, lower_km: float, upper_km: float,
                   alpha: float, beta: float) -> float:
    if upper_km <= 0:
        upper_km = 1e-6
    if d_km < lower_km and lower_km > 0:
        ratio = lower_km / max(d_km, 1e-6)
        return 1.0 + beta * ((ratio - 1.0) ** alpha)
    elif d_km > upper_km:
        ratio = d_km / upper_km
        return 1.0 + beta * ((ratio - 1.0) ** alpha)
    return 1.0


def build_cost_matrix(dist_m: np.ndarray,
                      lower_km: float, upper_km: float,
                      alpha: float, beta: float,
                      penalty_mode: str = "multiplicative",
                      preference_scale_m: int = 500) -> np.ndarray:
    M = dist_m.shape[0]
    cost = np.zeros((M, M), dtype=np.int64)
    for i in range(M):
        for j in range(M):
            if i == j:
                continue
            d_m_val = int(dist_m[i, j])
            d_km    = d_m_val / 1000.0
            if penalty_mode == "multiplicative":
                p = smooth_penalty(d_km, lower_km, upper_km, alpha, beta)
                cost[i, j] = int(d_m_val * p)
            elif penalty_mode == "additive":
                p = smooth_penalty(d_km, lower_km, upper_km, alpha, beta)
                additive_pref = int((p - 1.0) * preference_scale_m)
                cost[i, j] = d_m_val + additive_pref
            else:  # "none"
                cost[i, j] = d_m_val
    return cost


def generate_windows_sec(tw: TimeWindowConfig) -> List[int]:
    windows = []
    t = tw.start_time_minutes
    while t <= tw.end_time_minutes:
        windows.append(t * 60)
        t += tw.interval_minutes
    return windows


def assign_latest_feasible_window(
        commuters: List[Commuter],
        windows_sec: List[int],
        dur_fastest: np.ndarray,
        node_to_idx: Dict[int, int],
        station_idx: int,
        buffer_sec: float) -> List[int]:
    assignment = [-1] * len(commuters)
    for i, c in enumerate(commuters):
        c_idx = node_to_idx.get(c.origin_node, -1)
        if c_idx < 0:
            continue
        tt_sec = int(dur_fastest[c_idx, station_idx])
        pickup_earliest_sec = c.pickup_earliest_min * 60.0
        dropoff_latest_sec  = c.drop_off_latest_min * 60.0
        earliest_arrival    = pickup_earliest_sec + tt_sec
        for w in range(len(windows_sec) - 1, -1, -1):
            deadline = windows_sec[w] - buffer_sec
            if earliest_arrival <= deadline <= dropoff_latest_sec:
                assignment[i] = w
                break
    return assignment


def assign_individual_windows(
        commuters: List[Commuter],
        dur_fastest: np.ndarray,
        node_to_idx: Dict[int, int],
        station_idx: int) -> List[Tuple[int, int]]:
    windows = []
    for c in commuters:
        c_idx = node_to_idx.get(c.origin_node, -1)
        if c_idx < 0:
            windows.append((-1, -1))
            continue
        tt_sec = int(dur_fastest[c_idx, station_idx])
        tw_early = int(c.pickup_earliest_min * 60)
        tw_late  = int(c.drop_off_latest_min * 60) - int(tt_sec)
        if tw_late < tw_early:
            windows.append((-1, -1))
        else:
            windows.append((tw_early, tw_late))
    return windows


def calculate_baseline(
        commuters: List[Commuter],
        feasible_idx: List[int],
        raw_dist_sub: np.ndarray,
        original_count: int,
        cfg: ExperimentConfig) -> dict:
    total_mm = 0
    for sub_i, orig_i in enumerate(feasible_idx):
        total_mm += int(raw_dist_sub[sub_i + 1, 0])
    total_km = total_mm / 1_000_000.0
    fuel     = total_km * cfg.private_car_fuel_l_per_100km / 100.0
    co2      = fuel * cfg.private_car_co2_kg_per_liter
    return {
        "total_commuters":    original_count,
        "feasible_commuters": len(feasible_idx),
        "total_vmt_km":       round(total_km, 4),
        "total_fuel_liters":  round(fuel, 4),
        "total_co2_kg":       round(co2, 4),
        "passenger_km":       round(total_km, 4),
        "avg_trip_km":        round(total_km / len(feasible_idx), 4)
                              if feasible_idx else 0.0,
        "private_car_speed_kmph": cfg.private_car_speed_kmph,
    }


def compare(av: dict, baseline: dict, name: str,
            seed: int = 0, cfg: "ExperimentConfig | None" = None) -> dict:
    def pct(av_v, base_v):
        return round((av_v - base_v) / base_v * 100.0, 2) if base_v else 0.0
    raw_av_vmt = av.get("raw_av_total_vmt_km", av["total_vmt_km"])
    raw_av_fuel = av.get("raw_av_total_fuel_liters", av["total_fuel_liters"])
    raw_av_co2 = av.get("raw_av_total_co2_kg", av["total_co2_kg"])
    adjusted_av_vmt = av.get("adjusted_av_total_vmt_km", av["total_vmt_km"])
    adjusted_av_fuel = av.get("adjusted_av_total_fuel_liters", av["total_fuel_liters"])
    adjusted_av_co2 = av.get("adjusted_av_total_co2_kg", av["total_co2_kg"])
    system_vmt = av.get("system_total_vmt_km", av["total_vmt_km"])
    system_fuel = av.get("system_total_fuel_liters", av["total_fuel_liters"])
    system_co2 = av.get("system_total_co2_kg", av["total_co2_kg"])
    vmt_change_pct = pct(av["total_vmt_km"], baseline["total_vmt_km"])
    fuel_change_pct = pct(av["total_fuel_liters"], baseline["total_fuel_liters"])
    co2_change_pct = pct(av["total_co2_kg"], baseline["total_co2_kg"])
    out = {
        "experiment_name":           name,
        "seed":                      seed,
        "penalty_mode":              cfg.penalty_mode              if cfg else "",
        "time_window_mode":          cfg.time_window.mode          if cfg else "",
        "interval_minutes":          cfg.time_window.interval_minutes if cfg else 0,
        "service_rate_pct":          av["service_rate"],
        "on_time_rate_pct":          av["on_time_rate"],
        "late_deliveries":           av["late_deliveries"],
        "vmt_change_pct":            vmt_change_pct,
        "fuel_change_pct":           fuel_change_pct,
        "co2_change_pct":            co2_change_pct,
        "av_total_vmt_km":           av["total_vmt_km"],
        "baseline_total_vmt_km":     baseline["total_vmt_km"],
        "av_total_co2_kg":           av["total_co2_kg"],
        "baseline_total_co2_kg":     baseline["total_co2_kg"],
        "raw_av_total_vmt_km":       raw_av_vmt,
        "raw_av_total_fuel_liters":  raw_av_fuel,
        "raw_av_total_co2_kg":       raw_av_co2,
        "adjusted_av_total_vmt_km":      adjusted_av_vmt,
        "adjusted_av_total_fuel_liters": adjusted_av_fuel,
        "adjusted_av_total_co2_kg":      adjusted_av_co2,
        "system_total_vmt_km":       system_vmt,
        "system_total_fuel_liters":  system_fuel,
        "system_total_co2_kg":       system_co2,
        "system_vmt_change_pct":     vmt_change_pct,
        "system_fuel_change_pct":    fuel_change_pct,
        "system_co2_change_pct":     co2_change_pct,
        "avg_passengers_per_trip":   av["avg_passengers_per_trip"],
        "vehicles_used":             av["vehicles_used"],
        "vehicle_trips":             av["vehicle_trips"],
        "solo_trips":                av["solo_trips"],
        "shared_trips":              av["shared_trips"],
        "avg_in_vehicle_time_min":   av["avg_in_vehicle_time_min"],
        "max_in_vehicle_time_min":   av["max_in_vehicle_time_min"],
        "avg_detour_ratio":          av["avg_detour_ratio"],
        "max_detour_ratio":          av["max_detour_ratio"],
        "baseline_avg_trip_km":      baseline["avg_trip_km"],
        "baseline_avg_trip_min":     round(
            baseline["avg_trip_km"] / baseline.get("private_car_speed_kmph", 50) * 60, 2
        ) if baseline.get("avg_trip_km") else 0.0,
    }
    for key in (
        "fallback_private_cars",
        "baseline_parking_spaces",
        "station_commuter_parking_spaces",
        "station_parking_reduction_pct",
        "fleet_storage_equiv_spaces",
        "net_parking_equiv_if_fleet_stored_at_station",
        "net_parking_reduction_pct_if_fleet_stored_at_station",
    ):
        if key in av:
            out[key] = av[key]
    return out
