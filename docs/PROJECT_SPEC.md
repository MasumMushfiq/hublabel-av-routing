# PROJECT_SPEC.md

# Heterogeneous Electric AV Feeder Simulation Project Specification

**Status:** Living project specification  
**Primary implementation:** PyVRP-based first-mile autonomous feeder simulation  
**Main case study:** Melton Station, Melbourne  
**Active model:** all-electric vehicles  
**Last major model update:** all-electric energy, emissions, and cost evaluation

This document is the single source of truth for the current simulation pipeline, metric definitions, modeling assumptions, and validation rules. Any future implementation that changes the pipeline, metric semantics, configuration schema, experiment defaults, or output fields should update this specification in the same commit.

---

## 1. Project Purpose and Scope

This project evaluates heterogeneous autonomous vehicle (AV) fleets for first-mile access to train stations. The current system simulates morning-peak commuters traveling from sampled origins to a railway station using a fleet of electric AVs.

The main research focus is to compare fleet designs under consistent demand and network conditions. Fleet designs are evaluated using service, travel distance, energy use, emissions, parking demand, and AV fleet operating cost.

The current implementation is not a full traffic simulation. It is a routing and evaluation pipeline using PyVRP/HGS over a road-network distance and duration matrix.

---

## 2. Current Case Study and Demand Setting

The current main case study is **Melton Station, Melbourne**.

Current demand assumptions:

- Morning peak period: `07:00–09:30`.
- Total current demand: `1465` commuters.
- Temporal demand is derived from Myki train tap-on records.
- Myki provides station arrival/tap-on timing, not home locations.
- Current commuter origins are sampled from reachable road-network nodes.
- Residential-origin candidate preprocessing is implemented using inferred OSM residential/address candidates mapped to existing road-network nodes.

Important limitation:

> Current origins should not be described as observed home addresses. Myki does not provide home locations; residential-origin runs use inferred OSM residential/address candidate road nodes paired with Myki-derived time deadlines.

---

## 3. Demand-Generation Pipeline

The current Myki commuter-generation pipeline is implemented in:

```text
python/build_myki_commuters.py
```

The current pipeline is:

```text
Myki ScanOnTransaction records
    ↓
extract train tap-ons for selected station and date
    ↓
retain one tap-on per card/day
    ↓
optionally preprocess OSM residential/address candidates into road-network candidate nodes
    ↓
call C++ reachable-origin sampler
    ↓
sample reachable origin nodes from the supplied candidate pool
    ↓
pair sampled origins with Myki deadlines using a seed-controlled random pairing
    ↓
apply haversine feasibility filter
    ↓
write commuters.csv
    ↓
write commuters_metadata.json
```

Current key inputs:

```text
--myki-root
--nodes-file
--coord-nodes-file
--dest-node
--cpp-bin
--labels
--out
--config
--year
--week
--date
--pickup-buffer
--av-speed-kmh
--seed
--origin-sampling farthest|random
--metadata-out
```

`--nodes-file` is the origin candidate pool passed to `build_commuters_reachable`. For residential-origin runs this is typically `files/inputs/melton_residential_candidate_nodes.csv`. `--coord-nodes-file` is the full node-coordinate lookup used only for distance-aware pairing and the haversine feasibility filter; if omitted, it defaults to `--nodes-file` for backward compatibility.

Current metadata should record:

- station/source information,
- destination node,
- Myki root,
- nodes file,
- coordinate lookup nodes file,
- C++ binary,
- labels,
- config file,
- year/week/date,
- peak start/end,
- pickup buffer,
- AV speed for feasibility filtering,
- random seed,
- origin sampling method,
- tap-ons extracted,
- reachable origins generated,
- commuters written,
- current origin-generation method.

Current origin-generation modes:

- `farthest`: spatially spread road-network candidate ordering.
- `random`: random candidate ordering. This is preferred for residential candidate pools because it better preserves candidate-density effects.

### 3.1 C++ Reachable-Origin Sampler

The reachable-origin sampler is implemented in:

```text
build_commuters_reachable.cpp
```

It is used by the Myki commuter-generation pipeline to generate candidate commuter origins that are feasible on the road network. The sampler:

- reads candidate nodes from the supplied node CSV;
- removes the destination/station node from the candidate pool unless `--allow-dest-as-origin` is explicitly passed;
- orders candidates using `--sampling farthest` or `--sampling random`;
- validates bidirectional reachability for each candidate:
  - origin → station, representing the commuter travel direction;
  - station → origin, representing vehicle dispatch from the station/depot to pickup;
- writes only reachable origins to the output commuter CSV.

Supported sampling modes:

```text
--sampling farthest
--sampling random
```

Interpretation:

- `farthest` uses greedy farthest-point ordering to spread origins spatially across the candidate pool.
- `random` shuffles candidate order using the seed. This is preferred for residential/address candidate pools because it better preserves candidate-density effects.

Important:

> The sampler validates reachability, but it does not currently know whether a candidate is a residential address. Residential realism depends on the candidate pool supplied to the sampler.


### 3.2 Residential-Origin Candidate Preprocessing

Residential-origin candidate preprocessing is implemented in:

```text
python/build_residential_origin_candidates.py
```

The preprocessing reads:

```text
dataset/OSM_DATA/melton_osm.pbf
files/inputs/melton_nodes_lat_lon.csv
```

It:

```text
OSM/address/building residential candidates
    ↓
map candidates to nearest road nodes
    ↓
remove candidates within the walking threshold of Melton Station
    ↓
write residential candidate points, node mappings, unique node pool, and metadata
```

The current default walking threshold is `800 m` direct haversine distance from Melton Station. It is not pedestrian-network walking distance.

Generated residential candidate files:

```text
files/inputs/melton_residential_candidate_points.csv
files/inputs/melton_residential_candidate_node_mapping.csv
files/inputs/melton_residential_candidate_nodes.csv
files/inputs/melton_residential_candidates_metadata.json
```

The resulting candidate node file can be passed to `python/build_myki_commuters.py` as:

```text
--nodes-file files/inputs/melton_residential_candidate_nodes.csv
--coord-nodes-file files/inputs/melton_nodes_lat_lon.csv
--origin-sampling random
```

`build_commuters_reachable` still performs bidirectional reachability validation after residential candidate preprocessing.

---

## 4. Vehicle Model

The current active fleet has four electric AV vehicle types.

| Vehicle type | Capacity | Max speed | Energy rate |
|---|---:|---:|---:|
| Scooter | 1 | 25 km/h | 0.016 kWh/km |
| Moped | 2 | 45 km/h | 0.058 kWh/km |
| Car | 4 | 80 km/h | 0.155 kWh/km |
| Minibus | 8 | 70 km/h | 0.330 kWh/km |

The canonical balanced reference fleet has **224 seats**:

| Vehicle type | Fleet size | Seats |
|---|---:|---:|
| Scooter | 56 | 56 |
| Moped | 28 | 56 |
| Car | 14 | 56 |
| Minibus | 7 | 56 |
| **Total** | **105 vehicles** | **224 seats** |

The 224-seat fleet is used because it allows exact 25% seat-share increments across the four vehicle types.

---

## 5. Canonical Configuration

The current canonical config is:

```text
config/base_config.json
```

Experiment runners should copy this config and modify only experiment-specific fields such as:

- `experiment_name`,
- `composition_metadata`,
- fleet sizes,
- solver time limit if overridden by the runner.

Shared assumptions should remain in `base_config.json`, including:

- vehicle capacities,
- speeds,
- energy rates,
- private-car baseline,
- energy model,
- time-window configuration,
- penalty mode,
- cost model.

---

## 6. Time-Window Model

Current default time-window setting:

```text
mode: fixed_slots
interval_minutes: 20
start_time_minutes: 420   # 07:00
end_time_minutes: 570     # 09:30
buffer_before_deadline_minutes: 0
```

Interpretation:

- Each commuter has a station-arrival deadline derived from Myki tap-on timing and train-aligned assignment.
- The solver uses pickup-time windows because PyVRP cannot directly enforce per-passenger station-arrival deadlines inside pooled trips.
- Final station-arrival feasibility is audited after route extraction.

---

## 7. Solver Versus Evaluation Distinction

The solver constructs AV routes. The final evaluation is performed after solution extraction.

The PyVRP solver:

- assigns commuters to AV routes,
- supports multi-trip routes through vehicle duration constraints,
- uses vehicle-specific duration matrices,
- does not directly enforce final station-arrival deadlines for each passenger after pooled detours.

The evaluation step:

- reconstructs trip timing,
- checks each commuter against the original station-arrival deadline,
- prunes late commuters from AV service,
- recomputes route metrics for remaining on-time riders,
- assigns late or unserved commuters to fallback private cars.

This distinction is critical:

> Raw solver assignment is not the same as final AV service. Final reported service means on-time AV service after pruning.

---

## 8. Late-Commuter Pruning

Late arrivals are handled by iterative post-processing, not by re-running the solver.

For each station-to-station trip segment:

1. Recompute pickup and station-arrival timing for the trip.
2. Identify commuters who would arrive after their station deadline.
3. Remove one late commuter at a time, using a tightest-deadline/late-removal policy.
4. Recompute timing after each removal.
5. Stop when all remaining commuters are on time or the trip becomes empty.

The original pickup order is preserved. The pruned route is an adjusted evaluation route, not a newly optimized route.

Paper-safe wording:

> After solution extraction, late arrivals are treated as fallback private-car users, and AV route metrics are recomputed for the remaining on-time riders using the original pickup order.

Avoid saying:

> The solver produced the final pruned route.

---

## 9. Core Commuter Count Definitions

Let:

```text
total_commuters = all commuters in the original demand file
```

Definitions:

```text
served_commuters
    Commuters served on time by AV after late-arrival pruning.

late_deliveries
    Solver-assigned commuters removed from AV service because they would arrive after their station deadline.

unserved_commuters
    Commuters not served by the solver, or filtered before solving due to reachability/time-window infeasibility.

fallback_private_cars
    late_deliveries + unserved_commuters

service_rate
    served_commuters / total_commuters × 100
```

Important:

- `served_commuters` means successful on-time AV service.
- `late_deliveries` are not counted as served.
- `fallback_private_cars` are treated as private-car trips to the station.
- `on_time_rate` is generally 100% after pruning because all kept AV riders are on time by construction. The primary service metric is `service_rate`.

Required identity:

```text
served_commuters + fallback_private_cars = total_commuters
fallback_private_cars = late_deliveries + unserved_commuters
```

---

## 10. Metric Layers

The evaluation separates metrics into four layers.

### 10.1 Raw solver metrics

Prefix:

```text
raw_solver_*
raw_av_*
```

Meaning:

- what the solver initially assigned or routed before late-comer pruning;
- useful for diagnostics;
- not the primary final system result.

Examples:

```text
raw_solver_assigned_commuters
raw_solver_unserved_commuters
raw_solver_late_deliveries
raw_av_total_vmt_km
raw_av_total_energy_kwh
raw_av_total_co2_kg
raw_vehicle_trips
raw_avg_passengers_per_trip
```

### 10.2 Adjusted AV-only metrics

Prefix:

```text
adjusted_av_*
```

Compatibility aliases:

```text
total_vmt_km
total_energy_kwh
total_co2_kg
```

Meaning:

- AV fleet metrics after pruning late commuters;
- fallback private cars are not included;
- these describe only the successful AV portion.

Examples:

```text
adjusted_av_total_vmt_km
adjusted_av_total_energy_kwh
adjusted_av_total_co2_kg
total_vmt_km
total_energy_kwh
total_co2_kg
```

Important:

> In the current implementation, `total_*` means adjusted AV-only, not system-wide.

### 10.3 Fallback private-car metrics

Prefix:

```text
fallback_private_car_*
```

Meaning:

- metrics for commuters not successfully served by AV;
- includes both late and unserved commuters.

Examples:

```text
fallback_private_car_vmt_km
fallback_private_car_energy_kwh
fallback_private_car_co2_kg
fallback_private_car_energy_cost
fallback_private_car_avg_trip_km
fallback_private_car_share_pct
```

### 10.4 System metrics

Prefix:

```text
system_*
```

Meaning:

- adjusted AV metrics plus fallback private-car metrics;
- these are the primary paper metrics for total mobility-system comparison.

Examples:

```text
system_total_vmt_km
system_total_energy_kwh
system_total_co2_kg
system_energy_cost
system_vmt_change_pct
system_energy_change_pct
system_co2_change_pct
```

---

## 11. Electric Energy and Emissions Model

The active model is all-electric.

All of the following are modeled as electric:

- AV scooter,
- AV moped,
- AV car,
- AV minibus,
- fallback private car,
- private-car baseline.

There is no active petrol/diesel model in the main pipeline.

Global parameters:

```text
electricity_cost_per_kwh = 0.27 AUD/kWh
grid_co2_kg_per_kwh = 0.78 kg CO2-e/kWh
```

Private-car baseline/fallback:

```text
private_car_energy_kwh_per_km = 0.155
```

Core formulas:

```text
energy_kwh = distance_km × energy_kwh_per_km
co2_kg = energy_kwh × grid_co2_kg_per_kwh
energy_cost = energy_kwh × electricity_cost_per_kwh
```

Baseline:

```text
baseline_total_energy_kwh =
    baseline_total_vmt_km × private_car_energy_kwh_per_km

baseline_total_co2_kg =
    baseline_total_energy_kwh × grid_co2_kg_per_kwh

baseline_energy_cost =
    baseline_total_energy_kwh × electricity_cost_per_kwh
```

Fallback:

```text
fallback_private_car_energy_kwh =
    fallback_private_car_vmt_km × private_car_energy_kwh_per_km

fallback_private_car_co2_kg =
    fallback_private_car_energy_kwh × grid_co2_kg_per_kwh

fallback_private_car_energy_cost =
    fallback_private_car_energy_kwh × electricity_cost_per_kwh
```

System:

```text
system_total_energy_kwh =
    adjusted_av_total_energy_kwh + fallback_private_car_energy_kwh

system_total_co2_kg =
    adjusted_av_total_co2_kg + fallback_private_car_co2_kg
```

No active output should use:

```text
fuel_l_per_100km
co2_kg_per_liter
total_fuel_liters
fuel_change_pct
system_fuel_change_pct
av_fuel_cost
fuel_liters
fuel_cost
```

---

## 12. Private-Car Baseline

The private-car baseline represents every commuter driving directly from their origin to the station in an electric private car.

Baseline distance:

```text
baseline_total_vmt_km =
    sum of direct origin-to-station shortest-path distance for all feasible commuters
```

Baseline energy and emissions use the electric private-car parameters.

The baseline is not a parking search model or congestion model. It is a direct-drive access benchmark.

---

## 13. Parking Model

Parking metrics are computed after fallback assignment.

Baseline commuter parking:

```text
baseline_parking_spaces = total_commuters
```

Station commuter parking under AV system:

```text
station_commuter_parking_spaces = fallback_private_cars
```

Station parking reduction:

```text
station_parking_reduction_pct =
    100 × (1 - station_commuter_parking_spaces / baseline_parking_spaces)
```

Fleet storage uses configured fleet size, not only used vehicles:

| Vehicle type | Car-space equivalent |
|---|---:|
| Scooter | 0.25 |
| Moped | 0.50 |
| Car | 1.00 |
| Minibus | 2.00 |

Fleet storage:

```text
fleet_storage_equiv_spaces =
    Σ configured fleet_size(vehicle type) × parking_equivalent(vehicle type)
```

Net station parking if the fleet is stored at the station:

```text
net_parking_equiv_if_fleet_stored_at_station =
    station_commuter_parking_spaces + fleet_storage_equiv_spaces

net_parking_reduction_pct_if_fleet_stored_at_station =
    100 × (1 - net_parking_equiv_if_fleet_stored_at_station / baseline_parking_spaces)
```

Interpretation:

- `station_commuter_parking_spaces` is the active commuter parking demand.
- `fleet_storage_equiv_spaces` is a separate fleet-storage estimate.
- The combined net metric is optional and should be explained carefully.

---

## 14. AV Fleet Cost Model

The cost model is evaluation-only. It does not affect the solver objective or route construction.

The current AV fleet cost includes:

```text
fixed fleet cost
distance-based operating/maintenance cost
electric energy cost
```

Cost model inputs are in:

```text
config/base_config.json
```

Current base cost assumptions:

| Vehicle type | Fixed cost | Maintenance cost |
|---|---:|---:|
| Scooter | 8.0 | 0.05/km |
| Moped | 15.0 | 0.08/km |
| Car | 40.0 | 0.18/km |
| Minibus | 80.0 | 0.25/km |

To confirm before paper finalization:

> The current monetary values are placeholders for comparative evaluation and should be refined or justified before final submission.

Definitions:

```text
av_fleet_fixed_cost =
    Σ configured fleet_size(vehicle type) × fixed_cost_per_vehicle(vehicle type)

av_distance_operating_cost =
    Σ adjusted_av_vmt_km(vehicle type) × maintenance_cost_per_km(vehicle type)

av_energy_cost =
    Σ adjusted_av_energy_kwh(vehicle type) × electricity_cost_per_kwh

av_total_operating_cost =
    av_fleet_fixed_cost + av_distance_operating_cost + av_energy_cost
```

Important:

- AV fleet cost excludes fallback private-car energy/cost.
- Fallback private-car energy cost may be stored in metrics but is not part of `av_total_operating_cost`.
- Fixed cost uses configured fleet size, not used vehicles.

Cost outputs include:

```text
av_fleet_fixed_cost
av_distance_operating_cost
av_energy_cost
av_total_operating_cost
av_cost_per_commuter_total
av_cost_per_served_commuter
av_cost_per_passenger_km
av_cost_per_vehicle_km
av_cost_by_vehicle_type
```

---

## 15. Default Experiment Settings

Current default settings from `config/base_config.json`:

```text
solver: PyVRP/HGS
time_limit_seconds: 180
time_window.mode: fixed_slots
time_window.interval_minutes: 20
time_window.start_time_minutes: 420
time_window.end_time_minutes: 570
buffer_before_deadline_minutes: 0
penalty_mode: none
alpha: 1.0
beta: 1.0
preference_scale_m: 500
```

Current standard final experiment plan:

```text
seeds: 15
fleet capacity: 224 seats
fleet composition grid: 25% seat-share increments across four vehicle types
```

The fleet composition grid contains all combinations where:

```text
scooter_share + moped_share + car_share + minibus_share = 100
share ∈ {0, 25, 50, 75, 100}
```

This gives 35 fleet compositions.

---

## 16. Fleet-Composition Runner

The fleet-composition runner is:

```text
experiments/scripts/run_fleet_composition_grid.sh
```

Purpose:

- enumerate 35 fleet compositions;
- keep total seat capacity fixed at 224;
- generate one config per composition;
- run each composition for `N_SEEDS`;
- support `LABELS_OVERRIDE` for selected conditions;
- support `TIME_LIMIT_SECONDS`, `PARALLEL_JOBS`, `CONFIG_ONLY`, and `OUTPUT_DIR`.

Important design:

- The runner uses `config/base_config.json` as the canonical template.
- It should preserve shared fields such as `time_window`, `energy_model`, `baseline_parameters`, `penalty_parameters`, and `cost_model`.
- It should modify only experiment-specific fleet composition and metadata.

Common smoke-test pattern:

```bash
OUTPUT_DIR=experiments/test_results/electric_fleet_composition_224seats \
TIME_LIMIT_SECONDS=60 \
N_SEEDS=1 \
LABELS_OVERRIDE="comp_S25_M25_C25_MB25 comp_S25_M25_C0_MB50 comp_S25_M50_C0_MB25 comp_S100_M0_C0_MB0 comp_S0_M100_C0_MB0 comp_S0_M0_C100_MB0 comp_S0_M0_C0_MB100" \
PARALLEL_JOBS=7 \
bash experiments/scripts/run_fleet_composition_grid.sh
```

---


## 17. Matrix Generation Pipeline

The distance and duration matrix generator is implemented in:

```text
dump_distance_matrix.cpp
```

Purpose:

- read a commuter node list;
- create a matrix node order with the station/depot first, followed by commuter origin nodes;
- query all-pairs road-network shortest-path distances using hub labels;
- write a raw distance matrix in millimetres;
- write vehicle-specific duration matrices in milliseconds;
- write the matrix node-order file.

Generated files include:

```text
distances.npy
duration_25kmph.npy
duration_30kmph.npy
duration_45kmph.npy
duration_70kmph.npy
duration_80kmph.npy
nodes.txt
```

Duration calculation:

- each shortest path is converted to travel time using the speed table;
- effective edge speed is capped by the vehicle maximum speed;
- missing edge-speed information receives a large penalty;
- unreachable pairs receive large sentinel distance/duration values.

Current active vehicle speeds are:

| Vehicle | Speed | Duration matrix |
|---|---:|---|
| Scooter | 25 km/h | `duration_25kmph.npy` |
| Moped | 45 km/h | `duration_45kmph.npy` |
| Minibus | 70 km/h | `duration_70kmph.npy` |
| Car | 80 km/h | `duration_80kmph.npy` |

The generator may also write `duration_30kmph.npy` for legacy compatibility. The active scooter speed in the current base configuration is 25 km/h.

Important:

> Distance matrices are physical road distances. Duration matrices are vehicle-speed-specific travel times. Energy, emissions, and VMT calculations should use physical distance, not penalized solver cost.

---

## 18. Main Code Structure

Core files:

```text
config/base_config.json
    Canonical active experiment configuration.

config/energy_assumptions_reference.md
    Source-trace file for electric energy, emissions, and cost assumptions.

python/simulate_first_mile_pyvrp.py
    Main PyVRP simulation, solution extraction, pruning, metrics, and output writing.

python/simulate_first_mile_utils.py
    Dataclasses and pure helper functions for testing:
    time windows, pruning helpers, baseline, compare, parking, cost, cost matrix.

python/build_myki_commuters.py
    Myki-based commuter CSV generation and metadata writing.

python/build_residential_origin_candidates.py
    OSM residential/address candidate extraction, nearest road-node mapping, walking-threshold filtering, and candidate metadata writing.

python/tests/test_simulate_utils.py
    Unit tests for core utility behavior and metric formulas.

experiments/scripts/run_fleet_composition_grid.sh
    Fleet-composition experiment runner.

build_commuters_reachable.cpp
    C++ reachable-origin sampler used by the Myki commuter-generation pipeline.

dump_distance_matrix.cpp
    C++ distance and vehicle-specific duration matrix generator.

Makefile
    Convenience targets for building binaries, generating commuters, matrices, and running PyVRP.
```

Generated outputs:

```text
assignments.csv
av_routes.csv
baseline.json
metrics.json
comparison.json
simulation.log
commuters.csv
commuters_metadata.json
melton_residential_candidate_points.csv
melton_residential_candidate_node_mapping.csv
melton_residential_candidate_nodes.csv
melton_residential_candidates_metadata.json
```

Do not normally commit:

```text
experiments/test_results/
experiments/results/
results/
large datasets
matrix files
local logs
.DS_Store
__pycache__
```

---

## 19. Output Files

### assignments.csv

Should contain one row per original commuter.

Expected statuses:

```text
ASSIGNED
PRUNED_LATE
UNSERVED
```

Interpretation:

- `ASSIGNED`: served on time by AV after pruning.
- `PRUNED_LATE`: solver-assigned but removed due to late station arrival.
- `UNSERVED`: not served by solver or filtered before solving.

Required count:

```text
len(assignments.csv rows) = total_commuters
```

### av_routes.csv

Represents adjusted/pruned AV routes, not raw solver routes.

Expected:

```text
len(av_routes.csv rows) = vehicle_trips
```

### baseline.json

Private-car baseline metrics.

### metrics.json

Full run metrics, including raw, adjusted AV, fallback, system, parking, cost, and per-vehicle-type details.

### comparison.json

Compact comparison metrics against the private-car baseline.

---

## 20. Validation Invariants

Every smoke test or final experiment should satisfy:

```text
served_commuters + fallback_private_cars = total_commuters
fallback_private_cars = unserved_commuters + late_deliveries
fallback_private_cars = count(PRUNED_LATE) + count(UNSERVED)
len(assignments.csv rows) = total_commuters
len(av_routes.csv rows) = vehicle_trips
```

Energy and emissions:

```text
total_energy_kwh = adjusted_av_total_energy_kwh

system_total_energy_kwh =
    adjusted_av_total_energy_kwh + fallback_private_car_energy_kwh

total_co2_kg = adjusted_av_total_co2_kg

system_total_co2_kg =
    adjusted_av_total_co2_kg + fallback_private_car_co2_kg

fallback_private_car_co2_kg =
    fallback_private_car_energy_kwh × grid_co2_kg_per_kwh
```

Comparison:

```text
energy_change_pct =
    100 × (total_energy_kwh - baseline_total_energy_kwh) / baseline_total_energy_kwh

system_energy_change_pct =
    100 × (system_total_energy_kwh - baseline_total_energy_kwh) / baseline_total_energy_kwh

co2_change_pct =
    100 × (total_co2_kg - baseline_total_co2_kg) / baseline_total_co2_kg

system_co2_change_pct =
    100 × (system_total_co2_kg - baseline_total_co2_kg) / baseline_total_co2_kg
```

Fuel check:

```text
No active metrics.json or comparison.json field should contain "fuel".
```

Parking:

```text
baseline_parking_spaces = total_commuters
station_commuter_parking_spaces = fallback_private_cars
```

Cost:

```text
av_total_operating_cost =
    av_fleet_fixed_cost + av_distance_operating_cost + av_energy_cost

fallback_private_car_energy_cost is not included in av_total_operating_cost
```

---

## 21. Things That Must Not Change Without Updating This Spec

Update this spec if changing any of the following:

- vehicle types, capacities, speeds, or energy rates;
- private-car baseline assumptions;
- grid emission factor or electricity price;
- cost model formula or cost fields;
- service-rate definition;
- late-pruning algorithm;
- meaning of `total_*`, `adjusted_av_*`, `fallback_*`, or `system_*`;
- commuter-origin generation method;
- Myki filtering or date/station selection;
- default time-window settings;
- default solver time limit or seed count;
- parking equivalence assumptions;
- output field names;
- runner behavior or generated config structure.

---

## 22. Spec Maintenance Policy

This is a living specification.

Rules:

1. Update this file in the same commit as any implementation that changes definitions, assumptions, formulas, outputs, or pipeline steps.
2. Do not allow AI tools to reinterpret metrics independently of this file.
3. Before giving a coding task to ChatGPT, Codex, Claude Code, or another assistant, provide this spec or the relevant excerpt.
4. If a new task conflicts with this spec, resolve the modeling decision first, then update the spec, then update the code.
5. If a value is uncertain, mark it as `to confirm` rather than silently encoding it as final.
6. Keep this spec concise enough to be read before implementation work.

---

## 23. Standard Prompt for Future AI Coding Tasks

Use this pattern when assigning future implementation tasks:

```text
Please follow docs/PROJECT_SPEC.md as the source of truth. Do not change metric definitions, modeling assumptions, output field meanings, or experiment defaults unless explicitly requested. 
If the requested change conflicts with the spec, stop and report the conflict before editing code. Update docs/PROJECT_SPEC.md if your implementation changes any documented assumption, formula, field, or pipeline step.
```

---

## 24. Current Near-Term Roadmap

Immediate next work:

1. Create and validate this project specification. --> Looks good
2. Validate residential address/building candidate demand generation in experiments.
3. Update AV fleet cost assumptions with cited real-world values.
4. Update runners and plotting scripts one by one for the new energy metrics.
5. Select additional station case studies.
6. Rerun key experiments with the corrected evaluation and all-electric model.
7. Share updated outputs with supervisors before the next meeting.
