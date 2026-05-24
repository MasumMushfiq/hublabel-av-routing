#!/usr/bin/env bash
set -euo pipefail

# Capacity sensitivity for selected representative heterogeneous fleets.
# Paper setup:
# - PyVRP/HGS
# - 180s solver time limit
# - 15 seeds
# - fixed 20-minute train-aligned slots
# - 0-minute buffer
# - no distance-band penalty
# - raw-distance objective
#
# Fleets:
#   balanced      = S25/M25/C25/MB25
#   vmt_oriented  = S25/M25/C0/MB50
#   low_emission  = S25/M50/C0/MB25
#
# Capacity scales:
#   x0.90, x1.00, x1.10, x1.25 relative to the 224-seat reference.
#
# Usage:
#   bash experiments/scripts/run_capacity_sensitivity_representative.sh [--dry-run]

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"

SIM_SCRIPT="${SIM_SCRIPT:-python/simulate_first_mile_pyvrp.py}"

RESULTS_ROOT="${RESULTS_ROOT:-experiments/results/capacity_sensitivity_representative}"
CONFIG_ROOT="${CONFIG_ROOT:-${RESULTS_ROOT}/configs}"

TIME_LIMIT="${TIME_LIMIT:-180}"
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
# Base data paths.
# Adjust these only if your current runner uses different names.
# ---------------------------------------------------------------------

COMMUTERS_CSV="${COMMUTERS_CSV:-files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-files/matrices}"

# ---------------------------------------------------------------------
# Vehicle parameters.
# ---------------------------------------------------------------------
# Scooter: capacity 1, 25 km/h, 2.0 L/100km, petrol 2.35 kg/L
# Moped:   capacity 2, 45 km/h, 3.0 L/100km, petrol 2.35 kg/L
# Car:     capacity 4, 80 km/h, 11.1 L/100km, petrol 2.35 kg/L
# Minibus: capacity 8, 70 km/h, 14.0 L/100km, diesel 2.68 kg/L

# ---------------------------------------------------------------------
# Fleet definitions.
#
# Counts are chosen to preserve the intended seat shares as closely as
# possible at each capacity scale.
#
# Reference 224-seat compositions:
# Balanced:     56S / 28M / 14C / 7MB    = 224 seats
# VMT-oriented: 56S / 28M / 0C  / 14MB   = 224 seats
# Low-emission: 56S / 56M / 0C  / 7MB    = 224 seats
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
      # Seat shares: S25/M25/C0/MB50
      # x0.90: approximately 50 scooter seats, 50 moped seats, 100 minibus seats
      "x0.90") echo "50 25 0 13 204" ;;
      "x1.00") echo "56 28 0 14 224" ;;
      "x1.10") echo "62 31 0 15 244" ;;
      "x1.25") echo "70 35 0 18 284" ;;
      *) echo "Unknown scale: $scale" >&2; exit 1 ;;
    esac

  elif [[ "$fleet" == "low_emission" ]]; then
    case "$scale" in
      # Seat shares: S25/M50/C0/MB25
      # x0.90: approximately 50 scooter seats, 100 moped seats, 50 minibus seats
      "x0.90") echo "50 50 0 6 198" ;;
      "x1.00") echo "56 56 0 7 224" ;;
      "x1.10") echo "62 62 0 8 250" ;;
      "x1.25") echo "70 70 0 9 282" ;;
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

  {
    echo "{"
    echo "  \"experiment_name\": \"capacity_sensitivity_${fleet}_${scale}\","
    echo
    echo "  \"fleet\": {"
    echo "    \"vehicle_types\": ["

    local first_vehicle=1
    add_vehicle_type() {
      local name="$1"
      local count="$2"
      local capacity="$3"
      local speed="$4"
      local fuel="$5"
      local co2="$6"
      local lower="$7"
      local upper="$8"

      [[ "$count" -le 0 ]] && return 0

      if [[ "$first_vehicle" -eq 0 ]]; then
        echo "      ,"
      fi

      cat <<JSONEOF
      {
        "name": "${name}",
        "fleet_size": ${count},
        "capacity": ${capacity},
        "max_speed_kmph": ${speed},
        "fuel_l_per_100km": ${fuel},
        "co2_kg_per_liter": ${co2},
        "distance_band": {"lower_km": ${lower}, "upper_km": ${upper}},
        "fixed_cost_km_equiv": 0.0
      }
JSONEOF

      first_vehicle=0
    }

    add_vehicle_type "scooter" "$n_scooter" 1 25 2.0 2.35 0.0 2.0
    add_vehicle_type "moped" "$n_moped" 2 45 3.0 2.35 1.5 6.0
    add_vehicle_type "car" "$n_car" 4 80 11.1 2.35 4.0 12.0
    add_vehicle_type "minibus" "$n_minibus" 8 70 14.0 2.68 8.0 20.0

    echo
    echo "    ]"
    echo "  },"

    echo "  \"solver_config\": {"
    echo "    \"time_limit_seconds\": ${TIME_LIMIT}"
    echo "  },"
    echo
    echo "  \"time_window\": {"
    echo "    \"mode\": \"fixed_slots\","
    echo "    \"interval_minutes\": 20,"
    echo "    \"start_time_minutes\": 420,"
    echo "    \"end_time_minutes\": 570,"
    echo "    \"buffer_before_deadline_minutes\": 0"
    echo "  },"

    echo "  \"penalty_parameters\": {"
    echo "    \"alpha\": 1.0,"
    echo "    \"beta\": 1.0,"
    echo "    \"penalty_mode\": \"none\","
    echo "    \"preference_scale_m\": 500"
    echo "  },"

    echo "  \"baseline_parameters\": {"
    echo "    \"private_car_fuel_l_per_100km\": 11.1,"
    echo "    \"private_car_co2_kg_per_liter\": 2.35,"
    echo "    \"private_car_speed_kmph\": 80.0"
    echo "  }"
    echo "}"
  } > "$config_path"
}

echo "Running representative fleet capacity sensitivity"
echo "Results root: ${RESULTS_ROOT}"
echo "Config root:  ${CONFIG_ROOT}"
echo "Time limit:   ${TIME_LIMIT}s"
echo "Seeds:        ${NUM_SEEDS}"
echo "Dry run:      ${DRY_RUN}"
echo "Resume:       ${RESUME}"
echo "Parallel jobs:${JOBS}"
echo

# Validate prereqs before generating configs or jobs.
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: Missing command: $PYTHON_BIN"; exit 1; }
for f in "$SIM_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
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