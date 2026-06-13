# Corrected Footscray Pipeline Runbook

This runbook rebuilds the corrected Footscray data pipeline from raw Myki and OSM inputs through smoke validation. Run commands from the repository root.

```bash
cd /path/to/hub_label
PYTHON=.venv/bin/python
[[ -x "$PYTHON" ]] || PYTHON=python3
```

The corrected case uses Footscray Railway Station, road node `240615`, Myki `DimStopLocation.StopLocationID` `20025` from transaction column `8`, and date `2018-03-15`.

```text
Active Footscray config: config/footscray_base_config.json
Legacy Melton config:    config/legacy_melton_base_config.json
```

## 1. Required Raw Inputs

Required source data:

```text
dataset/MYKI/Samp_9
dataset/OSM_DATA/footscray_osm.pbf
```

Required compiled tools:

```text
bin/construct
bin/build_commuters_reachable
bin/dump_distance_matrix
```

Build the binaries if necessary:

```bash
make fast
```

Also require the Python packages in `python/requirements.txt`, including the OSM and PyVRP dependencies.

## 2. Optional Cleanup And Backup

These commands affect only generated Footscray artifacts. Do not remove the raw Myki root or OSM PBF.

Back up generated `files/inputs/footscray_*` files:

```bash
BACKUP_DIR="backups/footscray_inputs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
find files/inputs -maxdepth 1 -type f -name 'footscray_*' \
  -exec cp -p {} "$BACKUP_DIR"/ \;
```

Remove only generated Footscray input files:

```bash
find files/inputs -maxdepth 1 -type f -name 'footscray_*' -delete
```

Optionally remove the generated residential matrix:

```bash
rm -rf dataset/FOOTSCRAY/footscray_residential_matrix
```

Remove Footscray distance labels only when intentionally rebuilding them:

```bash
rm -f \
  dataset/FOOTSCRAY/footscray_dist.dorder \
  dataset/FOOTSCRAY/footscray_dist.dlabel
```

## 3. Build Footscray Network Inputs

```bash
"$PYTHON" python/build_osm_network_inputs.py \
  --osm-pbf dataset/OSM_DATA/footscray_osm.pbf \
  --station footscray \
  --out-dir files/inputs
```

Expected outputs:

```text
files/inputs/footscray_graph_distance.txt
files/inputs/footscray_graph_speed.txt
files/inputs/footscray_graph_time.txt
files/inputs/footscray_nodes_lat_lon.csv
files/inputs/footscray_network_metadata.json
```

The builder also writes `files/inputs/footscray_graph.txt` as a debug artifact.

## 4. Build Hub Labels

Use the generic label target with Footscray overrides:

```bash
make labels_dist \
  DATASET_DIR=dataset/FOOTSCRAY \
  GRAPH_DIST=files/inputs/footscray_graph_distance.txt \
  PFX_DIST=dataset/FOOTSCRAY/footscray_dist
```

Equivalent direct binary command:

```bash
mkdir -p dataset/FOOTSCRAY
bin/construct \
  files/inputs/footscray_graph_distance.txt \
  dataset/FOOTSCRAY/footscray_dist \
  dataset/FOOTSCRAY/footscray_dist
```

Expected outputs:

```text
dataset/FOOTSCRAY/footscray_dist.dorder
dataset/FOOTSCRAY/footscray_dist.dlabel
```

## 5. Build Residential Candidate Pool

The catchment is applied to OSM residential/address candidate points before nearest-road-node mapping: greater than `800 m` and at most `3 km` radial distance from the station.

```bash
"$PYTHON" python/build_residential_origin_candidates.py \
  --osm-pbf dataset/OSM_DATA/footscray_osm.pbf \
  --road-nodes files/inputs/footscray_nodes_lat_lon.csv \
  --station-node 240615 \
  --walking-threshold-m 800 \
  --max-station-distance-m 3000 \
  --out-nodes files/inputs/footscray_residential_candidate_nodes_3km.csv \
  --out-points files/inputs/footscray_residential_candidate_points_3km.csv \
  --out-mapping files/inputs/footscray_residential_candidate_mapping_3km.csv \
  --metadata-out files/inputs/footscray_residential_candidate_metadata_3km.json
```

The final mapped road-node distances may differ slightly from `800 m` and `3 km` because filtering occurs before nearest-node mapping. The expected candidate-node pool contains 6,606 rows with a `node_id` column.

## 6. Build Myki-Derived Commuters

The active config separates three timing concepts:

- `demand_window` is `07:00–09:30` and controls Myki tap-on extraction.
- `service_horizon` is `06:30–09:30` and controls vehicle operation and maximum route duration.
- `time_window` is `07:00–09:30` and generates fixed 20-minute station-arrival deadline slots beginning at `07:00`.

The 30-minute `--pickup-buffer` remains the commuter pickup-window width: `pickup_earliest = drop_off_latest - 30`. It does not widen Myki extraction.
A commuter with a `07:01` tap-on/deadline may therefore be picked up from `06:31`, while their fixed station-arrival slot is `07:00`, not `06:50`.

Build the corrected commuter file from 2018 Week 11:

```bash
"$PYTHON" python/build_myki_commuters.py \
  --myki-root dataset/MYKI/Samp_9 \
  --nodes-file files/inputs/footscray_residential_candidate_nodes_3km.csv \
  --coord-nodes-file files/inputs/footscray_nodes_lat_lon.csv \
  --dest-node 240615 \
  --cpp-bin bin/build_commuters_reachable \
  --labels dataset/FOOTSCRAY/footscray_dist \
  --out files/inputs/footscray_commuters_residential.csv \
  --metadata-out files/inputs/footscray_commuters_residential_metadata.json \
  --config config/footscray_base_config.json \
  --year 2018 \
  --week 11 \
  --date 2018-03-15 \
  --station-name Footscray \
  --stop-ids 20025 \
  --stop-id-column 8 \
  --pickup-buffer 30 \
  --seed 42 \
  --origin-sampling random \
  --origin-candidate-source osm_residential_address_candidate_nodes_3km \
  --residential-candidate-metadata files/inputs/footscray_residential_candidate_metadata_3km.json
```

Expected output: `586` commuters. The Myki tap-on window is `07:00–09:30`; each commuter's earliest pickup may be 30 minutes before their station-arrival deadline.

## 7. Create Station CSV

```bash
cat > files/inputs/footscray_station.csv <<'CSV'
station_id,station_name,node_id
S1,Footscray Railway Station,240615
CSV
```

## 8. Build Residential Matrix

```bash
make footscray_dump_matrices
```

This target uses:

```text
labels:       dataset/FOOTSCRAY/footscray_dist
graph:        files/inputs/footscray_graph_distance.txt
commuters:    files/inputs/footscray_commuters_residential.csv
station node: 240615
speed table:  files/inputs/footscray_graph_speed.txt
output:       dataset/FOOTSCRAY/footscray_residential_matrix
```

The matrix input must be the final commuter CSV with `origin_node`. Never pass the 6,606-row candidate pool, which has `node_id` and is only an origin-sampling input.

## 9. Validation Checks

Run the structural and distance checks:

```bash
"$PYTHON" - <<'PY'
import csv
from pathlib import Path

import numpy as np

commuter_path = Path("files/inputs/footscray_commuters_residential.csv")
matrix_dir = Path("dataset/FOOTSCRAY/footscray_residential_matrix")

with commuter_path.open(newline="") as stream:
    origins = [int(row["origin_node"]) for row in csv.DictReader(stream)]

nodes = [int(value) for value in (matrix_dir / "nodes.txt").read_text().splitlines()]
distances = np.load(matrix_dir / "distances.npy")

assert len(origins) == 586, len(origins)
assert distances.shape == (587, 587), distances.shape
assert nodes[0] == 240615, nodes[0]
assert nodes[1:] == origins
assert len(origins) == len(set(origins))

km = distances[1:, 0] / 1_000_000
print("commuters:", len(origins))
print("matrix shape:", distances.shape)
print("station node:", nodes[0])
print("duplicate origins:", len(origins) - len(set(origins)))
print("median/p90/p95/p99/max km:", *np.percentile(km, [50, 90, 95, 99]), km.max())
print(">5 km / >8 km / >10 km:", *(int((km > limit).sum()) for limit in (5, 8, 10)))
PY
```

Validated reference values:

```text
median 3.21 km; p90 4.34 km; p95 4.86 km; p99 7.28 km; max 8.20 km
>5 km: 22/586; >8 km: 3/586; >10 km: 0/586
```

## 10. Smoke Validation

```bash
bash experiments/scripts/run_footscray_smoke.sh
```

The helper uses `config/footscray_base_config.json`, creates a temporary 60-second config inside:

```text
experiments/results/footscray/smoke_balanced_80seats_mb10_h0630_seed1
```

and runs seed 1. This is an input/model smoke check, not a final paper experiment or convergence result.

## 11. Common Mistakes

- Do not use transaction column `7` for corrected station-level demand. Use column `8` and StopLocationID `20025`.
- Do not pass `footscray_residential_candidate_nodes_3km.csv` to matrix dumping. Use the final commuter CSV with `origin_node`.
- Do not confuse the Myki demand window (`07:00–09:30`), vehicle service horizon (`06:30–09:30`), and fixed deadline slots (`07:00–09:30`).
- Use `config/footscray_base_config.json` directly: `demand_window` controls extraction, `service_horizon` controls vehicle operation, and `time_window` controls station-arrival slots.
- Do not use `config/legacy_melton_base_config.json` for corrected Footscray runs.
- Do not treat smoke outputs as final evidence.
