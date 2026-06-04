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

EXPERIMENT="time_limit_calibration_224seats"
RESULTS_DIR="$ROOT/experiments/results/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
TIME_LIMITS=(${TIME_LIMITS_OVERRIDE:-10 20 30 60 120 180 240 300 450 600})
N_SEEDS=${N_SEEDS:-10}
# TIME_LIMITS=(10 20 30 60 120 180 240 300 450 600)
# N_SEEDS=10

JOB_FILE=$(mktemp /tmp/pyvrp_tl_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
for tl in "${TIME_LIMITS[@]}"; do
    for seed in $(seq 1 "$N_SEEDS"); do echo "$tl $seed"; done
done > "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP TIME LIMIT CALIBRATION                            ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Fleet    : 56S/28M/14C/7MB (224 seats, balanced 25/25/25/25 seat share)"
echo "  Demand   : 1465 Myki commuters  |  Buffer: 0 min  |  Distance-band penalty: none"
echo "  Limits   : ${TIME_LIMITS[*]} seconds  |  Seeds: $N_SEEDS"
echo "  Experiment folder: $EXPERIMENT"
echo "  Total    : $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"
[[ $DRY_RUN == 1 ]] && { echo "  DRY RUN"; cat "$JOB_FILE"; exit 0; }

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."
cat > "$CONFIGS_DIR/tl_10s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_10s",
  "fleet": {"vehicle_types": [
    {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
    {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
    {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
    {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 10},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_10s.json"
cat > "$CONFIGS_DIR/tl_20s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_20s",
  "fleet": {"vehicle_types": [
    {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
    {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
    {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
    {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 20},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_20s.json"
cat > "$CONFIGS_DIR/tl_30s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_30s",
  "fleet": {"vehicle_types": [
    {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
    {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
    {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
    {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 30},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_30s.json"
cat > "$CONFIGS_DIR/tl_60s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_60s",
  "fleet": {"vehicle_types": [
    {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
    {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
    {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
    {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 60},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_60s.json"
cat > "$CONFIGS_DIR/tl_120s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_120s",
  "fleet": {"vehicle_types": [
    {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
    {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
    {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
    {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 120},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_120s.json"
cat > "$CONFIGS_DIR/tl_180s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_180s",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 180},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_180s.json"
cat > "$CONFIGS_DIR/tl_240s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_240s",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 240},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_240s.json"
cat > "$CONFIGS_DIR/tl_300s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_300s",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 300},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_300s.json"
cat > "$CONFIGS_DIR/tl_450s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_450s",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 450},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_450s.json"
cat > "$CONFIGS_DIR/tl_600s.json" << 'JSEOF'
{
  "experiment_name": "time_limit_calibration_600s",
  "fleet": {"vehicle_types": [
      {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
      {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
      {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
      {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
  ]},
  "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
  "solver_config": {"time_limit_seconds": 600},
  "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
  "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
    echo "  tl_600s.json"
echo ""
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
    local tl="$1" seed="$2"
    local out_dir="$RESULTS_DIR/tl_${tl}s/run_$seed"
    local log="$out_dir/simulation.log"
    if [[ -f "$out_dir/metrics.json" ]] && [[ -s "$out_dir/metrics.json" ]] && \
       [[ -f "$out_dir/baseline.json" ]] && [[ -f "$out_dir/comparison.json" ]]; then
        printf "[tl_%ss seed_%s] already done, skipping\n" "$tl" "$seed"
        progress_tick; return 0
    fi
    mkdir -p "$out_dir"
    cp "$CONFIGS_DIR/tl_${tl}s.json" "$out_dir/config.json"
    printf "[tl_%ss seed_%s] starting...\n" "$tl" "$seed"
    if python3 "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
            "$out_dir/assignments.csv" "$out_dir/av_routes.csv" \
            "$CONFIGS_DIR/tl_${tl}s.json" \
            "$out_dir/baseline.json" "$out_dir/metrics.json" "$out_dir/comparison.json" \
            "$seed" > "$log" 2>&1; then
        printf "[tl_%ss seed_%s] done\n" "$tl" "$seed"
    else
        printf "[tl_%ss seed_%s] FAILED — see %s\n" "$tl" "$seed" "$log" >&2
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

echo "  Next: python3 experiments/scripts/plot_time_limit_calibration.py"
