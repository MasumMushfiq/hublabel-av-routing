#!/usr/bin/env bash
set -euo pipefail

# ARCHIVED / NOT ACTIVE FOR CORRECTED FOOTSCRAY PAPER WORKFLOW.
# Retained only for historical legacy Melton capacity diagnostics/reproducibility.
# Do not use for corrected Footscray experiments.

# Capacity sensitivity for selected representative fleets.
# Paper setup:
# - residential-origin demand
# - PyVRP/HGS
# - 300s solver time limit
# - 15 seeds
# - fixed 20-minute train-aligned slots
# - 0-minute buffer
# - no distance-band penalty
# - raw-distance objective
#
# Fleets:
#   balanced      = S25/M25/C25/MB25
#   vmt_oriented  = S25/M0/C0/MB75
#   low_emission  = S25/M75/C0/MB0
#   all_car       = S0/M0/C100/MB0
#
# Capacity scales:
#   x0.90, x1.00, x1.10, x1.25 relative to the 224-seat reference.
#
# Usage:
#   bash experiments/scripts/run_capacity_sensitivity_representative.sh [--dry-run]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$ROOT_DIR"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

SIM_SCRIPT="${SIM_SCRIPT:-python/simulate_first_mile_pyvrp.py}"

RESULTS_ROOT="${RESULTS_ROOT:-$ROOT/experiments/results/capacity_sensitivity_representative_residential}"
CONFIG_ROOT="${CONFIG_ROOT:-${RESULTS_ROOT}/configs}"

TIME_LIMIT="${TIME_LIMIT:-300}"
NUM_SEEDS="${NUM_SEEDS:-15}"

# Dry-run flag: support env var or first positional arg
DRY_RUN=${DRY_RUN:-0}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# Resume existing completed runs? (1 = skip completed, 0 = rerun)
RESUME="${RESUME:-1}"

# Number of parallel jobs: prefer JOBS, fallback to PARALLEL_JOBS, default 9
# Default to 10 jobs for overnight runs unless overridden
JOBS="${JOBS:-${PARALLEL_JOBS:-10}}"

# Always create roots (allow inspecting configs during dry-run)
mkdir -p "$RESULTS_ROOT"
mkdir -p "$CONFIG_ROOT"

# ---------------------------------------------------------------------
# Base data paths. Override with COMMUTERS_CSV, STATIONS_CSV, or MATRICES_DIR.
# Residential-origin demand is the main paper setting. Use generic
# reachable-node demand only through explicit overrides or clearly named
# robustness output folders.
# Default matrices: $ROOT/dataset/MELTON/melton_residential_matrix.
# ---------------------------------------------------------------------

COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters_residential.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_residential_matrix}"
BASE_CONFIG="${BASE_CONFIG:-$ROOT/config/legacy_melton_base_config.json}"
if [[ "$BASE_CONFIG" != /* ]]; then
  BASE_CONFIG="$ROOT/$BASE_CONFIG"
fi

# ---------------------------------------------------------------------
# Fleet definitions.
#
# Counts are chosen to preserve the intended seat shares as closely as
# possible at each capacity scale.
#
# Reference 224-seat compositions:
# Balanced:     56S / 28M / 14C / 7MB    = 224 seats
# VMT-oriented: 56S / 0M  / 0C  / 21MB   = 224 seats
# Low-emission: 56S / 84M / 0C  / 0MB    = 224 seats
# All-car:      0S  / 0M  / 56C / 0MB    = 224 seats
#
# Scaled counts:
#
# x0.90 target approx 202 seats
# x1.00 target 224 seats
# x1.10 target approx 246 seats
# x1.25 target 280 seats
# ---------------------------------------------------------------------

declare -a FLEETS=(
  "balanced"
  "vmt_oriented"
  "low_emission"
  "all_car"
)

declare -a SCALES=(
  "x0.90"
  "x1.00"
  "x1.10"
  "x1.25"
)

get_counts() {
  local fleet="$1"
  local scale="$2"

  # Output format:
  # scooters mopeds cars minibuses total_seats

  if [[ "$fleet" == "balanced" ]]; then
    case "$scale" in
      "x0.90") echo "50 25 13 6 200" ;;
      "x1.00") echo "56 28 14 7 224" ;;
      "x1.10") echo "61 31 15 8 247" ;;
      "x1.25") echo "70 35 17 9 280" ;;
      *) echo "Unknown scale: $scale" >&2; exit 1 ;;
    esac

  elif [[ "$fleet" == "vmt_oriented" ]]; then
    case "$scale" in
      # Seat shares: S25/M0/C0/MB75
      "x0.90") echo "50 0 0 19 202" ;;
      "x1.00") echo "56 0 0 21 224" ;;
      "x1.10") echo "62 0 0 23 246" ;;
      "x1.25") echo "70 0 0 26 278" ;;
      *) echo "Unknown scale: $scale" >&2; exit 1 ;;
    esac

  elif [[ "$fleet" == "low_emission" ]]; then
    case "$scale" in
      # Seat shares: S25/M75/C0/MB0
      "x0.90") echo "50 76 0 0 202" ;;
      "x1.00") echo "56 84 0 0 224" ;;
      "x1.10") echo "62 93 0 0 248" ;;
      "x1.25") echo "70 105 0 0 280" ;;
      *) echo "Unknown scale: $scale" >&2; exit 1 ;;
    esac

  elif [[ "$fleet" == "all_car" ]]; then
    case "$scale" in
      # Seat shares: S0/M0/C100/MB0
      "x0.90") echo "0 0 50 0 200" ;;
      "x1.00") echo "0 0 56 0 224" ;;
      "x1.10") echo "0 0 62 0 248" ;;
      "x1.25") echo "0 0 70 0 280" ;;
      *) echo "Unknown scale: $scale" >&2; exit 1 ;;
    esac

  else
    echo "Unknown fleet: $fleet" >&2
    exit 1
  fi
}

make_config() {
  local fleet="$1"
  local scale="$2"
  local config_path="$3"

  read -r n_scooter n_moped n_car n_minibus total_seats < <(get_counts "$fleet" "$scale")

  "$PYTHON_BIN" - "$BASE_CONFIG" "$config_path" "$fleet" "$scale" "$TIME_LIMIT" "$n_scooter" "$n_moped" "$n_car" "$n_minibus" "$total_seats" <<'PYEOF'
import copy
import json
import sys

base_config, config_path, fleet, scale = sys.argv[1:5]
time_limit = int(sys.argv[5])
counts = {
    "scooter": int(sys.argv[6]),
    "moped": int(sys.argv[7]),
    "car": int(sys.argv[8]),
    "minibus": int(sys.argv[9]),
}
total_seats = int(sys.argv[10])

labels = {
    "balanced": ("Balanced", "S25/M25/C25/MB25"),
    "vmt_oriented": ("VMT-Opt", "S25/M0/C0/MB75"),
    "low_emission": ("Low-Emission", "S25/M75/C0/MB0"),
    "all_car": ("All-Car", "S0/M0/C100/MB0"),
}

with open(base_config, "r", encoding="utf-8") as f:
    cfg = json.load(f)

base_vehicle_by_name = {
    vehicle["name"].lower(): vehicle
    for vehicle in cfg["fleet"]["vehicle_types"]
}
missing = [name for name in counts if name not in base_vehicle_by_name]
if missing:
    raise ValueError(f"Base config missing vehicle definitions: {missing}")

cfg["experiment_name"] = f"capacity_sensitivity_{fleet}_{scale}"
cfg["capacity_metadata"] = {
    "fleet": fleet,
    "scale": scale,
    "total_fleet_seats": total_seats,
    "scooter_count": counts["scooter"],
    "moped_count": counts["moped"],
    "car_count": counts["car"],
    "minibus_count": counts["minibus"],
    "display_label": labels[fleet][0],
    "seat_share_label": labels[fleet][1],
}
cfg.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
cfg["fleet"]["vehicle_types"] = []

for name in ["scooter", "moped", "car", "minibus"]:
    count = counts[name]
    if count <= 0:
        continue
    vehicle_cfg = copy.deepcopy(base_vehicle_by_name[name])
    vehicle_cfg["fleet_size"] = count
    cfg["fleet"]["vehicle_types"].append(vehicle_cfg)

with open(config_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
PYEOF
}

echo "Running representative fleet capacity sensitivity"
echo "Results root: ${RESULTS_ROOT}"
echo "Config root:  ${CONFIG_ROOT}"
echo "Base config:  ${BASE_CONFIG}"
echo "Time limit:   ${TIME_LIMIT}s"
echo "Seeds:        ${NUM_SEEDS}"
echo "Dry run:      ${DRY_RUN}"
echo "Resume:       ${RESUME}"
echo "Parallel jobs:${JOBS}"
echo

# Validate prereqs before generating configs or jobs.
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: Missing command: $PYTHON_BIN"; exit 1; }
for f in "$SIM_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
  [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

JOB_FILE=$(mktemp /tmp/capacity_sensitivity_jobs.XXXXXX)
trap '[[ -f "$JOB_FILE" ]] && rm -f "$JOB_FILE"' EXIT
for fleet in "${FLEETS[@]}"; do
  for scale in "${SCALES[@]}"; do
    read -r n_scooter n_moped n_car n_minibus total_seats < <(get_counts "$fleet" "$scale")
    for seed in $(seq 1 "$NUM_SEEDS"); do
      # Format: fleet scale seed total_seats config_path run_dir
      config_path="${CONFIG_ROOT}/${fleet}_${scale}.json"
      run_dir="${RESULTS_ROOT}/${fleet}/${scale}/seed_${seed}"
      printf "%s %s %s %s %s %s\n" "$fleet" "$scale" "$seed" "$total_seats" "$config_path" "$run_dir" >> "$JOB_FILE"
    done
  done
done

# Count jobs
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')
echo "Total jobs:   ${TOTAL}"

# Ensure config files exist before running jobs: create them now
while read -r fleet scale seed seats config_path run_dir; do
  make_config "$fleet" "$scale" "$config_path"
done < "$JOB_FILE"

PROG_COUNT=$(mktemp /tmp/capacity_sensitivity_prog.XXXXXX)
PROG_LOCK=$(mktemp /tmp/capacity_sensitivity_lock.XXXXXX)
echo "0" > "$PROG_COUNT"
trap '[[ -f "$JOB_FILE" ]] && rm -f "$JOB_FILE"; [[ -f "$PROG_COUNT" ]] && rm -f "$PROG_COUNT"; [[ -f "$PROG_LOCK" ]] && rm -f "$PROG_LOCK"' EXIT

progress_tick() {
  local lock_dir="$PROG_LOCK.lock"
  while ! mkdir "$lock_dir" 2>/dev/null; do sleep 0.02; done
  local done
  done=$(<"$PROG_COUNT")
  done=$((done + 1))
  echo "$done" > "$PROG_COUNT"
  printf "[progress] %d/%d completed\n" "$done" "$TOTAL"
  rmdir "$lock_dir"
}
export -f progress_tick
export PROG_COUNT PROG_LOCK TOTAL

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY RUN  : listing jobs only"
  echo "Jobs (fleet scale seed seats config_path run_dir):"
  cat "$JOB_FILE"
  exit 0
fi

run_one() {
  local fleet="$1" scale="$2" seed="$3" seats="$4" config_path="$5" run_dir="$6"
  local log_file="$run_dir/simulation.log"
  mkdir -p "$run_dir"
  if [[ "$RESUME" == "1" && -f "${run_dir}/metrics.json" ]] && \
     [[ -s "${run_dir}/metrics.json" ]] && \
     [[ -f "${run_dir}/baseline.json" ]] && \
     [[ -f "${run_dir}/comparison.json" ]]; then
    echo "[SKIP] ${fleet} ${scale} seed=${seed} already complete"
    progress_tick
    return 0
  fi
  cp "$config_path" "$run_dir/config.json"
  echo "[RUN] fleet=${fleet} scale=${scale} seats=${seats} seed=${seed}"
  if "${PYTHON_BIN}" "${SIM_SCRIPT}" \
    "${COMMUTERS_CSV}" "${STATIONS_CSV}" "${MATRICES_DIR}" \
    "${run_dir}/assignments.csv" "${run_dir}/av_routes.csv" \
    "${config_path}" \
    "${run_dir}/baseline.json" "${run_dir}/metrics.json" "${run_dir}/comparison.json" \
    "${seed}" > "$log_file" 2>&1; then
    echo "[RUN] fleet=${fleet} scale=${scale} seed=${seed} done"
  else
    echo "[RUN] fleet=${fleet} scale=${scale} seed=${seed} FAILED — see ${log_file}" >&2
  fi
  progress_tick
}

# Export variables used by run_one (parallel spawns subshells)
export PYTHON_BIN SIM_SCRIPT COMMUTERS_CSV STATIONS_CSV MATRICES_DIR
export RESULTS_ROOT CONFIG_ROOT RESUME PROG_COUNT PROG_LOCK TOTAL
export -f run_one

START=$(date +%s)

if command -v parallel &>/dev/null; then
  parallel --jobs "$JOBS" --colsep ' ' --eta run_one {1} {2} {3} {4} {5} {6} :::: "$JOB_FILE"
else
  echo "WARNING: GNU parallel not found, running sequentially"
  while IFS=' ' read -r fleet scale seed seats config_path run_dir; do
    run_one "$fleet" "$scale" "$seed" "$seats" "$config_path" "$run_dir"
  done < "$JOB_FILE"
fi

END=$(date +%s)

echo
echo "Done. Results written to: ${RESULTS_ROOT}"
printf "Total time: %ds\n" $((END - START))
