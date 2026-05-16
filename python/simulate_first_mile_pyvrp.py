"""
simulate_first_mile_pyvrp.py
════════════════════════════
First-mile AV-to-station routing using PyVRP (HGS algorithm).

Replaces simulate_first_mile_ortools with:
  - Native multi-trip via max_duration (no virtual vehicles, no cascade bugs)
  - Per-vehicle-type distance matrices (exact soft preference, same as OR-Tools)
  - Per-vehicle-type duration matrices (correct time window evaluation per speed)
  - Heterogeneous fleet: Scooter / Moped / Car / Minibus
  - Optional commuters (partial solution)
  - Same input/output CSV format as the C++ version

Note on time-window feasibility:
  PyVRP enforces pickup-time windows per client. For pooled multi-trip routes,
  passenger-specific station-arrival deadlines are not directly enforced by the
  solver. Final station-arrival feasibility is therefore audited after route
  extraction and reported via late_deliveries and on_time_rate in all output
  files. A solution marked feasible=True by PyVRP may still contain late
  station arrivals due to pooling detours or slower assigned vehicle types.

Prerequisites:
  pip install pyvrp numpy

Usage:
  python simulate_first_mile_pyvrp.py \\
      commuters.csv stations.csv matrices/ \\
      assignments.csv av_routes.csv config.json \\
      baseline.json metrics.json comparison.json [seed]

Where matrices/ is the directory produced by dump_distance_matrix.
"""

import sys
import json
import csv
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
from collections import Counter

import numpy as np

# ── PyVRP ─────────────────────────────────────────────────────────────────
try:
    from pyvrp import Model
    from pyvrp.stop import MaxRuntime, NoImprovement, MultipleCriteria
    from pyvrp.solve import SolveParams
    from pyvrp import PenaltyParams
    import pyvrp as _pyvrp
except ImportError:
    print("ERROR: PyVRP not installed. Run:  pip install pyvrp")
    sys.exit(1)

# Import pure utility functions from separate module so they can be
# unit-tested without requiring PyVRP to be installed (tests import
# the utils module directly).
from simulate_first_mile_utils import (
    Commuter,
    VehicleConfig,
    TimeWindowConfig,
    ExperimentConfig,
    smooth_penalty,
    build_cost_matrix,
    generate_windows_sec,
    assign_latest_feasible_window,
    assign_individual_windows,
    calculate_baseline,
    compare,
)


# Data classes are imported from simulate_first_mile_utils to ensure a
# single canonical definition for type checking and unit tests.


# ══════════════════════════════════════════════════════════════════════════
# LOADERS
# ══════════════════════════════════════════════════════════════════════════

def load_commuters(path: str) -> List[Commuter]:
    """Load commuters.csv — id,origin_node,destination_node,pickup_earliest,drop_off_latest"""
    def to_min(hhmm: str) -> float:
        h, m = hhmm.strip().split(":")
        return int(h) * 60 + int(m)
    commuters = []
    with open(path) as f:
        for row in csv.DictReader(f):
            commuters.append(Commuter(
                id=int(row["id"]),
                origin_node=int(row["origin_node"]),
                destination_node=int(row["destination_node"]),
                pickup_earliest_min=to_min(row["pickup_earliest"]),
                drop_off_latest_min=to_min(row["drop_off_latest"]),
            ))
    print(f"  ✓ Loaded {len(commuters)} commuters")
    return commuters


def load_station_node(path: str) -> int:
    with open(path) as f:
        for row in csv.DictReader(f):
            node = int(row["node_id"])
            print(f"  ✓ Station node: {node}")
            return node
    raise ValueError(f"No station rows in {path}")


def load_config(path: str) -> ExperimentConfig:
    with open(path) as f:
        cfg = json.load(f)
    vtypes = []
    for v in cfg["fleet"]["vehicle_types"]:
        vtypes.append(VehicleConfig(
            name=v["name"],
            capacity=v["capacity"],
            max_speed_kmph=v["max_speed_kmph"],
            fuel_l_per_100km=v["fuel_l_per_100km"],
            co2_kg_per_liter=v["co2_kg_per_liter"],
            fleet_size=v["fleet_size"],
            lower_km=v["distance_band"]["lower_km"],
            upper_km=v["distance_band"]["upper_km"],
            fixed_cost_km_equiv=v["fixed_cost_km_equiv"],
        ))
    tw = cfg["time_window"]
    buf_sec = tw.get("buffer_before_deadline_minutes", 0.0) * 60.0
    sc = cfg["solver_config"]
    bp = cfg["baseline_parameters"]
    return ExperimentConfig(
        experiment_name=cfg["experiment_name"],
        vehicle_types=vtypes,
        time_window=TimeWindowConfig(
            mode=tw.get("mode", "fixed_slots"),
            interval_minutes=tw.get("interval_minutes", 10),
            start_time_minutes=tw.get("start_time_minutes", 420),
            end_time_minutes=tw.get("end_time_minutes", 570),
            buffer_before_deadline_sec=buf_sec,
        ),
        time_limit_seconds=sc["time_limit_seconds"],
        alpha=cfg["penalty_parameters"]["alpha"],
        beta=cfg["penalty_parameters"]["beta"],
        penalty_mode=cfg["penalty_parameters"].get("penalty_mode", "multiplicative"),
        preference_scale_m=int(cfg["penalty_parameters"].get("preference_scale_m", 500)),
        private_car_fuel_l_per_100km=bp["private_car_fuel_l_per_100km"],
        private_car_co2_kg_per_liter=bp["private_car_co2_kg_per_liter"],
        private_car_speed_kmph=bp["private_car_speed_kmph"],
    )


def load_matrices(matrices_dir: str, vehicle_types: List[VehicleConfig]):
    """
    Load distance and duration matrices produced by dump_distance_matrix.

    Converts units for PyVRP compatibility:
      dist_mm (millimetres) → dist_m  (metres)     ÷1000
      dur_ms  (milliseconds) → dur_sec (seconds)   ÷1000

    PyVRP requires consistent integer scaling. Using metres + seconds
    gives values in the range [0, ~30000] which PyVRP handles well.
    Using mm + ms causes scaling differences of 1000× which triggers
    PenaltyBoundWarning and infeasible solutions.

    Returns:
        dist_m       : np.ndarray int64  shape (M, M)  metres
        dur_sec_by_speed : dict  speed_kmph -> np.ndarray int64 shape (M,M) seconds
        dist_mm_raw  : np.ndarray int64  shape (M, M)  millimetres (for metrics only)
        nodes        : list of int  node IDs in matrix order (nodes[0] = station)
    """
    d = Path(matrices_dir)
    dist_mm_raw = np.load(str(d / "distances.npy"))
    nodes       = [int(x) for x in (d / "nodes.txt").read_text().split()]

    # Convert mm → m  (integer division, lose sub-metre precision — acceptable)
    dist_m = (dist_mm_raw // 1000).astype(np.int64)

    # Load duration matrices, convert ms → sec
    speeds_needed = set(vc.max_speed_kmph for vc in vehicle_types)
    dur_sec_by_speed = {}
    for spd in speeds_needed:
        fname = d / f"duration_{int(spd)}kmph.npy"
        if not fname.exists():
            raise FileNotFoundError(
                f"Duration matrix not found: {fname}\n"
                f"Did you run dump_distance_matrix with this speed? "
                f"Available speeds: 30, 45, 70, 80 kmph"
            )
        dur_ms = np.load(str(fname))
        dur_sec_by_speed[spd] = (dur_ms // 1000).astype(np.int64)

    M = dist_m.shape[0]
    print(f"  ✓ Matrices loaded: {M}×{M}  ({M} nodes incl. depot)")
    print(f"  ✓ Units: distances in metres, durations in seconds")
    return dist_m, dur_sec_by_speed, dist_mm_raw, nodes


# ══════════════════════════════════════════════════════════════════════════
# BUILD PyVRP MODEL
# ══════════════════════════════════════════════════════════════════════════

def build_model(
        commuters: List[Commuter],
        window_assignment,          # List[int] for fixed_slots, List[Tuple] for individual
        windows_sec: Optional[List[int]],   # None in individual mode
        cfg: ExperimentConfig,
        dist_m: np.ndarray,
        dur_sec_by_speed: Dict[float, np.ndarray],
        node_to_idx: Dict[int, int],
        station_idx: int):
    """
    Build the PyVRP model.

    Key design decisions:
    ─────────────────────
    • Per-vehicle-type cost matrices: each VehicleType gets its own
      penalised distance matrix (smooth_penalty baked in). This is the
      exact equivalent of your OR-Tools per-vehicle arc cost callbacks.

    • Per-vehicle-type duration matrices: each VehicleType uses travel
      times computed at its own max_speed_kmph. This fixes the OR-Tools
      bug where all vehicles used the fastest speed for time feasibility.

    • max_duration per vehicle type: set to the full service window
      (e.g. 150 min). PyVRP's HGS automatically inserts depot returns
      when a vehicle would exceed this — native multi-trip, no virtual
      vehicles, no sequencing constraints.

    • Optional clients with skip penalty: matches allow_partial_solution.

    Returns (model, feasible_commuter_indices, cost_matrices_per_type).
    """

    service_start_sec = cfg.time_window.start_time_minutes * 60
    service_end_sec   = cfg.time_window.end_time_minutes   * 60
    # Depot window: slightly wider than service window so vehicles can
    # depart just before first pickup and return just after last dropoff
    depot_open  = max(0, service_start_sec - 30 * 60)
    depot_close = service_end_sec + 30 * 60

    # max_duration = full service window → enables multi-trip
    max_duration_sec = service_end_sec - service_start_sec

    individual_mode = (cfg.time_window.mode == "individual")

    if individual_mode:
        # window_assignment is List[Tuple[tw_early, tw_late]], -1,-1 = infeasible
        feasible_idx = [i for i, tw in enumerate(window_assignment) if tw[0] >= 0]
        # Service window = span of all individual windows
        all_early = [window_assignment[i][0] for i in feasible_idx]
        all_late  = [window_assignment[i][1] for i in feasible_idx]
        service_start_sec = min(all_early) if all_early else cfg.time_window.start_time_minutes * 60
        service_end_sec   = max(all_late)  if all_late  else cfg.time_window.end_time_minutes   * 60
    else:
        # window_assignment is List[int] — index into windows_sec, -1 = infeasible
        feasible_idx = [i for i, w in enumerate(window_assignment) if w >= 0]
        service_start_sec = cfg.time_window.start_time_minutes * 60
        service_end_sec   = cfg.time_window.end_time_minutes   * 60

    n_feasible = len(feasible_idx)
    print(f"  Feasible commuters: {n_feasible}/{len(commuters)}")

    # Sub-matrix indices: [station_idx] + [commuter matrix indices]
    matrix_rows = [station_idx] + [node_to_idx[commuters[i].origin_node]
                                    for i in feasible_idx]

    def sub(mat: np.ndarray) -> np.ndarray:
        """Extract sub-matrix for feasible nodes only."""
        idx = np.array(matrix_rows, dtype=np.intp)
        return mat[np.ix_(idx, idx)]

    # Build one cost matrix per vehicle type (with smooth penalty, in metres)
    # Extract distance submatrix once, then build per-type cost matrices on it.
    # Cheaper than building full 1466×1466 penalised matrices and slicing after.
    dist_m_sub = sub(dist_m)
    cost_matrices = []
    for vc in cfg.vehicle_types:
        cost_matrices.append(build_cost_matrix(
            dist_m_sub, vc.lower_km, vc.upper_km, cfg.alpha, cfg.beta,
            penalty_mode=cfg.penalty_mode,
            preference_scale_m=cfg.preference_scale_m,
        ))

    # Build one duration matrix per vehicle type (by speed, in seconds)
    dur_matrices = []
    for vc in cfg.vehicle_types:
        dur_matrices.append(sub(dur_sec_by_speed[vc.max_speed_kmph]))

    # ── Build skip penalty ─────────────────────────────────────────────
    # PyVRP's penalty manager works with values in roughly [0, 100_000].
    # Cost matrix entries are in metres (avg trip ~5000m, max ~20000m).
    # With smooth penalties up to 50×, max penalised arc ≈ 1,000,000m.
    #
    # Skip penalty must be:
    #   (a) larger than the most expensive arc cost → solver always prefers serving
    #   (b) small enough not to hit PyVRP's internal penalty ceiling
    #
    # Fixed value of 2,000,000m (2000 km-equiv) works for instances up to
    # ~2000 commuters. Any arc in Melton is < 30km = 30,000m unpenalised,
    # so even with 50× penalty = 1,500,000m < 2,000,000m skip cost.
    skip_penalty = 2_000_000   # 2000 km in metres — fixed, scale-stable

    print(f"  Skip penalty: {skip_penalty / 1000:.0f} km-equiv (fixed)")
    print(f"  Max duration per vehicle: {max_duration_sec // 60} min (multi-trip enabled)")

    # ── Construct PyVRP Model  (PyVRP 0.13.x API) ─────────────────────
    m = Model()

    # ── Depot ──────────────────────────────────────────────────────────
    depot = m.add_depot(
        x=0, y=0,
        tw_early=depot_open,
        tw_late=depot_close,
    )

    # ── One routing profile per vehicle type ───────────────────────────
    # In PyVRP 0.9+, profiles are created with m.add_profile().
    # Edges are added via m.add_edge(..., profile=profile_obj).
    profiles = []
    for vc in cfg.vehicle_types:
        profiles.append(m.add_profile(name=vc.name))

    # ── Clients ────────────────────────────────────────────────────────
    clients = []
    clamped_count   = 0      # diagnostic: tw_late < tw_early before fix
    clamped_examples: list  = []
    excluded_clamp  = 0      # commuters excluded due to tw_late < tw_early
    valid_feasible_idx = []  # feasible_idx entries that actually get a client

    for orig_idx in feasible_idx:
        c = commuters[orig_idx]
        # default placeholders to satisfy type checker and diagnostics
        w = None
        direct_tt_sec = None

        # default placeholders to satisfy type checker and diagnostics
        w = None
        direct_tt_sec = None

        if individual_mode:
            # Use individual window directly from CSV
            tw_early, tw_late = window_assignment[orig_idx]
        else:
            # Use assigned fixed train slot
            # windows_sec is guaranteed non-None in fixed_slots mode
            assert windows_sec is not None
            w = window_assignment[orig_idx]
            tw_early = int(c.pickup_earliest_min * 60)
            # tw_late: latest pickup time such that direct travel to station
            # reaches the assigned slot deadline, after applying any fixed
            # buffer_before_deadline_sec. Consistent with slot assignment logic
            # in assign_latest_feasible_window.
            c_idx = node_to_idx.get(c.origin_node, -1)
            if c_idx >= 0:
                spd = max(vc.max_speed_kmph for vc in cfg.vehicle_types)
                direct_tt_sec = float(dur_sec_by_speed[spd][c_idx, station_idx])
            else:
                direct_tt_sec = 0.0
            tw_late = int(windows_sec[w]
                          - cfg.time_window.buffer_before_deadline_sec
                          - direct_tt_sec)

        # Guard: tw_late < tw_early means the slot assignment and model
        # construction used inconsistent travel times (rounding / speed
        # mismatch).  Previously this was silently clamped to tw_late=tw_early,
        # producing zero-width windows that the solver treated as hard
        # pickup-time constraints, inflating late arrivals artificially.
        # Fix: exclude these commuters from the model entirely (same as -1
        # from assign_latest_feasible_window) and report diagnostics.
        if tw_late < tw_early:
            clamped_count += 1
            if len(clamped_examples) < 10:
                assigned_slot_min = None
                if (not individual_mode) and (windows_sec is not None) and (w is not None):
                    assigned_slot_min = windows_sec[w] / 60
                direct_tt_val = direct_tt_sec if (not individual_mode) else None
                clamped_examples.append({
                    "commuter_id":        c.id,
                    "pickup_earliest_min": c.pickup_earliest_min,
                    "drop_off_latest_min": c.drop_off_latest_min,
                    "assigned_slot_min":  assigned_slot_min,
                    "tw_early_min":       tw_early / 60,
                    "tw_late_before_fix": tw_late / 60,
                    "direct_tt_sec":      direct_tt_val,
                })
            excluded_clamp += 1
            continue   # exclude from model — do NOT clamp

        valid_feasible_idx.append(orig_idx)

        # PyVRP 0.13 uses delivery= for load (replaces old demand=)
        clients.append(m.add_client(
            x=0, y=0,
            delivery=1,
            tw_early=tw_early,
            tw_late=tw_late,
            prize=skip_penalty,
            required=False,
        ))

    # Report clamp diagnostics
    if clamped_count > 0:
        print(f"  WARNING: tw_late < tw_early detected and excluded: {clamped_count} commuters")
        print(f"     (speed/rounding mismatch between slot assignment and model construction)")
        for ex in clamped_examples:
            print(f"     {ex}")
    else:
        print(f"  OK: No tw_late < tw_early cases (clamp guard not triggered)")

    # Replace feasible_idx with the subset that actually got clients
    # and rebuild sub-matrices so sub-index positions remain consistent.
    # (matrix_rows was built before the loop using the original feasible_idx;
    #  if any commuters were excluded by the clamp guard we must re-slice.)
    if excluded_clamp > 0:
        feasible_idx  = valid_feasible_idx
        n_feasible    = len(feasible_idx)
        matrix_rows   = [station_idx] + [node_to_idx[commuters[i].origin_node]
                                          for i in feasible_idx]
        idx_arr       = np.array(matrix_rows, dtype=np.intp)
        dist_m_sub    = dist_m[np.ix_(idx_arr, idx_arr)]
        cost_matrices = []
        for vc in cfg.vehicle_types:
            cost_matrices.append(build_cost_matrix(
                dist_m_sub, vc.lower_km, vc.upper_km, cfg.alpha, cfg.beta,
                penalty_mode=cfg.penalty_mode,
                preference_scale_m=cfg.preference_scale_m,
            ))
        dur_matrices = []
        for vc in cfg.vehicle_types:
            dm = dur_sec_by_speed[vc.max_speed_kmph]
            dur_matrices.append(dm[np.ix_(idx_arr, idx_arr)])
        print(f"  Sub-matrices rebuilt after {excluded_clamp} clamp exclusions")
    else:
        feasible_idx = valid_feasible_idx
        n_feasible   = len(feasible_idx)

    print(f"  Clients added to model: {n_feasible}")

    # ── Vehicle types ──────────────────────────────────────────────────
    for k, vc in enumerate(cfg.vehicle_types):
        m.add_vehicle_type(
            num_available=vc.fleet_size,
            capacity=vc.capacity,
            start_depot=depot,
            end_depot=depot,
            fixed_cost=int(vc.fixed_cost_km_equiv * 1_000),
            tw_early=depot_open,
            tw_late=depot_close,
            shift_duration=max_duration_sec,
            reload_depots=[depot],
            name=vc.name,
            profile=profiles[k],
        )

    # ── Edges per profile ──────────────────────────────────────────────
    # m.locations = [depot, client_0, client_1, ..., client_N]
    # Indices match sub-matrices: 0=depot, 1..n=clients.
    all_locs = list(m.locations)
    n_locs   = len(all_locs)

    for k, profile in enumerate(profiles):
        cost_mat = cost_matrices[k]  # shape (n_locs, n_locs)
        dur_mat  = dur_matrices[k]

        for i in range(n_locs):
            for j in range(n_locs):
                if i == j:
                    continue
                m.add_edge(
                    frm=all_locs[i],
                    to=all_locs[j],
                    distance=int(cost_mat[i, j]),
                    duration=int(dur_mat[i, j]),
                    profile=profile,
                )

    return m, feasible_idx, cost_matrices


# ══════════════════════════════════════════════════════════════════════════
# SOLVE
# ══════════════════════════════════════════════════════════════════════════

def solve(model: "Model", time_limit_sec: int, no_improve_iters: int = 10000,
          skip_penalty: int = 2_000_000, seed: int = 0):
    """
    Solve with PyVRP HGS.

    Key: set max_penalty >> skip_penalty so capacity violations always
    cost more than skipping a commuter. This forces the solver to drop
    commuters rather than overload vehicles.

    skip_penalty (metres) = cost of skipping one commuter.
    max_penalty must exceed skip_penalty so that:
      penalty_per_unit_excess × 1 unit > skip_penalty
    → solver always prefers skipping over overloading.
    """
    print(f"\n  Time limit: {time_limit_sec}s  "
          f"(early stop after {no_improve_iters:,} non-improving iterations)")

    # max_penalty must be > skip_penalty to make capacity a hard constraint.
    # We set it to 10× skip_penalty for a strong margin.
    hard_cap_penalty = skip_penalty * 10  # 20,000,000 >> 2,000,000

    params = SolveParams(
        penalty=PenaltyParams(
            max_penalty=float(hard_cap_penalty),
            min_penalty=0.1,
            # Aggressively push towards feasibility
            target_feasible=0.50,
            penalty_increase=2.0,
            penalty_decrease=0.85,
        )
    )

    t0 = time.time()
    result = model.solve(
        stop=MultipleCriteria([
            MaxRuntime(time_limit_sec),
            NoImprovement(max_iterations=no_improve_iters),
        ]),
        seed=seed,
        display=True,
        params=params,
    )
    elapsed = time.time() - t0
    print(f"\n  Solved in {elapsed:.1f}s")
    cost = result.cost()
    if cost == float('inf'):
        print(f"  Best objective: INFEASIBLE (partial solution — see service rate)")
    else:
        print(f"  Best objective: {cost:.0f}")
    print(f"  Routes in solution: {len(result.best.routes())}")
    print(f"  Feasible: {result.best.is_feasible()}")
    return result


# ══════════════════════════════════════════════════════════════════════════
# EXTRACT RESULTS + COMPUTE METRICS + WRITE CSVs
# ══════════════════════════════════════════════════════════════════════════

def extract_results(
        result,
        commuters: List[Commuter],
        feasible_idx: List[int],
        window_assignment,
        windows_sec: Optional[List[int]],
        cfg: ExperimentConfig,
        raw_dist_sub: np.ndarray,       # mm, shape (n_locs, n_locs)
        cost_matrices: List[np.ndarray], # penalised metres, one per vehicle type
        station_node: int,
        assignments_csv: str,
        av_routes_csv: str,
        original_count: int = 0) -> dict:
    """
    Parse PyVRP routes and write output CSVs matching your existing format:

    assignments.csv:
        commuter_id, window_time, av_type, av_id, cost,
        station_node, path, shared_with, status

    av_routes.csv:
        av_type, av_id, physical_id, trip_num, station_node,
        pickup_order_commuters, pickup_nodes, route_nodes
    """

    routes = result.best.routes()

    # Map sub-matrix index (1-based) → original commuter index
    # sub-index 0 = depot, 1..n = commuters in feasible_idx order
    sub_to_orig = {sub_i + 1: orig_i
                   for sub_i, orig_i in enumerate(feasible_idx)}

    served_orig_ids = set()
    assign_rows = []
    route_rows  = []

    # ── Accumulators ──────────────────────────────────────────────────────
    total_vmt_mm        = 0
    total_penalised_m   = 0
    total_empty_mm      = 0
    total_loaded_mm     = 0
    total_fuel_L        = 0.0
    total_co2_kg        = 0.0
    total_pax_km        = 0.0
    vehicle_trips       = 0
    solo_trips          = 0
    shared_trips        = 0
    vehicles_used       = 0
    late_deliveries     = 0   # commuters whose actual station arrival > drop_off_latest

    # ── Passenger-experience accumulators ─────────────────────────────────
    # in_vehicle_times_sec: one entry per served commuter (pickup → station arrival)
    # detour_ratios: one entry per served commuter (actual route dist / direct dist)
    # Both require station_arrival from schedule(), so entries are added only
    # when that timing is available; commuters without schedule data are excluded
    # from avg/max but still counted as served.
    in_vehicle_times_sec: List[float] = []
    detour_ratios:        List[float] = []

    vtype_name_to_k = {vc.name: k for k, vc in enumerate(cfg.vehicle_types)}

    per_type: Dict[str, dict] = {
        vc.name: {"vehicles_used": 0, "vehicle_trips": 0,
                  "served_commuters": 0, "vmt_km": 0.0, "empty_km": 0.0}
        for vc in cfg.vehicle_types
    }

    vc_map       = {vc.name: vc for vc in cfg.vehicle_types}
    vtype_names  = [vc.name for vc in cfg.vehicle_types]

    for route_id, route in enumerate(routes):
        # ── Collect all client visits across the whole route ───────────
        all_visits = [v for v in route if v in sub_to_orig]
        if not all_visits:
            continue

        vtype_idx  = route.vehicle_type()
        vtype_name = vtype_names[vtype_idx]
        vc         = vc_map[vtype_name]
        vehicles_used += 1
        per_type[vtype_name]["vehicles_used"] += 1

        # ── Segment route into sub-trips using schedule() ──────────────
        # schedule() yields Activity objects for every stop including depot
        # returns. We split on depot visits (location index 0) to get
        # individual sub-trip client lists.
        #
        # A sub-trip is: depot → [clients] → depot
        # The schedule includes the start and end depot implicitly, plus
        # any reload depot visits mid-route.
        #
        # Strategy: split the flat visits list at depot boundaries.
        # We use the full schedule to identify trip boundaries.

        sub_trips = []          # list of lists of sub-matrix client indices
        # trip_depot_arrivals[i] = actual arrival time at depot for sub-trip i (seconds)
        trip_depot_arrivals = []

        try:
            for trip in route.trips():
                trip_clients = [v for v in trip if v in sub_to_orig]
                if trip_clients:
                    sub_trips.append(trip_clients)
                    # Trip.end_depot gives the depot index; use schedule to
                    # find the actual arrival time at the depot at the end of
                    # this trip. We approximate as: pickup time of last client
                    # + travel time from last client to depot.
                    # PyVRP Trip doesn't expose end time directly, so we use
                    # the duration matrix of the vehicle to compute it.
                    trip_depot_arrivals.append(None)  # filled below via schedule
        except AttributeError:
            current_trip = []
            try:
                for activity in route.schedule():
                    loc_idx = activity.location
                    if loc_idx == 0:
                        if current_trip:
                            sub_trips.append(current_trip)
                            current_trip = []
                    elif loc_idx in sub_to_orig:
                        current_trip.append(loc_idx)
                if current_trip:
                    sub_trips.append(current_trip)
            except Exception:
                pass
            trip_depot_arrivals = [None] * len(sub_trips)

        # ── Get actual depot arrival times + per-client pickup times ──────
        # schedule() yields all activities including depot returns.
        # We record:
        #   trip_depot_arrivals[t] — start_service at the depot after trip t
        #                            (= station arrival time for all pax in that trip)
        #   client_pickup_sec[sub_idx] — start_service when the AV arrives at
        #                                each client location (= pickup time)
        # Both are used below for in-vehicle time and detour ratio computation.
        client_pickup_sec: Dict[int, float] = {}  # sub-matrix idx → pickup time (sec)
        try:
            sched = route.schedule()
            trip_idx_sched  = 0
            clients_in_trip = 0

            for activity in sched:
                loc = activity.location
                if loc in sub_to_orig:
                    clients_in_trip += 1
                    client_pickup_sec[loc] = float(activity.start_service)
                elif loc == 0 and clients_in_trip > 0:
                    # Depot return after a non-empty trip
                    if trip_idx_sched < len(trip_depot_arrivals):
                        trip_depot_arrivals[trip_idx_sched] = activity.start_service
                    trip_idx_sched  += 1
                    clients_in_trip  = 0
        except Exception:
            pass

        if not sub_trips:
            sub_trips = [[v for v in route if v in sub_to_orig]]
            sub_trips = [t for t in sub_trips if t]
            trip_depot_arrivals = [None] * len(sub_trips)

        n_sub_trips = len(sub_trips)
        vehicle_trips += n_sub_trips
        per_type[vtype_name]["vehicle_trips"] += n_sub_trips

        # ── Process each sub-trip individually ─────────────────────────
        for trip_num, trip_visits in enumerate(sub_trips):
            if not trip_visits:
                continue

            trip_orig_ids   = [sub_to_orig[v] for v in trip_visits]
            trip_commuter_ids = [commuters[i].id for i in trip_orig_ids]
            trip_pickup_nodes = [commuters[i].origin_node for i in trip_orig_ids]
            n_trip_pax = len(trip_orig_ids)

            # Mark as served
            for orig_i in trip_orig_ids:
                served_orig_ids.add(orig_i)

            # ── Raw road distance (mm) ────────────────────────────────
            seq = [0] + list(trip_visits) + [0]
            trip_mm = sum(
                int(raw_dist_sub[seq[k], seq[k+1]])
                for k in range(len(seq) - 1)
            )
            # Empty leg = depot → first pickup of this sub-trip
            trip_empty_mm  = int(raw_dist_sub[0, trip_visits[0]])
            trip_loaded_mm = trip_mm - trip_empty_mm

            # ── Penalised cost (metres) — for reconciliation with solver ──
            # Uses the same cost matrix the solver used for this vehicle type.
            # Sum should equal result.best.distance() when all trips are summed.
            k = vtype_name_to_k[vtype_name]
            cost_mat = cost_matrices[k]
            trip_penalised_m = sum(
                int(cost_mat[seq[i], seq[i+1]])
                for i in range(len(seq) - 1)
            )

            total_vmt_mm      += trip_mm
            total_penalised_m += trip_penalised_m
            total_empty_mm    += trip_empty_mm
            total_loaded_mm   += trip_loaded_mm

            trip_km  = trip_mm  / 1_000_000.0
            empty_km = trip_empty_mm / 1_000_000.0

            fuel = trip_km * vc.fuel_l_per_100km / 100.0
            co2  = fuel * vc.co2_kg_per_liter
            total_fuel_L += fuel
            total_co2_kg += co2

            for sub_i in trip_visits:
                pax_km = raw_dist_sub[sub_i, 0] / 1_000_000.0
                total_pax_km += pax_km

            # Solo/shared per actual sub-trip
            if n_trip_pax <= 1:
                solo_trips   += 1
            else:
                shared_trips += 1

            per_type[vtype_name]["served_commuters"] += n_trip_pax
            per_type[vtype_name]["vmt_km"]           += trip_km
            per_type[vtype_name]["empty_km"]         += empty_km

            # ── Window time string ────────────────────────────────────
            wa = window_assignment[trip_orig_ids[0]]
            if windows_sec is not None:
                assert windows_sec is not None
                w_sec = windows_sec[wa]
                w_str = f"{w_sec // 3600:02d}:{(w_sec % 3600) // 60:02d}"
            else:
                c0    = commuters[trip_orig_ids[0]]
                dl_min = int(c0.drop_off_latest_min)
                w_str = f"{dl_min // 60:02d}:{dl_min % 60:02d}"

            # ── av_routes.csv — one row per actual sub-trip ───────────
            route_nodes_str = " ".join(
                map(str, trip_pickup_nodes + [station_node]))
            route_rows.append({
                "av_type":                vtype_name,
                "av_id":                  route_id,
                "physical_id":            route_id,
                "trip_num":               trip_num,
                "station_node":           station_node,
                "pickup_order_commuters": " ".join(map(str, trip_commuter_ids)),
                "pickup_nodes":           " ".join(map(str, trip_pickup_nodes)),
                "route_nodes":            route_nodes_str,
            })

            # ── assignments.csv — one row per commuter in this sub-trip
            station_arrival = trip_depot_arrivals[trip_num] if trip_num < len(trip_depot_arrivals) else None
            for sub_i, orig_i in zip(trip_visits, trip_orig_ids):
                c       = commuters[orig_i]
                cost_mm = int(raw_dist_sub[sub_i, 0])
                shared  = " ".join(str(commuters[o].id)
                                   for o in trip_orig_ids if o != orig_i)

                # Check if commuter arrived after their drop_off_latest
                dropoff_latest_sec = int(c.drop_off_latest_min * 60)
                if station_arrival is not None:
                    arrived_late = int(station_arrival) > dropoff_latest_sec
                    arrival_str  = f"{int(station_arrival)//3600:02d}:{(int(station_arrival)%3600)//60:02d}"
                    delay_sec    = max(0, int(station_arrival) - dropoff_latest_sec)
                else:
                    arrived_late = False
                    arrival_str  = ""
                    delay_sec    = 0

                # ── In-vehicle time (pickup → station arrival) ────────────
                # Requires both pickup time from schedule and station arrival.
                pickup_sec = client_pickup_sec.get(sub_i)
                if pickup_sec is not None and station_arrival is not None:
                    ivt_sec = float(station_arrival) - pickup_sec
                    if ivt_sec >= 0:
                        in_vehicle_times_sec.append(ivt_sec)

                # ── Detour ratio (actual route dist / direct dist) ────────
                # actual_mm: sum of road distances along the shared route
                #   from this commuter's pickup to every subsequent stop
                #   and finally to the depot, re-using the already-computed
                #   trip sequence.  We approximate with the per-commuter
                #   share of trip_mm: specifically the sub-sequence from
                #   this commuter's position in seq to the depot.
                # direct_mm: direct home → station distance (raw_dist_sub[sub_i, 0]).
                # This is the standard definition used in the confirmation report.
                direct_mm = int(raw_dist_sub[sub_i, 0])
                if direct_mm > 0:
                    # Position of this commuter in the trip sequence (1-based: 0 = depot)
                    pax_pos   = list(trip_visits).index(sub_i)
                    seq_from  = [sub_i] + list(trip_visits[pax_pos + 1:]) + [0]
                    actual_mm = sum(
                        int(raw_dist_sub[seq_from[p], seq_from[p + 1]])
                        for p in range(len(seq_from) - 1)
                    )
                    detour_ratios.append(actual_mm / direct_mm)

                if arrived_late:
                    late_deliveries += 1

                assign_rows.append({
                    "commuter_id":            c.id,
                    "window_time":            w_str,
                    "av_type":                vtype_name,
                    "av_id":                  route_id,
                    "direct_station_dist_mm": cost_mm,
                    "station_node":           station_node,
                    "path":                   f"{c.origin_node} {station_node}",
                    "shared_with":            shared,
                    "status":                 "ASSIGNED",
                    "station_arrival":        arrival_str,
                    "drop_off_latest":        f"{dropoff_latest_sec//3600:02d}:{(dropoff_latest_sec%3600)//60:02d}",
                    "arrived_late":           "YES" if arrived_late else "NO",
                    "delay_sec":              delay_sec,
                })

    # Unserved commuters
    for orig_i in feasible_idx:
        if orig_i not in served_orig_ids:
            c = commuters[orig_i]
            assign_rows.append({
                "commuter_id":            c.id,
                "window_time":            "NONE",
                "av_type": "", "av_id": "", "direct_station_dist_mm": "",
                "station_node":           station_node,
                "path": "", "shared_with": "", "status": "UNSERVED",
                "station_arrival": "", "drop_off_latest": "", "arrived_late": "", "delay_sec": "",
            })

    # ── Write CSVs ─────────────────────────────────────────────────────
    asgn_fields = ["commuter_id","window_time","av_type","av_id",
                   "direct_station_dist_mm","station_node","path","shared_with",
                   "status","station_arrival","drop_off_latest","arrived_late","delay_sec"]
    with open(assignments_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=asgn_fields)
        w.writeheader(); w.writerows(assign_rows)

    route_fields = ["av_type","av_id","physical_id","trip_num","station_node",
                    "pickup_order_commuters","pickup_nodes","route_nodes"]
    with open(av_routes_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=route_fields)
        w.writeheader(); w.writerows(route_rows)

    print(f"  ✓ {assignments_csv}")
    print(f"  ✓ {av_routes_csv}")

    # ── Distance reconciliation ────────────────────────────────────────
    # Three quantities to compare:
    #   (A) result.best.distance()  — PyVRP's own penalised cost total
    #   (B) total_penalised_m       — our reconstruction using same cost matrices
    #   (C) total_vmt_mm / 1000     — raw physical road distance in metres
    #
    # (A) ≈ (B) means extraction is correct — we captured all arcs
    # (B) > (C) is expected — penalties inflate cost over physical distance
    # Report (C) as VMT in the paper; (A)=(B) is the validation check.
    solver_dist_m   = result.best.distance()
    extracted_pen_m = total_penalised_m
    extracted_raw_m = total_vmt_mm / 1_000.0   # mm → metres
    match_pct = 100.0 * extracted_pen_m / max(1, solver_dist_m)

    print(f"\n  Distance reconciliation (validation):")
    print(f"    (A) Solver penalised distance:     {solver_dist_m/1000:.2f} km")
    print(f"    (B) Extracted penalised distance:  {extracted_pen_m/1000:.2f} km  "
          f"({match_pct:.1f}% of solver)")
    print(f"    (C) Extracted raw road distance:   {extracted_raw_m/1000:.2f} km")
    if abs(match_pct - 100.0) < 2.0:
        print(f"    ✓ (A)≈(B): extraction is correct. Gap (B)→(C) is penalty effect.")
    else:
        print(f"    ⚠  (A)≠(B): extraction may be missing arcs. Investigate trip.visits().")

    # ── Late delivery summary ──────────────────────────────────────────
    served_count = len(served_orig_ids)
    print(f"\n  On-time delivery check:")
    print(f"    Served:        {served_count}")
    print(f"    On time:       {served_count - late_deliveries}")
    print(f"    Late arrivals: {late_deliveries}"
          + (f" ⚠" if late_deliveries > 0 else " ✓"))
    if late_deliveries > 0:
        print(f"    (See arrived_late column in assignments.csv for details)")

    # ── Metrics dict ───────────────────────────────────────────────────
    served_count    = len(served_orig_ids)
    # total_commuters = original demand, not just feasible subset.
    # Using feasible_idx size would make service_rate 100% for coarse
    # fixed-slot conditions that silently exclude infeasible commuters.
    total_commuters = original_count if original_count > 0 else len(feasible_idx)
    unserved_count  = total_commuters - served_count
    total_vmt_km    = total_vmt_mm / 1_000_000.0

    # ── Passenger-experience summary stats ─────────────────────────────
    n_ivt = len(in_vehicle_times_sec)
    avg_ivt_min = round(sum(in_vehicle_times_sec) / n_ivt / 60.0, 2) if n_ivt else 0.0
    max_ivt_min = round(max(in_vehicle_times_sec) / 60.0, 2)         if n_ivt else 0.0
    n_dr = len(detour_ratios)
    avg_detour_ratio = round(sum(detour_ratios) / n_dr, 4) if n_dr else 0.0
    max_detour_ratio = round(max(detour_ratios), 4)        if n_dr else 0.0

    return {
        "total_commuters":         total_commuters,
        "served_commuters":        served_count,
        "unserved_commuters":      unserved_count,
        "service_rate":            round(100.0 * served_count / total_commuters, 2)
                                   if total_commuters else 0.0,
        "late_deliveries":         late_deliveries,
        "on_time_deliveries":      served_count - late_deliveries,
        "on_time_rate":            round(100.0 * (served_count - late_deliveries) / max(1, served_count), 2),
        # on_time_rate is over served commuters; this is over total demand —
        # the stricter metric for partial-service experiments
        "effective_on_time_service_rate": round(
            100.0 * (served_count - late_deliveries) / max(1, total_commuters), 2
        ),
        "total_vmt_km":            round(total_vmt_km, 4),
        "loaded_vmt_km":           round(total_loaded_mm / 1_000_000.0, 4),
        "empty_vmt_km":            round(total_empty_mm  / 1_000_000.0, 4),
        "empty_vmt_ratio":         round(total_empty_mm / max(1, total_vmt_mm), 4),
        "total_fuel_liters":       round(total_fuel_L, 4),
        "total_co2_kg":            round(total_co2_kg, 4),
        "passenger_km":            round(total_pax_km, 4),
        "vehicles_used":           vehicles_used,
        "vehicle_trips":           vehicle_trips,
        "solo_trips":              solo_trips,
        "shared_trips":            shared_trips,
        "avg_passengers_per_trip": round(served_count / vehicle_trips, 2)
                                   if vehicle_trips else 0.0,
        # ── Passenger-experience metrics (confirmation report Fig 2.4) ──
        # avg/max in-vehicle time: computed for commuters where schedule()
        # provided pickup timing; n_ivt <= served_count when timing unavailable.
        "avg_in_vehicle_time_min": avg_ivt_min,
        "max_in_vehicle_time_min": max_ivt_min,
        "n_in_vehicle_time_samples": n_ivt,
        # avg/max detour ratio: actual route distance / direct home->station
        # distance; always >= 1.0 (solo direct trip = 1.0 exactly).
        "avg_detour_ratio":        avg_detour_ratio,
        "max_detour_ratio":        max_detour_ratio,
        "n_detour_ratio_samples":  n_dr,
        "per_vehicle_type":        per_type,
    }


# ══════════════════════════════════════════════════════════════════════════
# BASELINE
# ══════════════════════════════════════════════════════════════════════════

def calculate_baseline(
        commuters: List[Commuter],
        feasible_idx: List[int],
        raw_dist_sub: np.ndarray,
        original_count: int,
        cfg: ExperimentConfig) -> dict:
    """
    Private vehicle baseline: every commuter drives alone.
    Mirrors your C++ calculate_private_vehicle_baseline.
    raw_dist_sub[sub_i+1, 0] = commuter i → station in mm.
    """
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
    out = {
        "experiment_name":           name,
        # ── Run metadata (for batch aggregation) ──
        "seed":                      seed,
        "penalty_mode":              cfg.penalty_mode              if cfg else "",
        "time_window_mode":          cfg.time_window.mode          if cfg else "",
        "interval_minutes":          cfg.time_window.interval_minutes if cfg else 0,
        # ── Service quality ──
        "service_rate_pct":          av["service_rate"],
        "on_time_rate_pct":          av["on_time_rate"],
        "late_deliveries":           av["late_deliveries"],
        # ── Environmental comparison ──
        "vmt_change_pct":            pct(av["total_vmt_km"],      baseline["total_vmt_km"]),
        "fuel_change_pct":           pct(av["total_fuel_liters"],  baseline["total_fuel_liters"]),
        "co2_change_pct":            pct(av["total_co2_kg"],       baseline["total_co2_kg"]),
        "av_total_vmt_km":           av["total_vmt_km"],
        "baseline_total_vmt_km":     baseline["total_vmt_km"],
        "av_total_co2_kg":           av["total_co2_kg"],
        "baseline_total_co2_kg":     baseline["total_co2_kg"],
        # ── Fleet usage ──
        "avg_passengers_per_trip":   av["avg_passengers_per_trip"],
        "vehicles_used":             av["vehicles_used"],
        "vehicle_trips":             av["vehicle_trips"],
        "solo_trips":                av["solo_trips"],
        "shared_trips":              av["shared_trips"],
        # ── Passenger experience ──
        "avg_in_vehicle_time_min":   av["avg_in_vehicle_time_min"],
        "max_in_vehicle_time_min":   av["max_in_vehicle_time_min"],
        "avg_detour_ratio":          av["avg_detour_ratio"],
        "max_detour_ratio":          av["max_detour_ratio"],
        # ── Baseline reference ──
        "baseline_avg_trip_km":      baseline["avg_trip_km"],
        "baseline_avg_trip_min":     round(
            baseline["avg_trip_km"] / baseline.get("private_car_speed_kmph", 50) * 60, 2
        ) if baseline.get("avg_trip_km") else 0.0,
    }
    return out


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) not in (10, 11):
        print(
            "Usage: python simulate_first_mile_pyvrp.py\n"
            "  commuters.csv  stations.csv  matrices_dir/\n"
            "  assignments.csv  av_routes.csv  config.json\n"
            "  baseline.json  metrics.json  comparison.json  [seed]"
        )
        sys.exit(1)

    (commuters_csv, stations_csv, matrices_dir,
     assignments_csv, av_routes_csv, config_json,
     baseline_json, metrics_json, comparison_json) = sys.argv[1:10]
    solver_seed = int(sys.argv[10]) if len(sys.argv) == 11 else 0

    banner = "═" * 66

    print(f"\n╔{banner}╗")
    print( "║        FIRST-MILE AV SIMULATION  ·  PyVRP / HGS               ║")
    print(f"╚{banner}╝\n")
    # show_versions() prints to stdout directly
    _pyvrp.show_versions()

    # ── 1. Load inputs ─────────────────────────────────────────────────
    print(f"{'─'*40}\n  LOADING INPUTS\n{'─'*40}")
    cfg          = load_config(config_json)
    commuters    = load_commuters(commuters_csv)
    station_node = load_station_node(stations_csv)
    original_count = len(commuters)
    print(f"  ✓ Config: {cfg.experiment_name}")
    print(f"  ✓ Seed:   {solver_seed}")
    print(f"  ✓ Fleet:  {sum(v.fleet_size for v in cfg.vehicle_types)} vehicles "
          f"({', '.join(f'{v.fleet_size} {v.name}' for v in cfg.vehicle_types)})")

    # ── 2. Load matrices ───────────────────────────────────────────────
    print(f"\n{'─'*40}\n  LOADING MATRICES\n{'─'*40}")
    dist_m, dur_sec_by_speed, dist_mm_raw, nodes = load_matrices(
        matrices_dir, cfg.vehicle_types
    )

    # Build node → matrix index lookup
    node_to_idx = {n: i for i, n in enumerate(nodes)}
    station_idx = node_to_idx[station_node]

    # ── 3. Filter unreachable commuters ────────────────────────────────
    print(f"\n{'─'*40}\n  CHECKING REACHABILITY\n{'─'*40}")
    reachable = []
    unreachable_count = 0
    for c in commuters:
        if c.origin_node in node_to_idx:
            idx = node_to_idx[c.origin_node]
            if int(dist_m[idx, station_idx]) < int(1e8):  # not penalty value (1e12mm → 1e9m)
                reachable.append(c)
            else:
                unreachable_count += 1
        else:
            unreachable_count += 1
    if unreachable_count:
        print(f"  ⚠  Filtered {unreachable_count} unreachable commuters")
    commuters = reachable
    print(f"  ✓ Reachable: {len(commuters)}/{original_count}")

    # ── 4. Time window assignment ──────────────────────────────────────
    print(f"\n{'─'*40}\n  TIME WINDOW ASSIGNMENT\n{'─'*40}")
    print(f"  Mode: {cfg.time_window.mode}")

    # Use fastest vehicle for feasibility screening (optimistic).
    # Slower assigned vehicles or pooling detours may still cause late arrivals;
    # final station-arrival feasibility is audited after route extraction
    # and reported via on_time_rate.
    max_speed   = max(vc.max_speed_kmph for vc in cfg.vehicle_types)
    dur_fastest = dur_sec_by_speed[max_speed]

    if cfg.time_window.mode == "individual":
        # ── Individual mode: use each commuter's own drop_off_latest ──────
        # No fixed train slots. tw_late = drop_off_latest - travel_to_station.
        window_assignment = assign_individual_windows(
            commuters, dur_fastest, node_to_idx, station_idx
        )
        windows_sec = None  # not used in individual mode

        feasible_commuters = [c for c, tw in zip(commuters, window_assignment) if tw[0] >= 0]
        window_assignment  = [tw for tw in window_assignment if tw[0] >= 0]

        # Print window width distribution
        widths = [(tw[1] - tw[0]) / 60 for tw in window_assignment]
        if widths:
            print(f"  Window widths: min={min(widths):.1f} max={max(widths):.1f} "
                  f"avg={sum(widths)/len(widths):.1f} min")
        print(f"  ✓ {len(feasible_commuters)} commuters with individual windows")

    else:
        # ── Fixed-slot mode: assign to latest feasible train departure ────
        # Comparable with OR-Tools. Same logic as C++ assign_latest_feasible_window.
        windows_sec = generate_windows_sec(cfg.time_window)
        print(f"  Windows: {[f'{w//3600:02d}:{(w%3600)//60:02d}' for w in windows_sec]}")

        window_assignment = assign_latest_feasible_window(
            commuters, windows_sec, dur_fastest, node_to_idx, station_idx,
            cfg.time_window.buffer_before_deadline_sec
        )

        wcount = Counter(w for w in window_assignment if w >= 0)
        for w_idx in sorted(wcount):
            ws = windows_sec[w_idx]
            print(f"  Window {w_idx:2d} "
                  f"({ws//3600:02d}:{(ws%3600)//60:02d}): "
                  f"{wcount[w_idx]:4d} commuters")

        no_window = sum(1 for w in window_assignment if w < 0)
        if no_window:
            print(f"  ⚠  {no_window} commuters have no feasible window — excluded")

        feasible_commuters = [c for c, w in zip(commuters, window_assignment) if w >= 0]
        window_assignment  = [w for w in window_assignment if w >= 0]

    commuters = feasible_commuters

    # ── 5. Baseline ────────────────────────────────────────────────────
    print(f"\n{'─'*40}\n  PRIVATE VEHICLE BASELINE\n{'─'*40}")
    feasible_idx_for_baseline = list(range(len(commuters)))

    # Build sub-matrix for feasible commuters vs station (use raw mm for metrics)
    matrix_rows_b = [station_idx] + [node_to_idx[c.origin_node] for c in commuters]
    idx_arr = np.array(matrix_rows_b, dtype=np.intp)
    raw_dist_mm_sub_baseline = dist_mm_raw[np.ix_(idx_arr, idx_arr)]

    baseline = calculate_baseline(
        commuters, feasible_idx_for_baseline,
        raw_dist_mm_sub_baseline, original_count, cfg
    )
    print(f"  Total VMT (private):  {baseline['total_vmt_km']:.2f} km")
    print(f"  Total CO₂ (private):  {baseline['total_co2_kg']:.2f} kg")
    print(f"  Avg trip:             {baseline['avg_trip_km']:.2f} km")
    with open(baseline_json, "w") as f:
        json.dump(baseline, f, indent=2)
    print(f"  ✓ Written: {baseline_json}")

    # ── 6. Build PyVRP model ───────────────────────────────────────────
    print(f"\n{'─'*40}\n  BUILDING PyVRP MODEL\n{'─'*40}")
    model, feasible_idx, cost_matrices = build_model(
        commuters, window_assignment, windows_sec, cfg,
        dist_m, dur_sec_by_speed, node_to_idx, station_idx
    )

    service_min = cfg.time_window.end_time_minutes - cfg.time_window.start_time_minutes
    tw_mode_str = ("Individual (drop_off_latest per commuter)"
                   if cfg.time_window.mode == "individual"
                   else f"Fixed slots ({cfg.time_window.interval_minutes}-min intervals, OR-Tools comparable)")
    print(f"  Time window mode:  {tw_mode_str}")

    if cfg.time_window.mode == "individual":
        # In individual mode window_assignment is List[Tuple[int,int]]
        ind_wa: List[Tuple[int,int]] = window_assignment  # type: ignore[assignment]
        all_tw = [tw for tw in ind_wa if tw[0] >= 0]
        if all_tw:
            eff_start_sec = min(tw[0] for tw in all_tw)
            eff_end_sec   = max(tw[1] for tw in all_tw)
            eff_min = (eff_end_sec - eff_start_sec) // 60
            print(f"  Effective window span: "
                  f"{eff_start_sec//3600:02d}:{(eff_start_sec%3600)//60:02d} – "
                  f"{eff_end_sec//3600:02d}:{(eff_end_sec%3600)//60:02d} "
                  f"({eff_min} min, from commuter windows)")
    else:
        print(f"  Service window: "
              f"{cfg.time_window.start_time_minutes//60:02d}:"
              f"{cfg.time_window.start_time_minutes%60:02d} – "
              f"{cfg.time_window.end_time_minutes//60:02d}:"
              f"{cfg.time_window.end_time_minutes%60:02d} "
              f"({service_min} min)")
    print(f"  max_duration per vehicle: {(cfg.time_window.end_time_minutes - cfg.time_window.start_time_minutes)} min → multi-trip handled natively by PyVRP")
    print(f"  Per-vehicle cost matrices: ✓ (mode={cfg.penalty_mode}, scale={cfg.preference_scale_m}m)")
    print(f"  Per-vehicle duration matrices: ✓ (speed-correct time windows)")

    # ── 7. Solve ───────────────────────────────────────────────────────
    print(f"\n{'─'*40}\n  SOLVING (HGS)\n{'─'*40}")
    n_clients = len(commuters)
    no_improve = max(10_000, n_clients * 50)
    result = solve(model, cfg.time_limit_seconds,
                   no_improve_iters=no_improve,
                   skip_penalty=2_000_000,
                   seed=solver_seed)

    print(f"\n{'─'*40}\n  EXTRACTING RESULTS\n{'─'*40}")
    # Build raw mm sub-matrix for metrics (distances in mm for VMT/fuel/CO2)
    matrix_rows_full = [station_idx] + [node_to_idx[c.origin_node] for c in commuters]
    idx_arr2 = np.array(matrix_rows_full, dtype=np.intp)
    raw_dist_mm_sub = dist_mm_raw[np.ix_(idx_arr2, idx_arr2)]

    # ── Distance reconciliation note ───────────────────────────────────
    # PyVRP's solution.distance() reports the SUM OF PENALISED ARC COSTS
    # in metres — the quantity the solver actually minimised. This includes
    # the smooth distance-band penalty multiplier per vehicle type, so it
    # is NOT physical road distance.
    #
    # Our extracted VMT uses raw road distances (dist_mm_raw ÷ 1e6 = km),
    # which is the physically meaningful metric for emissions and fuel.
    # These two numbers will differ whenever penalties are active.
    #
    # The ratio (solver_distance / extracted_vmt_m) is the effective
    # average penalty multiplier across all arcs in the solution.
    solver_dist_m = result.best.distance()
    print(f"  Solver objective distance: {solver_dist_m/1000:.2f} km "
          f"(penalised cost, vehicle-type weighted)")
    print(f"  Physical VMT will be computed from raw road distances below")

    metrics = extract_results(
        result, commuters, feasible_idx, window_assignment, windows_sec,
        cfg, raw_dist_mm_sub, cost_matrices,
        station_node, assignments_csv, av_routes_csv,
        original_count=original_count
    )

    # ── 9. Print summary ───────────────────────────────────────────────
    print(f"\n╔{banner}╗")
    print( "║  RESULTS                                                         ║")
    print(f"╚{banner}╝")
    print(f"\n  Served:                {metrics['served_commuters']}/{metrics['total_commuters']}"
          f"  ({metrics['service_rate']:.1f}%)")
    print(f"  On-time arrivals:      {metrics['on_time_deliveries']}/{metrics['served_commuters']}"
          f"  ({metrics['on_time_rate']:.1f}%)")
    print(f"  Late arrivals:         {metrics['late_deliveries']}"
          + (" ⚠" if metrics['late_deliveries'] > 0 else " ✓"))
    print(f"  Vehicles used:         {metrics['vehicles_used']}")
    print(f"  Vehicle trips:         {metrics['vehicle_trips']}")
    print(f"  Solo / Shared trips:   {metrics['solo_trips']} / {metrics['shared_trips']}")
    print(f"  Avg pax per trip:      {metrics['avg_passengers_per_trip']:.2f}")
    print(f"  Total VMT:             {metrics['total_vmt_km']:.2f} km")
    print(f"  Empty VMT:             {metrics['empty_vmt_km']:.2f} km "
          f"({metrics['empty_vmt_ratio']*100:.1f}%)")
    print(f"  Total fuel:            {metrics['total_fuel_liters']:.2f} L")
    print(f"  Total CO₂:             {metrics['total_co2_kg']:.2f} kg")
    print(f"  Avg in-vehicle time:   {metrics['avg_in_vehicle_time_min']:.1f} min"
          f"  (max {metrics['max_in_vehicle_time_min']:.1f} min,"
          f"  n={metrics['n_in_vehicle_time_samples']})")
    print(f"  Avg detour ratio:      {metrics['avg_detour_ratio']:.3f}"
          f"  (max {metrics['max_detour_ratio']:.3f},"
          f"  n={metrics['n_detour_ratio_samples']})")
    print(f"\n  By vehicle type:")
    for vtype, pt in metrics["per_vehicle_type"].items():
        if pt["vehicle_trips"] > 0:
            print(f"    {vtype:8s}: {pt['served_commuters']:4d} pax, "
                  f"{pt['vehicle_trips']:3d} trips, "
                  f"{pt['vmt_km']:.1f} km VMT")

    with open(metrics_json, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\n  ✓ Metrics written: {metrics_json}")

    # ── 10. Comparison ─────────────────────────────────────────────────
    comp = compare(metrics, baseline, cfg.experiment_name, solver_seed, cfg)
    with open(comparison_json, "w") as f:
        json.dump(comp, f, indent=2)
    print(f"  ✓ Comparison written: {comparison_json}")

    print(f"\n╔{banner}╗")
    print( "║  SIMULATION COMPLETE                                             ║")
    print(f"╚{banner}╝")
    print(f"\n  1. Baseline:    {baseline_json}")
    print(f"  2. Metrics:     {metrics_json}")
    print(f"  3. Comparison:  {comparison_json}")
    print(f"  4. Routes:      {av_routes_csv}")
    print(f"  5. Assignments: {assignments_csv}")
    print("\n✅ Done!\n")


if __name__ == "__main__":
    main()