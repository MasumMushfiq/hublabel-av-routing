# PROJECT_SPEC.md

# Heterogeneous Electric AV Feeder Simulation Project Specification

**Status:** Living project specification  
**Primary implementation:** PyVRP-based first-mile autonomous feeder simulation  
**Main case study:** Footscray Railway Station, Melbourne
**Active model:** all-electric vehicles  
**Last major model update:** refined all-electric energy, emissions, cost, and parking evaluation

This document is the single source of truth for the current simulation pipeline, metric definitions, modeling assumptions, and validation rules. Any future implementation that changes the pipeline, metric semantics, configuration schema, experiment defaults, or output fields should update this specification in the same commit.

---

## 1. Project Purpose and Scope

This project evaluates heterogeneous autonomous vehicle (AV) fleets for first-mile access to train stations. The current system simulates morning-peak commuters traveling from sampled origins to a railway station using a fleet of electric AVs.

The main research focus is to compare fleet designs under consistent demand and network conditions. Fleet designs are evaluated using service, travel distance, energy use, emissions, parking demand, and AV fleet operating cost.

The current implementation is not a full traffic simulation. It is a routing and evaluation pipeline using PyVRP/HGS over a road-network distance and duration matrix.

The refined all-electric energy, emissions, cost, and parking evaluation model is now active. Cost and parking are evaluation-only layers and do not affect routing.

---

## Why autonomous fleets?

This study assumes autonomous fleets because first-mile feeder service requires coordinated routing, dispatch, and repositioning around train-aligned demand. Driver-based ride-hailing or taxi systems cannot be directly controlled by a public agency; drivers can only be incentivized to move to certain areas.

AV fleets can be centrally managed to match train-aligned demand and to serve low-density or underserved areas when required. Removing human drivers also removes driver-labor constraints and may reduce future operating costs, but cost remains evaluation-only in this project and does not affect routing.

Autonomous scooters, bikes, and mopeds are conceptually different from current shared micromobility because they can be dispatched to the commuter origin and repositioned after use. They do not require users to walk to a dock or stand before pickup, and they do not require users to park the vehicle manually near the station.

---

## 2. Current Case Study and Demand Setting

The corrected main paper case study is **Footscray Railway Station, Melbourne**.

Current demand assumptions:

- Myki tap-on demand window: `07:00–09:30`.
- Vehicle service horizon: `06:30–09:30`, allowing pickups from `06:30` where commuter pickup windows permit them.
- Fixed station-arrival deadline slots: 20-minute slots from `07:00–09:30`.
- Main Myki date: `2018-03-15`.
- Footscray `DimStopLocation.StopLocationID`: `20025`.
- Corrected demand: `586` commuters from the station-level extraction.
- Temporal demand is derived from Myki train tap-on records.
- Myki provides station arrival/tap-on timing, not home locations.
- The main Footscray commuter-origin method uses inferred OSM residential/address candidates mapped to existing road-network nodes.
- Generic reachable road-network node sampling is retained only as a robustness/sensitivity comparison.

Archived Melton note:

- Melton was the previous experiment context.
- Melton demand/results generated using transaction column `7` are archived for reproducibility and must not be used as final paper results.
- Full Footscray PyVRP experiments, seed convergence, fleet-composition results, and capacity sensitivity are pending corrected reruns.

Important limitation:

> Current origins should not be described as observed home addresses. Myki does not provide home locations; residential-origin runs use inferred OSM residential/address candidate road nodes paired with Myki-derived time deadlines.

---

## 3. Demand-Generation Pipeline

The command-oriented reproducibility guide for the corrected Footscray workflow is:

```text
docs/FOOTSCRAY_PIPELINE.md
```

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
preprocess OSM residential/address candidates into road-network candidate nodes
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
--station-name
--stop-ids
--stop-id-column 7|8
--pickup-buffer
--av-speed-kmh
--seed
--origin-sampling farthest|random
--metadata-out
```

`--station-name` is a metadata label for the selected station. The active paper demand should set it to `Footscray`.

`--stop-ids` is a comma-separated list of station/location identifier values used to select station tap-ons from the column chosen by `--stop-id-column`. The corrected Footscray demand uses:

```text
20025
```

`--stop-id-column` selects the zero-based `ScanOnTransaction` column used for station filtering:

- column `8` contains the station-specific `DimStopLocation.StopLocationID` values from `stop_locations.txt` and must be used for station-level paper demand;
- column `7` remains supported only for archived/reproducibility checks and must not be used for station-level paper demand.

The corrected Footscray extraction must pass `--stop-id-column 8`, `--stop-ids 20025`, `--station-name Footscray`, and date `2018-03-15`.

The previous Melton extraction used column `7`; it is retained only as archived experiment context and is not valid station-level paper demand.

`--nodes-file` is the origin candidate pool passed to `build_commuters_reachable`. Main Footscray experiments should use `files/inputs/footscray_residential_candidate_nodes_3km.csv`. `--coord-nodes-file` is the full node-coordinate lookup used only for distance-aware pairing and the haversine feasibility filter; if omitted, it defaults to `--nodes-file` for backward compatibility.

Current metadata should record:

- station/source information,
- destination node,
- Myki station stop IDs used for tap-on filtering,
- selected ScanOnTransaction stop-ID column index and description,
- Myki extraction window and whether it came from `demand_window` or the legacy `time_window` fallback,
- AV service/routing horizon from `service_horizon` or the legacy `time_window` fallback,
- station-arrival deadline-slot span from `time_window`,
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

Generic reachable-node demand:

- samples from the broader road-node set rather than residential/address candidates;
- is useful for checking whether conclusions depend on origin-generation assumptions;
- should be reported, if used, as a robustness/sensitivity comparison rather than the main spatial-demand method.

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
dataset/OSM_DATA/footscray_osm.pbf
files/inputs/footscray_nodes_lat_lon.csv
```

The main Footscray spatial-demand pipeline is:

```text
Myki temporal demand
    +
OSM/address/building residential candidates
    ↓
map candidates to nearest road nodes
    ↓
retain candidates beyond walking distance and within the Footscray first-mile catchment
    ↓
write residential candidate points, node mappings, unique node pool, and metadata
    ↓
random sampling from residential candidate pool
    ↓
bidirectional reachability validation by build_commuters_reachable
    ↓
pair sampled origins with Myki tap-on deadlines
```

The full Footscray road network is retained for routing. Only the residential origin candidate pool is filtered.

The main Footscray candidate policy uses direct radial distance from Footscray Railway Station:

- lower bound: beyond walking distance, greater than `800 m`;
- upper bound: within a `3 km` radial first-mile catchment.

The `800 m` lower bound removes trips plausibly served on foot. The `3 km` outer bound avoids assigning riders from areas closer to neighbouring stations such as Middle Footscray, West Footscray, Seddon, Yarraville, Tottenham, Newport, Sunshine, or Albion.

The catchment filter is applied to extracted residential/address candidate points before mapping to the nearest road node. Therefore, final mapped road-node distances can differ slightly from the nominal `800 m` and `3 km` thresholds.

Main generated residential candidate file:

```text
files/inputs/footscray_residential_candidate_nodes_3km.csv
```

Footscray candidate-pool summary after filtering:

| Statistic | Value |
|---|---:|
| Candidate road nodes | 6,606 |
| Minimum distance | 0.77 km |
| 25th percentile | 1.71 km |
| Median | 2.21 km |
| 75th percentile | 2.63 km |
| 90th percentile | 2.85 km |
| 95th percentile | 2.93 km |
| 99th percentile | 3.00 km |
| Maximum distance | 3.05 km |
| Mean distance | 2.13 km |

The resulting candidate node file can be passed to `python/build_myki_commuters.py` as:

```text
--nodes-file files/inputs/footscray_residential_candidate_nodes_3km.csv
--coord-nodes-file files/inputs/footscray_nodes_lat_lon.csv
--origin-sampling random
```

`build_commuters_reachable` still performs bidirectional reachability validation after residential candidate preprocessing.

The `6,606`-row candidate pool is an intermediate sampling input with a `node_id` column. It must not be passed to `dump_distance_matrix`. The final matrix was built from `files/inputs/footscray_commuters_residential.csv`, which has `586` commuter rows and an `origin_node` column.

Validated final Footscray matrix properties:

| Check | Result |
|---|---:|
| Matrix shape | `587 x 587` |
| Matrix index 0 | station node `240615` |
| Matrix indices 1..586 | exact match to commuter origins, in CSV order |
| Duplicate commuter origins | `0` |

Validated network origin-to-station distances for the 586 commuters:

| Statistic | Distance / count |
|---|---:|
| Median | 3.21 km |
| 90th percentile | 4.34 km |
| 95th percentile | 4.86 km |
| 99th percentile | 7.28 km |
| Maximum | 8.20 km |
| Greater than 5 km | 22 / 586 |
| Greater than 8 km | 3 / 586 |
| Greater than 10 km | 0 / 586 |

### 3.3 Station-Generic Network Preparation

Station-generic OSM network preparation is implemented in:

```text
python/build_osm_network_inputs.py
```

The in-project OSM builder creates the station-specific road-network artifacts:

```text
files/inputs/<station>_nodes_lat_lon.csv
files/inputs/<station>_graph_speed.txt
files/inputs/<station>_graph_distance.txt
files/inputs/<station>_graph_time.txt
files/inputs/<station>_network_metadata.json
```

Current Footscray network:

```text
OSM extract: dataset/OSM_DATA/footscray_osm.pbf
station prefix: footscray
station road node: 240615
nearest station-node distance: 19.09 m
network nodes: 255,804
speed edges: 453,007
```

Archived Melton artifacts may be retained for reproducibility, but results generated from the column-7 Melton demand must not be used as final paper results.

Paper framing:

- Main results should use residential-origin demand.
- Generic reachable-node demand may be reported compactly as a robustness check if the qualitative fleet tradeoffs are similar.
- If generic-node and residential-origin results differ, residential-origin results should be treated as more defensible for the main analysis because they are spatially grounded in residential/address candidates.
- Corrected calibration and main Footscray experiments should use residential-origin demand as the primary demand input. Generic reachable-node demand is retained only as a robustness/sensitivity comparison.

---

## 4. Vehicle Model

The current active fleet has four electric AV vehicle types.

| Vehicle type | Capacity | Max speed | Energy rate |
|---|---:|---:|---:|
| Scooter | 1 | 25 km/h | 0.016 kWh/km |
| Moped | 2 | 45 km/h | 0.058 kWh/km |
| Car | 4 | 80 km/h | 0.155 kWh/km |
| Minibus | 8 in canonical base; 10 in Footscray reference | 70 km/h | 0.330 kWh/km |

The previous Melton experiments instantiated the balanced reference pattern as a **224-seat** fleet:

| Vehicle type | Fleet size | Seats |
|---|---:|---:|
| Scooter | 56 | 56 |
| Moped | 28 | 56 |
| Car | 14 | 56 |
| Minibus | 7 | 56 |
| **Total** | **105 vehicles** | **224 seats** |

This historical 224-seat realization allowed exact 25% seat-share increments across the four vehicle types. The Footscray balanced reference uses exactly 80 seats and exact 25% seat shares:

| Vehicle type | Fleet size | Capacity | Seats |
|---|---:|---:|---:|
| Scooter | 20 | 1 | 20 |
| Moped | 10 | 2 | 20 |
| Car | 5 | 4 | 20 |
| Minibus | 2 | 10 | 20 |
| **Total** | **37 vehicles** |  | **80 seats** |

Minibus capacity 10 is defined in the active Footscray reference config. The renamed `config/legacy_melton_base_config.json` retains the historical minibus capacity 8 for legacy Melton workflows.

---

## 5. Canonical Configuration

For end-to-end commands from raw inputs through smoke validation, see `docs/FOOTSCRAY_PIPELINE.md`.

The active corrected Footscray config is:

```text
config/footscray_base_config.json
```

The old generic/Melton-era config is retained explicitly as:

```text
config/legacy_melton_base_config.json
```

The corrected smoke workflow is reproducible with:

```bash
bash experiments/scripts/run_footscray_smoke.sh
```

This helper uses the final Footscray commuter CSV, station CSV, residential matrix, output directory `experiments/results/footscray/smoke_balanced_80seats_mb10_h0630_seed1`, and seed 1. It creates a temporary `config.json` in that output directory by copying `config/footscray_base_config.json` and changing only the experiment metadata and solver limit to 60 seconds. It does not rebuild demand or matrices.

The corrected Footscray residential matrix can be rebuilt explicitly with:

```bash
make footscray_dump_matrices
```

This target preserves the generic matrix targets and fixes the Footscray labels, final commuter CSV, station node, speed table, and matrix output paths. The matrix input is the final commuter CSV with `origin_node`, never the candidate pool with `node_id`.

Corrected Footscray experiment runners should copy `config/footscray_base_config.json` and modify only experiment-specific fields such as:

- `experiment_name`,
- `composition_metadata`,
- fleet sizes,
- solver time limit if overridden by the runner.

Shared active Footscray assumptions should remain in `config/footscray_base_config.json`, including:

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

Corrected Footscray time-window setting:

```text
demand_window.start_time_minutes: 420   # 07:00 Myki extraction
demand_window.end_time_minutes: 570     # 09:30
service_horizon.start_time_minutes: 390 # 06:30 vehicle operation
service_horizon.end_time_minutes: 570   # 09:30
time_window.mode: fixed_slots
time_window.interval_minutes: 20
time_window.start_time_minutes: 420     # 07:00 first deadline slot
time_window.end_time_minutes: 570       # 09:30
```

Interpretation:

- Each commuter has a station-arrival deadline derived from Myki tap-on timing and train-aligned assignment.
- The Myki tap-on demand window is `07:00–09:30`.
- `demand_window` controls Myki extraction, so no `06:30–07:00` Myki demand is generated.
- `service_horizon` controls vehicle operation and the 180-minute maximum route duration from `06:30–09:30`.
- `time_window` generates fixed 20-minute station-arrival slots beginning at `07:00`; it does not generate `06:30` or `06:50` slots.
- A commuter with a `07:01` station deadline may have `pickup_earliest = 06:31` but is assigned to the `07:00` deadline slot rather than `06:50`.
- The 30-minute pickup window is created during commuter generation; the active routing config does not add a separate deadline-relaxation parameter.
- Legacy configs without `service_horizon` use the `time_window` span as the service horizon.
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

There is no active combustion-engine model in the main pipeline.

Global parameters:

```text
electricity_cost_per_kwh = 0.27 AUD/kWh
grid_co2_kg_per_kwh = 0.78 kg CO2-e/kWh
```

Energy assumptions are documented in:

```text
docs/energy_assumptions_reference.md
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

Active Footscray cost model inputs are in:

```text
config/footscray_base_config.json
```

Cost assumptions are documented in:

```text
docs/cost_assumptions_reference.md
```

Current base evaluation-cost assumptions:

| Vehicle type | Fixed cost | Maintenance cost |
|---|---:|---:|
| Scooter | 1.98 AUD/vehicle/day | 0.06 AUD/km |
| Moped | 4.02 AUD/vehicle/day | 0.04 AUD/km |
| Car | 39.96 AUD/vehicle/day | 0.04 AUD/km |
| Minibus | 42.59 AUD/vehicle/day | 0.25 AUD/km |

Interpretation:

- These values are indicative evaluation inputs for relative fleet comparison.
- Costs are computed after routing and pruning; they are not part of route construction or the solver objective.
- The model excludes autonomy-stack premium, driver labour, depot/charging infrastructure, insurance, and remote supervision.
- Results should be interpreted as relative/indicative cost indicators, not as a full deployment business case.

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
- `cost_model.fixed_cost_per_vehicle` and `cost_model.maintenance_cost_per_km` are AUD evaluation fields.
- Legacy configs may contain `fleet.vehicle_types[].fixed_cost_km_equiv`, a solver-objective field. The active Footscray config omits it, which defaults to zero; real AUD costs remain evaluation-only and must not be placed in solver-objective fields.

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

## Results Metric Hierarchy and Presentation Plan

Primary paper metrics:

- service rate;
- system VMT reduction;
- system energy reduction;
- system CO2 reduction;
- fallback private cars where useful for unmet-service interpretation.

Secondary metrics:

- served commuters / supported commuters;
- AV operating cost per commuter or per served commuter;
- parking reduction / net parking reduction;
- pooling or vehicle-type assignment metrics only when explaining mechanisms.

Diagnostic-only metrics:

- late deliveries;
- unserved commuters separately, unless explaining fallback accounting;
- empty VMT ratio;
- detailed cost subcomponents;
- detailed parking subcomponents;
- AV-only VMT/energy/CO2 reductions when system metrics exist.

### Passenger Experience, Cost, and Parking Presentation

Average in-vehicle time is a secondary passenger-experience metric. It is most useful in the representative fleet comparison to check whether system VMT savings come with longer passenger travel times. Do not use in-vehicle time as a primary metric in every experiment.

Cost is evaluation-only and does not affect routing. Cost should be preserved in summary CSVs where available. The paper may report one compact cost metric, preferably AV operating cost per served commuter or AV operating cost per commuter. Detailed cost components should remain diagnostic.

Parking is evaluation-only and should be preserved in summary CSVs where available. The safest paper-facing parking metric is station commuter parking reduction. Net parking reduction if the fleet is stored at the station can be reported only as illustrative because it depends on fleet-storage assumptions.

Suggested placement:

- Fleet grid: no cost, parking, or in-vehicle time in the main figure.
- Representative comparison: include in-vehicle time and optionally one cost and one parking metric.
- Vehicle-type contribution: focus on served share, VMT share, and distance assignment.
- Capacity sensitivity: local sensitivity analysis around the verified station-specific reference capacity, not fleet-size optimization. The main paper-facing figure focuses on system VMT reduction and system CO2 reduction. Service rate and fallback private cars remain in summary CSVs and diagnostics, but they are not the main capacity figure. System metrics include adjusted AV routes plus fallback private-car trips. Generic-origin capacity results remain diagnostic/robustness only.
- Pilot demand sensitivity: fixed near-112-seat pilot-fleet stress test, not capacity scaling. The main paper-facing figure focuses on service rate and fallback private cars. Supported commuters are retained in summary CSVs and prose as needed. VMT/CO2 pilot plots are diagnostic only unless demand-matched baselines are confirmed. Cost and parking are not main pilot-section metrics unless needed for a separate application discussion.

Current experiment presentation plan:

1. Fleet-composition grid:
   - main figure: system VMT reduction vs system CO2 reduction, with representative fleets highlighted;
   - table: selected representative fleets with service rate, fallback private cars, system VMT reduction, and system CO2 reduction.
2. Representative fleet comparison:
   - compact table using the four selected representative fleets;
   - no large duplicate figure unless needed.
3. Vehicle-type contribution:
   - main mechanism analysis uses representative heterogeneous fleet share patterns at the verified station-specific reference capacity;
   - analyze vehicle-type served share, vehicle-type VMT share, and distance-bin assignment;
   - all-car is excluded from vehicle-type assignment plots because it has only one vehicle type;
   - pilot `x0.50` may be used only as an illustrative secondary mechanism check if it clarifies vehicle utilization;
   - scooter underuse in the archived 224-seat Melton setting should be treated as a previous empirical finding, not an assumed Footscray result.
4. Capacity sensitivity:
   - use residential-origin capacity results as local sensitivity around the verified Footscray reference capacity;
   - main figure: system VMT reduction and system CO2 reduction vs capacity scale;
   - service rate and fallback private cars remain diagnostic/supporting metrics;
   - generic capacity run is diagnostic/robustness only;
   - runtime diagnostic at `x1.25` indicates high-capacity service behavior is not primarily a 300-second runtime artifact.
5. Pilot-fleet demand sensitivity:
   - use fixed near-112-seat pilot fleets;
   - main figure: service rate and fallback private cars vs demand fraction;
   - supported commuters used in prose/summary;
   - VMT/CO2 kept diagnostic unless demand-matched baselines are confirmed;
   - optional `all_minibus_pilot` is excluded from paper-facing analysis.
6. Generic-origin robustness:
   - run deliberately as a robustness check;
   - do not use accidental generic results as the main evidence.
7. Multi-station extension:
   - deferred until the corrected Footscray primary experiment is rerun and checked;
   - Footscray is the primary/full-depth case study;
   - future transferability stations must also use column-8 station-specific Myki demand;
   - current candidate robustness stations are Williams Landing and Box Hill, pending final validation;
   - Caulfield and Pakenham are older candidate stations and are not the planned/default pair;
   - do not run a full 35-grid for additional robustness stations unless explicitly requested later.
8. Multi-station robustness presentation:
   - station summary table: station, context, commuters, seats, commuter/seat ratio, number of origin nodes, and average/median direct distance if available;
   - one compact multi-station result figure/table comparing selected fleets across service rate, fallback private-car use, system VMT reduction, system CO2 reduction, and operating cost or cost reduction if available;
   - do not create separate full per-station result sections unless needed.

### Paper-Facing Plot Outputs

Keep diagnostic plots separate from paper-facing figures.

Fleet composition:

```text
fleet_composition_tradeoff_system_vmt_co2.pdf
fleet_composition_tradeoff_system_vmt_co2.png
```

Vehicle-type assignment:

```text
distance_bin_assignment_stacked_bar.pdf
distance_bin_assignment_stacked_bar.png
```

Capacity sensitivity:

```text
capacity_sensitivity_vmt_co2.pdf
capacity_sensitivity_vmt_co2.png
```

Pilot demand sensitivity:

```text
pilot_demand_sensitivity_service_fallback.pdf
pilot_demand_sensitivity_service_fallback.png
```

### LaTeX and Figure Notation

- Use `\COtwo` in manuscript text.
- Use `CO$_2$` in Matplotlib figures.
- Escape percent signs as `\%` in LaTeX.

---

## 15. Default Experiment Settings

Initial corrected Footscray rerun settings, pending Footscray-specific validation:

```text
solver: PyVRP/HGS
time_limit_seconds: 300
demand_window.start_time_minutes: 420
demand_window.end_time_minutes: 570
service_horizon.start_time_minutes: 390
service_horizon.end_time_minutes: 570
time_window.mode: fixed_slots
time_window.interval_minutes: 20
time_window.start_time_minutes: 420
time_window.end_time_minutes: 570
```

Routing cost is raw road distance. The active Footscray config therefore omits legacy distance-preference parameters and solver-objective fixed-cost knobs.

Vehicle assignment emerges from routing distance, vehicle capacity, speed-specific travel times, and time-window feasibility. Runtime and seed convergence are calibration questions; time-window representation is a modelling choice; and the 80-seat reference fleet is experimental design.

Current validation status:

- `300` seconds is the initial solver time limit for corrected Footscray reruns, not a validated Footscray runtime conclusion.
- Runtime, seed count, and time-window representation are pending corrected Footscray validation.
- Fixed 20-minute slots are the initial representation used for reruns and smoke validation; they should not be described as Footscray-calibrated until validation is complete.
- Do not describe Footscray VMT or other metrics as converged until corrected reruns are complete.

Calibration and reporting should use system-level metrics when fallback private cars exist:

```text
service_rate
fallback_private_cars
system_total_vmt_km / system_vmt_change_pct
system_total_energy_kwh / system_energy_change_pct
system_total_co2_kg / system_co2_change_pct
```

Do not report service coverage as 100% under the current fallback framing. `service_rate` is the share of commuters served on time by AV after pruning; remaining commuters are represented by `fallback_private_cars`.

Initial experiment plan, pending corrected Footscray validation:

```text
initial seeds: 15
Footscray reference capacity: 80 seats
fleet composition grid: 25% seat-share increments across four vehicle types
```

The fleet composition grid contains all combinations where:

```text
scooter_share + moped_share + car_share + minibus_share = 100
share ∈ {0, 25, 50, 75, 100}
```

This gives 35 fleet compositions.

Current main experiment status:

```text
case study: Footscray Railway Station residential-origin demand
Myki StopLocationID: 20025
Myki transaction column: 8 (DimStopLocation.StopLocationID)
date: 2018-03-15
corrected demand: 586 commuters
reference fleet: 20 scooters, 10 mopeds, 5 cars, 2 minibuses (80 seats; minibus capacity 10)
PyVRP results: pending rerun
seed convergence: pending rerun
fleet-composition grid: pending rerun
capacity sensitivity: pending rerun
```

The previous Melton grid and associated analyses were generated from column-7 demand. They are archived experiment context and must not be presented as final paper results.

---

## 16. Fleet-Composition Runner

The fleet-composition runner is:

```text
experiments/scripts/run_fleet_composition_grid.sh
```

Purpose:

- enumerate 35 fleet compositions;
- use the corrected 80-seat Footscray reference capacity as the active experimental design;
- generate one config per composition;
- run each composition for `N_SEEDS`;
- support `LABELS_OVERRIDE` for selected conditions;
- support `TIME_LIMIT_SECONDS`, `PARALLEL_JOBS`, `CONFIG_ONLY`, and `OUTPUT_DIR`.

Important design:

- Corrected Footscray runners should use `config/footscray_base_config.json` as their template; legacy Melton runners use `config/legacy_melton_base_config.json`.
- The 80-seat Footscray reference fleet is an experiment-design choice, not a calibrated fleet capacity. The historical 224-seat grid applies only to archived Melton work.
- It should preserve shared fields such as `demand_window`, `service_horizon`, `time_window`, `energy_model`, `baseline_parameters`, and `cost_model`. Legacy Melton configs may retain `penalty_parameters` for archived workflows, but active Footscray runners should not require them.
- It should modify only experiment-specific fleet composition and metadata.

Common smoke-test pattern:

```bash
OUTPUT_DIR=experiments/test_results/footscray_fleet_composition_grid_80seats \
TIME_LIMIT_SECONDS=60 \
N_SEEDS=1 \
LABELS_OVERRIDE="comp_S25_M25_C25_MB25 comp_S25_M0_C0_MB75 comp_S25_M75_C0_MB0 comp_S0_M0_C100_MB0" \
PARALLEL_JOBS=7 \
bash experiments/scripts/run_fleet_composition_grid.sh
```

The historical smoke labels `comp_S25_M25_C0_MB50` and `comp_S25_M50_C0_MB25` may appear in older notes or outputs, but they are not the current selected representative fleets.

### 16.1 Selected Representative Fleets

The representative seat-share patterns carried forward for the Footscray rerun are shown below. The balanced Footscray reference is 20 scooters, 10 mopeds, 5 cars, and 2 minibuses with capacity 10, giving 80 seats and exact 25% seat shares. Other absolute Footscray fleet realizations must preserve the intended seat shares under the Footscray capacities.

| Representative fleet | Seat shares | Historical 224-seat Melton realization | Role |
|---|---|---|---|
| Balanced heterogeneous reference | S25/M25/C25/MB25 | 56 scooters, 28 mopeds, 14 cars, 7 minibuses | Balanced reference |
| VMT-oriented | S25/M0/C0/MB75 | 56 scooters, 0 mopeds, 0 cars, 21 minibuses | System VMT-oriented representative |
| Low-emission | S25/M75/C0/MB0 | 56 scooters, 84 mopeds, 0 cars, 0 minibuses | System energy/CO2-oriented representative |
| All-car homogeneous comparator | S0/M0/C100/MB0 | 0 scooters, 0 mopeds, 56 cars, 0 minibuses | Homogeneous comparator |

All-scooter, all-moped, and all-minibus compositions remain part of the 35-composition grid. They are no longer carried forward as main representative fleets and should be treated as diagnostic/extreme grid cases unless explicitly selected for a separate sensitivity test.

### 16.1.1 Corrected Footscray Smoke Validation

The balanced 80-seat, minibus-capacity-10 smoke run used seed 1, a 60-second solver limit, and the `06:30–09:30` service horizon. It produced:

| Metric | Smoke result |
|---|---:|
| Served commuters | 581 / 586 |
| Fallback private cars | 5 |
| Service rate | 99.15% |
| System total VMT | 1158.6737 km |
| System total CO2 | 141.7181 kg |
| Vehicle trips | 154 |
| Pooling rate | 94.16% |

This corrected post-window-fix smoke result is only an input and model validation check. It is not final paper evidence and must not be presented as a converged experiment result.

### 16.2 Representative Capacity Sensitivity

The representative capacity sensitivity experiment is implemented by:

```text
experiments/scripts/run_capacity_sensitivity_representative.sh
experiments/scripts/plot_capacity_sensitivity_representative.py
```

Purpose:

- test whether the selected representative fleet strategies remain stable under moderate capacity changes.

Fleet strategies:

```text
balanced
vmt_oriented
low_emission
all_car
```

Capacity scales:

```text
x0.90
x1.00
x1.10
x1.25
```

Current settings:

- residential-origin demand;
- initial 15 seeds, pending corrected Footscray seed validation;
- initial 300-second solver runtime, pending corrected Footscray runtime validation;
- initial fixed 20-minute slots, pending corrected Footscray time-window validation.

The analyzer should extract:

- service rate;
- fallback private cars;
- system VMT reduction;
- system energy reduction;
- system CO2 reduction;
- parking metrics;
- cost metrics where available.

Cost and parking are evaluation-only and do not affect routing.

Targeted runtime diagnostic:

- A targeted runtime diagnostic was run for `x1.25` all-car and VMT-oriented fleets using seeds 1--5 at 600 seconds and 1200 seconds.
- Longer runtime did not recover service toward `x1.00` levels:
  - all-car `x1.25` service: 300-second main mean 88.3%, 600-second diagnostic 87.8%, 1200-second diagnostic 87.9%;
  - VMT-oriented `x1.25` service: 300-second main mean 92.0%, 600-second diagnostic 92.1%, 1200-second diagnostic 91.8%.
- This diagnostic suggests the high-capacity service pattern is not primarily a 300-second runtime artifact.
- It is a targeted diagnostic only, not a full replacement for the 15-seed main sweep.

Current state:

- Previous Melton capacity outputs are archived because their demand was generated from transaction column `7`.
- Corrected Footscray capacity sensitivity is pending rerun and must use column-8 Footscray station demand.

### 16.3 Pilot-Fleet Demand Sensitivity

The pilot-fleet demand sensitivity experiment is implemented by:

```text
experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
experiments/scripts/plot_pilot_fleet_demand_sensitivity.py
```

Purpose:

- evaluate how much observed residential-origin demand a smaller fixed pilot fleet can support.

Demand levels:

```text
x0.25
x0.50
x0.75
x1.00
```

Demand subsets are nested and preserve the train-slot distribution using `drop_off_latest`. The default demand sample seed is `42`.

Default near-112-seat pilot fleets:

| Pilot fleet | Counts | Seats |
|---|---|---:|
| balanced_pilot | 28 scooters, 14 mopeds, 7 cars, 3 minibuses | 108 |
| vmt_oriented_pilot | 28 scooters, 0 mopeds, 0 cars, 10 minibuses | 108 |
| low_emission_pilot | 28 scooters, 42 mopeds, 0 cars, 0 minibuses | 112 |
| all_car_pilot | 0 scooters, 0 mopeds, 28 cars, 0 minibuses | 112 |

An optional diagnostic `all_minibus_pilot` can be enabled with `INCLUDE_ALL_MINIBUS=1`:

```text
0 scooters, 0 mopeds, 0 cars, 14 minibuses = 112 seats
```

`all_minibus_pilot` is not used in the current paper-facing pilot analysis unless explicitly enabled for diagnostics. Paper-facing pilot analysis uses only:

```text
all_car_pilot
balanced_pilot
vmt_oriented_pilot
low_emission_pilot
```

Pilot fleets should be described as "near-112-seat pilot fleets", "approximately half-scale pilot fleets", or a "112-seat pilot reference", not as exactly equal-seat fleets.

Current state: previous Melton pilot outputs are archived because their demand was generated from transaction column `7`. Any Footscray pilot analysis is pending rerun.

Runner design:

- the existing Melton-era runner generates configs from `config/legacy_melton_base_config.json`; a corrected Footscray rerun must explicitly use `config/footscray_base_config.json`;
- modify only `experiment_name`, fleet sizes/types, solver time limit, and pilot metadata;
- preserve the all-electric energy, emissions, cost, parking, time-window, baseline, and penalty settings from the base config.

The analyzer should extract service, fallback private cars, system VMT/energy/CO2 metrics, parking, and cost metrics into summary CSVs.

---

### 16.4 Multi-Station Robustness Experiment

The multi-station extension is deferred until the corrected Footscray primary experiment is complete. It remains a compact robustness/transferability experiment rather than a repeat of the full primary analysis.

Stations:

| Station | Role |
|---|---|
| Footscray | Corrected primary case; full-depth residential-origin experiments pending rerun |
| Williams Landing | Current candidate robustness station, pending final validation |
| Box Hill | Current candidate robustness station, pending final validation |

Caulfield and Pakenham were older candidate robustness stations. They are not the current planned/default pair and should be revisited only if selected after station validation.

Purpose:

- test whether the corrected fleet-composition findings from Footscray are station-specific;
- present robustness/transferability evidence for the pipeline and fleet-composition findings;
- keep the section compact for a SIGSPATIAL Applications paper.

Demand and fleet scaling:

- Preserve the corrected Footscray commuter-to-seat ratio rather than forcing the same absolute demand everywhere.
- Footscray uses `586` commuters and an 80-seat reference fleet, or approximately `7.33` commuters per seat.
- For each additional station, use station-specific commuter demand if available, and choose reference fleet seats to preserve approximately this ratio.
- If controlled comparison is needed because station-specific demand is unavailable or unreliable, document this explicitly and keep the same commuter-to-seat ratio.
- Report the actual commuter count and seat count per station in the experiment summary.

Temporal demand construction:

- Prefer station-specific Myki/tap-on distributions from the same 2018 dataset.
- If station-specific Myki distributions are not immediately available, use the corrected Footscray 20-minute slot proportions as a prior applied to the station-specific commuter count.
- Do not use a uniform synthetic temporal distribution unless explicitly justified later.
- Preserve the same morning-peak window: `07:00--09:30`.
- Preserve the same train-aligned/fixed-slot structure: 20-minute slots.

Solver/settings:

- Begin with the Footscray rerun settings:
  - PyVRP/HGS;
  - initial 300-second runtime;
  - initial 15 seeds;
  - initial fixed 20-minute time windows;
- Treat runtime, seed count, and time-window representation as provisional until corrected Footscray validation is complete.
- Do not redo full calibration for additional robustness stations.
- If service rate under the reference/balanced fleet is extremely low or extremely high, flag it as a boundary condition and report it rather than silently recalibrating.

Compact fleet set for validated robustness stations:

| Fleet | Seat shares | Role |
|---|---|---|
| all-car | S0/M0/C100/MB0 | homogeneous comparator |
| all-minibus | S0/M0/C0/MB100 | additional homogeneous/extreme comparator |
| balanced | S25/M25/C25/MB25 | balanced heterogeneous reference |
| VMT-oriented / minibus-heavy | S25/M0/C0/MB75 | system VMT-oriented representative |
| low-emission / moped-heavy | S25/M75/C0/MB0 | system energy/CO2-oriented representative |

Do not add all-moped to the multi-station robustness experiment unless explicitly requested later. Do not redefine the representative fleet compositions already specified for the corrected Footscray reruns.

Minimum data-quality checks for new stations:

- Residential origin candidates should cover the station catchment without obvious large OSM gaps.
- Bidirectional reachability should be validated:
  - origin -> station;
  - station -> origin.
- At least 95% of sampled origins should be reachable, or failures should be reported and investigated.
- At least 200 distinct origin nodes should be available after mapping/reachability filtering; otherwise candidate extraction may be too sparse.
- Balanced/reference service rate should be sanity checked. If it is below roughly 45% or above roughly 97%, flag the station as a boundary case.
- Seed variation across 15 seeds should be checked, especially for service rate and system VMT reduction.

Data-preparation requirements for each new station:

- station OSM PBF or clipped OSM extract;
- graph speed file;
- nodes lat/lon CSV;
- hub-label distance/time files;
- residential candidate points/nodes/mapping files;
- `commuters_residential.csv`;
- `commuters_residential_metadata.json`;
- station node ID;
- station-specific or prior-based temporal demand distribution.

Final commuter CSV schema remains:

```text
id,origin_node,destination_node,pickup_earliest,drop_off_latest
```

Do not describe origins as observed home locations; they remain inferred residential/address candidate road nodes paired with temporal demand.

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
config/footscray_base_config.json
    Active corrected Footscray experiment configuration.

config/legacy_melton_base_config.json
    Legacy Melton-era configuration retained for archived and reproducibility workflows.

docs/energy_assumptions_reference.md
    Source-trace file for electric energy and emissions assumptions.

docs/cost_assumptions_reference.md
    Source-trace file for AV fleet cost assumptions.

python/simulate_first_mile_pyvrp.py
    Main PyVRP simulation, solution extraction, pruning, metrics, and output writing.

python/simulate_first_mile_utils.py
    Dataclasses and pure helper functions for testing:
    time windows, pruning helpers, baseline, compare, parking, cost, cost matrix.

python/build_myki_commuters.py
    Myki-based commuter CSV generation and metadata writing.

python/build_residential_origin_candidates.py
    OSM residential/address candidate extraction, nearest road-node mapping, walking-threshold filtering, and candidate metadata writing.

python/build_osm_network_inputs.py
    Station-generic OSM road-network artifact builder for nodes, speed, distance, time, and network metadata inputs.

python/tests/test_simulate_utils.py
    Unit tests for core utility behavior and metric formulas.

experiments/scripts/run_fleet_composition_grid.sh
    Fleet-composition experiment runner.

experiments/scripts/plot_fleet_composition_grid.py
    Fleet-composition summary and plotting script.

experiments/scripts/run_capacity_sensitivity_representative.sh
    Representative-fleet capacity-sensitivity runner.

experiments/scripts/plot_capacity_sensitivity_representative.py
    Representative-fleet capacity-sensitivity analyzer and plotter.

experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
    Pilot-fleet demand-sensitivity runner.

experiments/scripts/plot_pilot_fleet_demand_sensitivity.py
    Pilot-fleet demand-sensitivity analyzer and plotter.

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
footscray_residential_candidate_nodes_3km.csv
```

The previous Melton residential candidate artifacts may be retained for archived reproducibility checks, but they are not active Footscray paper inputs.

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

1. Create and validate this project specification. Completed
2. Correct station-level Myki filtering to use transaction column `8` (`DimStopLocation.StopLocationID`) and establish Footscray Railway Station (`20025`) as the main paper case. Completed
3. Build the Footscray road network and the residential/address origin candidate pool for the `>800 m` to `3 km` catchment. Completed
4. Verify the corrected Footscray commuter extraction for `2018-03-15`, final commuter count, matrix order, and network access distances. Completed: 586 commuters and a validated `587 x 587` matrix
5. Rerun Footscray seed convergence and runtime diagnostics under corrected column-8 demand. Pending
6. Rerun the Footscray fleet-composition experiment and representative-fleet analyses. Pending
7. Rerun Footscray capacity sensitivity and any required pilot-fleet demand sensitivity. Pending
8. Retain previous column-7 Melton experiments only as archived/reproducibility context; do not use them as final paper results.
9. Run deliberate generic-origin robustness checks after the corrected Footscray primary experiments. Planned; generic reachable-node results remain robustness/sensitivity comparisons only.
10. Validate Williams Landing and Box Hill as the current candidate robustness stations after the corrected Footscray experiment suite is complete. Caulfield and Pakenham remain older candidates only; do not run full 35-composition grids for additional stations unless explicitly requested later.
11. Generate corrected Footscray paper-facing outputs before any multi-station comparison outputs.
12. Share updated outputs with supervisors before the next meeting.

TODO: Add mathematical problem formulation to the paper.
- Define commuters, station, deadlines/time windows, heterogeneous vehicle types, capacities, travel-time matrices, route assignment variables, service/fallback variables, and objective/metrics.
- Clarify that the implemented solver is PyVRP/HGS and the paper evaluates fleet-composition scenarios rather than proposing a new routing algorithm.

Corrected Footscray fleet-composition results, representative-fleet capacity sensitivity, pilot-fleet demand sensitivity, future multi-station robustness checks, and final cost-related interpretation should use the refined all-electric energy, emissions, cost, and parking evaluation model.
