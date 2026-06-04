#!/usr/bin/env bash
set -euo pipefail

TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/commuters.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/stations.csv
#   MATRICES_DIR  default: $ROOT/dataset/MELTON/melton_generic_matrix
COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_generic_matrix}"
DRY_RUN=${DRY_RUN:-0}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

EXPERIMENT="tw_mode_comparison_224seats"
RESULTS_DIR="$ROOT/experiments/results/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
LABELS=(${LABELS_OVERRIDE:-individual fixed_5min fixed_10min fixed_15min fixed_20min fixed_30min fixed_60min})
N_SEEDS=${N_SEEDS:-15}
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-180}
BUFFER_MINUTES=${BUFFER_MINUTES:-0}

JOB_FILE=$(mktemp /tmp/pyvrp_tw_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
for label in "${LABELS[@]}"; do
    for seed in $(seq 1 "$N_SEEDS"); do echo "$label $seed"; done
done > "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP TIME-WINDOW MODE COMPARISON                       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Fleet    : 56S/28M/14C/7MB (224 seats, balanced 25/25/25/25 seat share)"
echo "  Demand   : 1465 Myki commuters  |  Time: ${TIME_LIMIT_SECONDS}s  |  Buffer: ${BUFFER_MINUTES} min"
echo "  Distance-band penalty: none"
echo "  Experiment folder: $EXPERIMENT"
echo "  Conditions: ${LABELS[*]}"
echo "  Seeds    : $N_SEEDS per condition  |  Total: $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"
[[ $DRY_RUN == 1 ]] && { echo "  DRY RUN"; cat "$JOB_FILE"; exit 0; }

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."

write_config() {
    local label="$1"
    local mode="$2"
    local interval="${3:-}"
    local tw_json
    if [[ "$mode" == "individual" ]]; then
        tw_json="{\"mode\":\"individual\",\"buffer_before_deadline_minutes\":${BUFFER_MINUTES}}"
    else
        tw_json="{\"mode\":\"fixed_slots\",\"interval_minutes\":${interval},\"start_time_minutes\":420,\"end_time_minutes\":570,\"buffer_before_deadline_minutes\":${BUFFER_MINUTES}}"
    fi

cat > "$CONFIGS_DIR/${label}.json" << JSEOF
{
  "experiment_name": "tw_mode_${label}",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": ${tw_json},
  "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  ${label}.json"
}

for label in "${LABELS[@]}"; do
    case "$label" in
        individual) write_config "$label" individual ;;
        fixed_5min) write_config "$label" fixed_slots 5 ;;
        fixed_10min) write_config "$label" fixed_slots 10 ;;
        fixed_15min) write_config "$label" fixed_slots 15 ;;
        fixed_20min) write_config "$label" fixed_slots 20 ;;
        fixed_30min) write_config "$label" fixed_slots 30 ;;
        fixed_60min) write_config "$label" fixed_slots 60 ;;
        *) echo "ERROR: Unknown label '$label'"; exit 1 ;;
    esac
done

export CONFIGS_DIR RESULTS_DIR PYVRP_SCRIPT COMMUTERS_CSV STATIONS_CSV MATRICES_DIR

PROG_COUNT=$(mktemp /tmp/pyvrp_prog.XXXXXX)
PROG_LOCK=$(mktemp /tmp/pyvrp_lock.XXXXXX)
echo "0" > "$PROG_COUNT"
trap "rm -f $JOB_FILE $PROG_COUNT $PROG_LOCK" EXIT

progress_tick() {
    local lock_dir="$PROG_LOCK.lock"
    while ! mkdir "$lock_dir" 2>/dev/null; do sleep 0.02; done
    local done; done=$(<"$PROG_COUNT")
    done=$((done + 1))
    echo "$done" > "$PROG_COUNT"
    printf "[progress] %d/%d completed\n" "$done" "$TOTAL"
    rmdir "$lock_dir"
}
export -f progress_tick
export PROG_COUNT PROG_LOCK TOTAL

run_one() {
    local label="$1" seed="$2"
    local out_dir="$RESULTS_DIR/$label/run_$seed"
    local log="$out_dir/simulation.log"
    if [[ -f "$out_dir/metrics.json" ]] && [[ -s "$out_dir/metrics.json" ]] && \
       [[ -f "$out_dir/baseline.json" ]] && [[ -f "$out_dir/comparison.json" ]]; then
        printf "[%s seed_%s] already done, skipping\n" "$label" "$seed"
        progress_tick; return 0
    fi
    mkdir -p "$out_dir"
    cp "$CONFIGS_DIR/${label}.json" "$out_dir/config.json"
    printf "[%s seed_%s] starting...\n" "$label" "$seed"
    if python3 "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
            "$out_dir/assignments.csv" "$out_dir/av_routes.csv" \
            "$CONFIGS_DIR/${label}.json" \
            "$out_dir/baseline.json" "$out_dir/metrics.json" "$out_dir/comparison.json" \
            "$seed" > "$log" 2>&1; then
        printf "[%s seed_%s] done\n" "$label" "$seed"
    else
        printf "[%s seed_%s] FAILED — see %s\n" "$label" "$seed" "$log" >&2
    fi
    progress_tick
}
export -f run_one

START=$(date +%s)
parallel --jobs "$PARALLEL_JOBS" --colsep ' ' --eta run_one {1} {2} :::: "$JOB_FILE"
END=$(date +%s)

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        EXPERIMENT COMPLETE                                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
printf "  Total time: %ds\n" $((END - START))
FAILED=$(find "$RESULTS_DIR" -name "simulation.log" \
    | xargs grep -l "Error\|Traceback" 2>/dev/null | wc -l | tr -d " ")
[[ "$FAILED" -gt 0 ]] && echo "  WARNING: $FAILED run(s) may have failed" \
    || echo "  No failures detected"
echo ""

echo "  Next: python3 experiments/scripts/plot_tw_mode_comparison.py"
