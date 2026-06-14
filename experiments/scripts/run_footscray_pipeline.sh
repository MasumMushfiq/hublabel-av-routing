#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

DRY_RUN="${DRY_RUN:-0}"

# Keep station constants together so Box Hill and Williams Landing wrappers can
# reuse the same stage layout later with different station-specific values.
STATION_KEY=footscray
STATION_DISPLAY=Footscray
STATION_CSV_NAME="Footscray Railway Station"
STATION_NODE=240615
MYKI_ROOT=dataset/MYKI/Samp_9
STOP_IDS=20025
STOP_ID_COLUMN=8
OSM_PBF=dataset/OSM_DATA/footscray_osm.pbf
BASE_CONFIG=config/footscray_base_config.json
EXPECTED_COMMUTERS=586
DATE=2018-03-15
YEAR=2018
WEEK=11
PICKUP_BUFFER=30
SEED=42
MIN_STATION_DISTANCE_M=800
MAX_STATION_DISTANCE_M=3000
PROD_INPUTS_DIR=files/inputs
PROD_DATASET_DIR=dataset/FOOTSCRAY
PROD_LABEL_PREFIX=dataset/FOOTSCRAY/footscray_dist
PROD_MATRIX_DIR=dataset/FOOTSCRAY/footscray_residential_matrix
PROD_GRAPH_DIST=files/inputs/footscray_graph_distance.txt
PROD_GRAPH_SPEED=files/inputs/footscray_graph_speed.txt
PROD_GRAPH_TIME=files/inputs/footscray_graph_time.txt
PROD_NODES=files/inputs/footscray_nodes_lat_lon.csv
PROD_NETWORK_METADATA=files/inputs/footscray_network_metadata.json
PROD_CANDIDATE_NODES=files/inputs/footscray_residential_candidate_nodes_3km.csv
PROD_CANDIDATE_POINTS=files/inputs/footscray_residential_candidate_points_3km.csv
PROD_CANDIDATE_MAPPING=files/inputs/footscray_residential_candidate_mapping_3km.csv
PROD_CANDIDATE_METADATA=files/inputs/footscray_residential_candidate_metadata_3km.json
PROD_COMMUTERS_CSV=files/inputs/footscray_commuters_residential.csv
PROD_COMMUTERS_METADATA=files/inputs/footscray_commuters_residential_metadata.json
PROD_STATION_CSV=files/inputs/footscray_station.csv

INPUTS_DIR="$PROD_INPUTS_DIR"
DATASET_DIR="$PROD_DATASET_DIR"
LABEL_PREFIX=""
MATRIX_DIR=""

NETWORK_GRAPH_DIST=""
NETWORK_GRAPH_SPEED=""
NETWORK_GRAPH_TIME=""
NETWORK_NODES=""
NETWORK_METADATA=""
CANDIDATE_NODES=""
CANDIDATE_POINTS=""
CANDIDATE_MAPPING=""
CANDIDATE_METADATA=""
COMMUTERS_CSV=""
COMMUTERS_METADATA=""
STATION_CSV=""

TEST_OUTPUT_ROOT=""
INPUTS_DIR_EXPLICIT=0
DATASET_DIR_EXPLICIT=0
LABEL_PREFIX_EXPLICIT=0
MATRIX_DIR_EXPLICIT=0
OUTPUT_MODE_TEST=0

SMOKE_SCRIPT=experiments/scripts/run_footscray_smoke.sh

usage() {
  cat <<'EOF'
Usage: bash experiments/scripts/run_footscray_pipeline.sh [options]

Options:
  --stage STAGE        Run one stage: network, labels, candidates, commuters,
                       station, matrix, validate, compare, smoke, all. Default: all.
  --inputs-dir DIR     Write generated input files under DIR. Default: files/inputs.
  --dataset-dir DIR    Write labels and matrix outputs under DIR.
  --matrix-dir DIR     Write matrices under DIR. Default: <dataset-dir>/footscray_residential_matrix.
  --label-prefix PATH  Use PATH as the label prefix. Default: <dataset-dir>/footscray_dist.
  --test-output-root DIR
                       Convenience sandbox root for side-by-side comparisons.
  --clean-generated    Back up then remove generated <inputs-dir>/footscray_*
                       files before starting.
  --clean-matrix       Remove the active matrix directory.
  --rebuild-labels     Remove the active label prefix .dorder/.dlabel files.
  --skip-smoke         Skip the smoke stage when --stage all is used.
  --help               Show this help.

Environment:
  PYTHON   Python executable to use. Defaults to .venv/bin/python, then python3.
  DRY_RUN  Set to 1 to print commands without executing them.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

print_cmd() {
  printf '+ '
  local arg
  for arg in "$@"; do
    printf '%q ' "$arg"
  done
  printf '\n'
}

run_cmd() {
  print_cmd "$@"
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  "$@"
}

stage_header() {
  echo
  echo "==> $1"
}

check_path() {
  local path="$1"
  local label="$2"
  local required_in_dry_run="${3:-0}"

  if [[ -e "$path" ]]; then
    return 0
  fi

  if [[ "$DRY_RUN" == "1" && "$required_in_dry_run" != "1" ]]; then
    echo "DRY_RUN: would verify $label at $path"
    return 0
  fi

  die "Missing $label: $path"
}

check_raw_inputs() {
  check_path "$MYKI_ROOT" "raw Myki root" 1
  check_path "$OSM_PBF" "Footscray OSM PBF" 1
}

ensure_binary() {
  local binary_path="$1"
  local label="$2"

  if [[ -x "$binary_path" ]]; then
    return 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    if [[ -f Makefile ]]; then
      echo "DRY_RUN: would run make fast because $label is missing: $binary_path"
    else
      echo "DRY_RUN: missing $label and no Makefile is available to build it: $binary_path"
    fi
    return 0
  fi

  if [[ ! -f Makefile ]]; then
    die "Missing $label and Makefile is not available to build it: $binary_path"
  fi

  echo "$label is missing; running make fast"
  run_cmd make fast
  [[ -x "$binary_path" ]] || die "$label is still missing after make fast: $binary_path"
}

ensure_python() {
  command -v "$PYTHON" >/dev/null 2>&1 || die "Python executable not found: $PYTHON"
}

refresh_paths() {
  if [[ -z "$LABEL_PREFIX" ]]; then
    LABEL_PREFIX="$DATASET_DIR/${STATION_KEY}_dist"
  fi
  if [[ -z "$MATRIX_DIR" ]]; then
    MATRIX_DIR="$DATASET_DIR/${STATION_KEY}_residential_matrix"
  fi

  NETWORK_GRAPH_DIST="$INPUTS_DIR/${STATION_KEY}_graph_distance.txt"
  NETWORK_GRAPH_SPEED="$INPUTS_DIR/${STATION_KEY}_graph_speed.txt"
  NETWORK_GRAPH_TIME="$INPUTS_DIR/${STATION_KEY}_graph_time.txt"
  NETWORK_NODES="$INPUTS_DIR/${STATION_KEY}_nodes_lat_lon.csv"
  NETWORK_METADATA="$INPUTS_DIR/${STATION_KEY}_network_metadata.json"
  CANDIDATE_NODES="$INPUTS_DIR/${STATION_KEY}_residential_candidate_nodes_3km.csv"
  CANDIDATE_POINTS="$INPUTS_DIR/${STATION_KEY}_residential_candidate_points_3km.csv"
  CANDIDATE_MAPPING="$INPUTS_DIR/${STATION_KEY}_residential_candidate_mapping_3km.csv"
  CANDIDATE_METADATA="$INPUTS_DIR/${STATION_KEY}_residential_candidate_metadata_3km.json"
  COMMUTERS_CSV="$INPUTS_DIR/${STATION_KEY}_commuters_residential.csv"
  COMMUTERS_METADATA="$INPUTS_DIR/${STATION_KEY}_commuters_residential_metadata.json"
  STATION_CSV="$INPUTS_DIR/${STATION_KEY}_station.csv"
}

configure_test_output_root() {
  local root="$1"
  TEST_OUTPUT_ROOT="$root"
  INPUTS_DIR="$root/files_inputs"
  DATASET_DIR="$root/dataset_FOOTSCRAY"
  LABEL_PREFIX="$DATASET_DIR/${STATION_KEY}_dist"
  MATRIX_DIR="$DATASET_DIR/${STATION_KEY}_residential_matrix"
  OUTPUT_MODE_TEST=1
}

active_paths_are_production() {
  [[ "$INPUTS_DIR" == "$PROD_INPUTS_DIR" ]] &&
    [[ "$DATASET_DIR" == "$PROD_DATASET_DIR" ]] &&
    [[ "$LABEL_PREFIX" == "$PROD_LABEL_PREFIX" ]] &&
    [[ "$MATRIX_DIR" == "$PROD_MATRIX_DIR" ]]
}

cleanup_generated() {
  stage_header "CLEANUP"

  local backup_dir="backups/${STATION_KEY}_inputs_$(date +%Y%m%d_%H%M%S)"
  [[ -d "$INPUTS_DIR" ]] || {
    echo "No generated inputs directory to clean at $INPUTS_DIR"
    return 0
  }
  run_cmd mkdir -p "$backup_dir"
  run_cmd find "$INPUTS_DIR" -maxdepth 1 -type f -name "${STATION_KEY}_*" -exec cp -p '{}' "$backup_dir" ';'
  run_cmd find "$INPUTS_DIR" -maxdepth 1 -type f -name "${STATION_KEY}_*" -delete
}

cleanup_matrix() {
  stage_header "CLEAN MATRIX"
  [[ -e "$MATRIX_DIR" ]] || {
    echo "No matrix directory to clean at $MATRIX_DIR"
    return 0
  }
  run_cmd rm -rf "$MATRIX_DIR"
}

cleanup_labels() {
  stage_header "REBUILD LABELS"
  [[ -e "$LABEL_PREFIX.dorder" || -e "$LABEL_PREFIX.dlabel" ]] || {
    echo "No label outputs to clean at $LABEL_PREFIX.*"
    return 0
  }
  run_cmd rm -f "$LABEL_PREFIX.dorder" "$LABEL_PREFIX.dlabel"
}

stage_network() {
  stage_header "NETWORK"
  check_raw_inputs

  run_cmd "$PYTHON" python/build_osm_network_inputs.py \
    --osm-pbf "$OSM_PBF" \
    --station "$STATION_KEY" \
    --out-dir "$INPUTS_DIR"

  for path in \
    "$NETWORK_GRAPH_DIST" \
    "$NETWORK_GRAPH_SPEED" \
    "$NETWORK_GRAPH_TIME" \
    "$NETWORK_NODES" \
    "$NETWORK_METADATA"; do
    check_path "$path" "network output"
  done
}

stage_labels() {
  stage_header "LABELS"
  check_raw_inputs
  check_path "$NETWORK_GRAPH_DIST" "network graph distance output"
  ensure_binary bin/construct "bin/construct"

  run_cmd make labels_dist \
    DATASET_DIR="$DATASET_DIR" \
    GRAPH_DIST="$NETWORK_GRAPH_DIST" \
    PFX_DIST="$LABEL_PREFIX"

  check_path "$LABEL_PREFIX.dorder" "label order output"
  check_path "$LABEL_PREFIX.dlabel" "label payload output"
}

stage_candidates() {
  stage_header "CANDIDATES"
  check_raw_inputs
  check_path "$NETWORK_NODES" "network node coordinate output"

  run_cmd "$PYTHON" python/build_residential_origin_candidates.py \
    --osm-pbf "$OSM_PBF" \
    --road-nodes "$NETWORK_NODES" \
    --station-node "$STATION_NODE" \
    --walking-threshold-m "$MIN_STATION_DISTANCE_M" \
    --max-station-distance-m "$MAX_STATION_DISTANCE_M" \
    --out-nodes "$CANDIDATE_NODES" \
    --out-points "$CANDIDATE_POINTS" \
    --out-mapping "$CANDIDATE_MAPPING" \
    --metadata-out "$CANDIDATE_METADATA"

  for path in \
    "$CANDIDATE_NODES" \
    "$CANDIDATE_POINTS" \
    "$CANDIDATE_MAPPING" \
    "$CANDIDATE_METADATA"; do
    check_path "$path" "candidate output"
  done
}

stage_commuters() {
  stage_header "COMMUTERS"
  check_raw_inputs
  check_path "$CANDIDATE_NODES" "candidate node pool"
  check_path "$NETWORK_NODES" "network node coordinate output"
  check_path "$LABEL_PREFIX.dorder" "label order output"
  check_path "$LABEL_PREFIX.dlabel" "label payload output"
  ensure_binary bin/build_commuters_reachable "bin/build_commuters_reachable"

  run_cmd "$PYTHON" python/build_myki_commuters.py \
    --myki-root "$MYKI_ROOT" \
    --nodes-file "$CANDIDATE_NODES" \
    --coord-nodes-file "$NETWORK_NODES" \
    --dest-node "$STATION_NODE" \
    --cpp-bin bin/build_commuters_reachable \
    --labels "$LABEL_PREFIX" \
    --out "$COMMUTERS_CSV" \
    --metadata-out "$COMMUTERS_METADATA" \
    --config "$BASE_CONFIG" \
    --year "$YEAR" \
    --week "$WEEK" \
    --date "$DATE" \
    --station-name "$STATION_DISPLAY" \
    --stop-ids "$STOP_IDS" \
    --stop-id-column "$STOP_ID_COLUMN" \
    --pickup-buffer "$PICKUP_BUFFER" \
    --seed "$SEED" \
    --origin-sampling random \
    --origin-candidate-source osm_residential_address_candidate_nodes_3km \
    --residential-candidate-metadata "$CANDIDATE_METADATA"

  check_path "$COMMUTERS_CSV" "commuter CSV"
  check_path "$COMMUTERS_METADATA" "commuter metadata"

  run_cmd "$PYTHON" - "$COMMUTERS_CSV" "$EXPECTED_COMMUTERS" <<'PY'
import csv
import sys
from pathlib import Path

commuter_path = Path(sys.argv[1])
expected = int(sys.argv[2])

with commuter_path.open(newline="", encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))

actual = len(rows)
if actual != expected:
    raise SystemExit(f"commuter row count mismatch: expected {expected}, found {actual}")

print(f"commuter rows: {actual}")
PY
}

stage_station() {
  stage_header "STATION"

  run_cmd "$PYTHON" - "$STATION_CSV" "$STATION_CSV_NAME" "$STATION_NODE" <<'PY'
import csv
import sys
from pathlib import Path

station_path = Path(sys.argv[1])
station_name = sys.argv[2]
station_node = int(sys.argv[3])

station_path.parent.mkdir(parents=True, exist_ok=True)
with station_path.open("w", newline="", encoding="utf-8") as stream:
    writer = csv.writer(stream)
    writer.writerow(["station_id", "station_name", "node_id"])
    writer.writerow(["S1", station_name, station_node])
PY

  check_path "$STATION_CSV" "station CSV"
}

stage_matrix() {
  stage_header "MATRIX"
  check_path "$COMMUTERS_CSV" "commuter CSV"
  check_path "$NETWORK_GRAPH_SPEED" "network speed graph"
  check_path "$LABEL_PREFIX.dorder" "label order output"
  check_path "$LABEL_PREFIX.dlabel" "label payload output"
  ensure_binary bin/dump_distance_matrix "bin/dump_distance_matrix"

  run_cmd mkdir -p "$MATRIX_DIR"
  run_cmd bin/dump_distance_matrix \
    --labels "$LABEL_PREFIX" \
    --nodes "$COMMUTERS_CSV" \
    --station "$STATION_NODE" \
    --speed "$NETWORK_GRAPH_SPEED" \
    --out-dir "$MATRIX_DIR"

  for path in \
    "$MATRIX_DIR/nodes.txt" \
    "$MATRIX_DIR/distances.npy" \
    "$MATRIX_DIR/duration_25kmph.npy" \
    "$MATRIX_DIR/duration_30kmph.npy" \
    "$MATRIX_DIR/duration_45kmph.npy" \
    "$MATRIX_DIR/duration_70kmph.npy" \
    "$MATRIX_DIR/duration_80kmph.npy"; do
    check_path "$path" "matrix output"
  done
}

stage_validate() {
  stage_header "VALIDATE"
  check_path "$COMMUTERS_CSV" "commuter CSV"
  check_path "$MATRIX_DIR/nodes.txt" "matrix nodes"
  check_path "$MATRIX_DIR/distances.npy" "matrix distances"

  run_cmd "$PYTHON" - \
    "$COMMUTERS_CSV" \
    "$MATRIX_DIR" \
    "$EXPECTED_COMMUTERS" \
    "$STATION_NODE" <<'PY'
import csv
import sys
from pathlib import Path

import numpy as np

commuter_path = Path(sys.argv[1])
matrix_dir = Path(sys.argv[2])
expected = int(sys.argv[3])
station_node = int(sys.argv[4])

with commuter_path.open(newline="", encoding="utf-8") as stream:
    rows = list(csv.DictReader(stream))

origins = [int(row["origin_node"]) for row in rows]
nodes = [int(value) for value in (matrix_dir / "nodes.txt").read_text(encoding="utf-8").splitlines() if value.strip()]
distances = np.load(matrix_dir / "distances.npy")

if len(origins) != expected:
    raise SystemExit(f"commuter count mismatch: expected {expected}, found {len(origins)}")
if distances.shape != (expected + 1, expected + 1):
    raise SystemExit(f"matrix shape mismatch: expected {(expected + 1, expected + 1)}, found {distances.shape}")
if not nodes:
    raise SystemExit("matrix nodes.txt is empty")
if nodes[0] != station_node:
    raise SystemExit(f"station node mismatch: expected {station_node}, found {nodes[0]}")
if nodes[1:] != origins:
    raise SystemExit("matrix nodes after station do not match commuter origin_node order")
if len(origins) != len(set(origins)):
    raise SystemExit("duplicate origins found in commuter CSV")

km = distances[1:, 0] / 1_000_000
median, p90, p95, p99 = np.percentile(km, [50, 90, 95, 99])
max_km = float(km.max())
above_5 = int((km > 5).sum())
above_8 = int((km > 8).sum())
above_10 = int((km > 10).sum())

print(f"commuter count: {len(origins)}")
print(f"matrix shape: {distances.shape}")
print(f"station node: {nodes[0]}")
print(f"duplicate origins: {len(origins) - len(set(origins))}")
print(
    "median/p90/p95/p99/max network station distance (km):",
    f"{median:.2f}",
    f"{p90:.2f}",
    f"{p95:.2f}",
    f"{p99:.2f}",
    f"{max_km:.2f}",
)
print(f">5 km / >8 km / >10 km: {above_5} / {above_8} / {above_10}")

reference = (3.21, 4.34, 4.86, 7.28, 8.20)
observed = (float(median), float(p90), float(p95), float(p99), max_km)
labels = ("median", "p90", "p95", "p99", "max")
for label, ref_value, obs_value in zip(labels, reference, observed):
    if abs(obs_value - ref_value) > 0.15:
        print(f"WARN: {label} differs from reference by more than 0.15 km: {obs_value:.2f} vs {ref_value:.2f}")
PY
}

stage_smoke() {
  stage_header "SMOKE"
  check_path "$SMOKE_SCRIPT" "smoke helper"
  check_path "$COMMUTERS_CSV" "commuter CSV"
  check_path "$STATION_CSV" "station CSV"
  check_path "$MATRIX_DIR/distances.npy" "matrix distances"
  check_path "$BASE_CONFIG" "base config"

  if [[ "$OUTPUT_MODE_TEST" == "1" ]]; then
    die "Smoke uses production-path orchestration; rerun with --skip-smoke or use --stage compare after sandbox generation."
  fi

  run_cmd bash "$SMOKE_SCRIPT"
}

stage_compare() {
  stage_header "COMPARE"

  if [[ "$TEST_OUTPUT_ROOT" == "" ]]; then
    if [[ "$INPUTS_DIR" == "$PROD_INPUTS_DIR" || "$DATASET_DIR" == "$PROD_DATASET_DIR" || "$LABEL_PREFIX" == "$PROD_LABEL_PREFIX" || "$MATRIX_DIR" == "$PROD_MATRIX_DIR" ]]; then
      die "Compare requires sandbox outputs. Use --test-output-root or set distinct --inputs-dir/--dataset-dir/--matrix-dir/--label-prefix values."
    fi
  fi

  compare_csv_counts() {
    local label="$1"
    local prod_path="$2"
    local test_path="$3"

    run_cmd "$PYTHON" - "$label" "$prod_path" "$test_path" <<'PY'
import csv
import sys
from pathlib import Path

label, prod_path, test_path = sys.argv[1:4]

def row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as stream:
        return sum(1 for _ in csv.DictReader(stream))

prod = row_count(Path(prod_path))
test = row_count(Path(test_path))
print(f"{label}: production={prod} test={test} match={prod == test}")
if prod != test:
    raise SystemExit(f"{label} row count mismatch")
PY
  }

  compare_json_fields() {
    local label="$1"
    local prod_path="$2"
    local test_path="$3"
    shift 3

    run_cmd "$PYTHON" - "$label" "$prod_path" "$test_path" "$@" <<'PY'
import json
import sys
from pathlib import Path

label = sys.argv[1]
prod_path = Path(sys.argv[2])
test_path = Path(sys.argv[3])
fields = sys.argv[4:]

def lookup(payload, dotted_key):
    current = payload
    for part in dotted_key.split('.'):
        current = current[part]
    return current

prod = json.loads(prod_path.read_text(encoding="utf-8"))
test = json.loads(test_path.read_text(encoding="utf-8"))
all_match = True
for field in fields:
    prod_value = lookup(prod, field)
    test_value = lookup(test, field)
    match = prod_value == test_value
    print(f"{label}.{field}: production={prod_value!r} test={test_value!r} match={match}")
    all_match = all_match and match
if not all_match:
    raise SystemExit(f"{label} metadata mismatch")
PY
  }

  compare_matrix() {
    run_cmd "$PYTHON" - "$PROD_MATRIX_DIR" "$MATRIX_DIR" <<'PY'
import sys
from pathlib import Path

import numpy as np

prod_dir = Path(sys.argv[1])
test_dir = Path(sys.argv[2])

prod_nodes = [int(line) for line in (prod_dir / "nodes.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
test_nodes = [int(line) for line in (test_dir / "nodes.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
prod_dist = np.load(prod_dir / "distances.npy")
test_dist = np.load(test_dir / "distances.npy")

nodes_match = prod_nodes == test_nodes
shape_match = prod_dist.shape == test_dist.shape
print(f"matrix.nodes: match={nodes_match} prod_len={len(prod_nodes)} test_len={len(test_nodes)}")
print(f"matrix.distances.shape: match={shape_match} production={prod_dist.shape} test={test_dist.shape}")
if not nodes_match:
    raise SystemExit("matrix node order mismatch")
if not shape_match:
    raise SystemExit("matrix distances shape mismatch")

if np.array_equal(prod_dist, test_dist):
    print("matrix.distances: exact equality")
else:
    max_abs = int(np.max(np.abs(prod_dist.astype(np.int64) - test_dist.astype(np.int64))))
    print(f"matrix.distances: max_abs_diff={max_abs}")
    if max_abs != 0:
        raise SystemExit("matrix distances differ")
PY
  }

  compare_csv_counts "commuters" "$PROD_COMMUTERS_CSV" "$COMMUTERS_CSV"
  compare_csv_counts "candidate_nodes" "$PROD_CANDIDATE_NODES" "$CANDIDATE_NODES"
  compare_csv_counts "candidate_points" "$PROD_CANDIDATE_POINTS" "$CANDIDATE_POINTS"
  compare_csv_counts "candidate_mapping" "$PROD_CANDIDATE_MAPPING" "$CANDIDATE_MAPPING"

  compare_json_fields "network_metadata" "$PROD_NETWORK_METADATA" "$NETWORK_METADATA" \
    station raw_nodes raw_edges compact_node_count nodes distance_edges_written time_edges_written speed_edges_written

  compare_json_fields "candidate_metadata" "$PROD_CANDIDATE_METADATA" "$CANDIDATE_METADATA" \
    walking_threshold_m max_station_distance_m raw_candidates kept_candidate_rows unique_candidate_road_nodes \
    removed_by_walking_threshold removed_by_outer_catchment

  compare_json_fields "commuter_metadata" "$PROD_COMMUTERS_METADATA" "$COMMUTERS_METADATA" \
    source station_name destination_node stop_ids stop_id_column year week date pickup_buffer_minutes seed \
    feasible_commuters output_commuters commuters_written origin_candidate_source origin_sampling_mode \
    origin_sampling_method residential_address_based origin_generation_method

  compare_matrix
}

print_summary() {
  echo
  echo "Summary"
  echo "Generated or refreshed key files:"
  echo "  $NETWORK_GRAPH_DIST"
  echo "  $NETWORK_GRAPH_SPEED"
  echo "  $NETWORK_GRAPH_TIME"
  echo "  $NETWORK_NODES"
  echo "  $LABEL_PREFIX.dorder"
  echo "  $LABEL_PREFIX.dlabel"
  echo "  $CANDIDATE_NODES"
  echo "  $COMMUTERS_CSV"
  echo "  $STATION_CSV"
  echo "  $MATRIX_DIR/nodes.txt"
  echo "  $MATRIX_DIR/distances.npy"
  echo "  $MATRIX_DIR/duration_25kmph.npy"
  echo "  $MATRIX_DIR/duration_30kmph.npy"
  echo "  $MATRIX_DIR/duration_45kmph.npy"
  echo "  $MATRIX_DIR/duration_70kmph.npy"
  echo "  $MATRIX_DIR/duration_80kmph.npy"
  echo "Active inputs dir:  $INPUTS_DIR"
  echo "Active dataset dir: $DATASET_DIR"
  echo "Active matrix dir:  $MATRIX_DIR"
  echo "Next suggested commands:"
  echo "  bash experiments/scripts/run_fleet_composition_grid.sh"
  echo "  bash experiments/scripts/run_capacity_sensitivity_representative.sh"
  echo "  bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh"
}

stage="all"
clean_generated=0
clean_matrix=0
rebuild_labels=0
skip_smoke=0
explicit_inputs_dir=0
explicit_dataset_dir=0
explicit_matrix_dir=0
explicit_label_prefix=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --stage)
      [[ $# -ge 2 ]] || die "--stage requires a value"
      stage="$2"
      shift 2
      ;;
    --inputs-dir)
      [[ $# -ge 2 ]] || die "--inputs-dir requires a value"
      INPUTS_DIR="$2"
      explicit_inputs_dir=1
      shift 2
      ;;
    --dataset-dir)
      [[ $# -ge 2 ]] || die "--dataset-dir requires a value"
      DATASET_DIR="$2"
      explicit_dataset_dir=1
      shift 2
      ;;
    --matrix-dir)
      [[ $# -ge 2 ]] || die "--matrix-dir requires a value"
      MATRIX_DIR="$2"
      explicit_matrix_dir=1
      shift 2
      ;;
    --label-prefix)
      [[ $# -ge 2 ]] || die "--label-prefix requires a value"
      LABEL_PREFIX="$2"
      explicit_label_prefix=1
      shift 2
      ;;
    --test-output-root)
      [[ $# -ge 2 ]] || die "--test-output-root requires a value"
      configure_test_output_root "$2"
      shift 2
      ;;
    --clean-generated)
      clean_generated=1
      shift
      ;;
    --clean-matrix)
      clean_matrix=1
      shift
      ;;
    --rebuild-labels)
      rebuild_labels=1
      shift
      ;;
    --skip-smoke)
      skip_smoke=1
      shift
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

case "$stage" in
  network|labels|candidates|commuters|station|matrix|validate|compare|smoke|all)
    ;;
  *)
    die "Unknown stage: $stage"
    ;;
esac

ensure_python
refresh_paths

if [[ "$stage" == "all" && "$OUTPUT_MODE_TEST" == "1" && "$skip_smoke" != "1" ]]; then
  die "Sandbox output mode is active; add --skip-smoke or run --stage compare after the rebuild."
fi

if [[ "$clean_generated" == "1" ]]; then
  cleanup_generated
fi
if [[ "$clean_matrix" == "1" ]]; then
  cleanup_matrix
fi
if [[ "$rebuild_labels" == "1" ]]; then
  cleanup_labels
fi

if [[ "$stage" == "all" ]]; then
  stage_network
  stage_labels
  stage_candidates
  stage_commuters
  stage_station
  stage_matrix
  stage_validate
  if [[ "$skip_smoke" == "1" ]]; then
    echo
    echo "Skipping smoke stage because --skip-smoke was set."
  else
    stage_smoke
  fi
else
  case "$stage" in
    network)
      stage_network
      ;;
    labels)
      stage_labels
      ;;
    candidates)
      stage_candidates
      ;;
    commuters)
      stage_commuters
      ;;
    station)
      stage_station
      ;;
    matrix)
      stage_matrix
      ;;
    validate)
      stage_validate
      ;;
    compare)
      stage_compare
      ;;
    smoke)
      stage_smoke
      ;;
  esac
fi

print_summary
