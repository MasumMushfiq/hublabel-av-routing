#!/usr/bin/env bash
set -euo pipefail

TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
COMMUTERS_CSV="$ROOT/files/inputs/commuters.csv"
STATIONS_CSV="$ROOT/files/inputs/stations.csv"
MATRICES_DIR="$ROOT/files/matrices"
DRY_RUN=${DRY_RUN:-0}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# =============================================================================
# run_penalty_fleet_interaction.sh
# Compact penalty ablation: compare `none` vs `multiplicative` penalties
# across four fleet scales relative to the final 224-seat balanced baseline.
#
# Grid:
#   Penalty modes : none, multiplicative
#   Fleet scales  : x0.90 (200 seats), x1.00 (224 seats), x1.10 (247 seats), x1.25 (280 seats)
#   Seeds         : configurable (default 15)
#   Total         : 2 penalty modes × 4 fleet scales × N_SEEDS
# =============================================================================

EXPERIMENT="penalty_fleet_interaction_224seats"
RESULTS_DIR="$ROOT/experiments/results/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
# Defaults (can be overridden from environment)
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-180}
N_SEEDS=${N_SEEDS:-15}

LABELS=(none_x0.90 none_x1.00 none_x1.10 none_x1.25
        multiplicative_x0.90 multiplicative_x1.00 multiplicative_x1.10 multiplicative_x1.25)

JOB_FILE=$(mktemp /tmp/pyvrp_pfi_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
for label in "${LABELS[@]}"; do
    for seed in $(seq 1 "$N_SEEDS"); do echo "$label $seed"; done
done > "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP PENALTY MODE × FLEET SCALE (penalty ablation)     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Penalty modes: none, multiplicative"
echo "  Fleet scales : x0.90, x1.00, x1.10, x1.25"
echo "  Baseline     : x1.00 = 224 seats"
echo "  Fleet map    : x0.90=50S/25M/13C/6MB (200), x1.00=56S/28M/14C/7MB (224), x1.10=61S/31M/15C/8MB (247), x1.25=70S/35M/17C/9MB (280)"
echo "  Time limit   : ${TIME_LIMIT_SECONDS}s"
echo "  Experiment folder: $EXPERIMENT"
echo "  Seeds        : $N_SEEDS  |  Total jobs: $TOTAL  |  Parallel: $PARALLEL_JOBS workers"
[[ $DRY_RUN == 1 ]] && { echo "  DRY RUN"; cat "$JOB_FILE"; exit 0; }

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."

# none x0.90
cat > "$CONFIGS_DIR/none_x0.90.json" << JSEOF
{
    "experiment_name": "penalty_fleet_none_x0.90",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":50,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":25,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":13,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":6,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  none_x0.90.json"

# none x1.00 (224-seat balanced baseline)
cat > "$CONFIGS_DIR/none_x1.00.json" << JSEOF
{
    "experiment_name": "penalty_fleet_none_x1.00",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  none_x1.00.json"

# none x1.10 (247 seats)
cat > "$CONFIGS_DIR/none_x1.10.json" << JSEOF
{
    "experiment_name": "penalty_fleet_none_x1.10",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":61,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":31,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":15,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":8,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  none_x1.10.json"

# none x1.25 (280 seats)
cat > "$CONFIGS_DIR/none_x1.25.json" << JSEOF
{
    "experiment_name": "penalty_fleet_none_x1.25",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":70,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":35,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":17,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":9,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"none","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  none_x1.25.json"
cat > "$CONFIGS_DIR/multiplicative_x0.90.json" << JSEOF
{
    "experiment_name": "penalty_fleet_multiplicative_x0.90",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":50,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":25,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":13,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":6,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"multiplicative","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  multiplicative_x0.90.json"

cat > "$CONFIGS_DIR/multiplicative_x1.00.json" << JSEOF
{
    "experiment_name": "penalty_fleet_multiplicative_x1.00",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":56,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":28,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":14,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":7,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"multiplicative","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  multiplicative_x1.00.json"

cat > "$CONFIGS_DIR/multiplicative_x1.10.json" << JSEOF
{
    "experiment_name": "penalty_fleet_multiplicative_x1.10",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":61,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":31,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":15,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":8,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"multiplicative","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  multiplicative_x1.10.json"

cat > "$CONFIGS_DIR/multiplicative_x1.25.json" << JSEOF
{
    "experiment_name": "penalty_fleet_multiplicative_x1.25",
    "fleet": {"vehicle_types": [
            {"name":"Scooter","capacity":1,"max_speed_kmph":25,"fuel_l_per_100km":2.0,"co2_kg_per_liter":2.35,"fleet_size":70,"distance_band":{"lower_km":0.0,"upper_km":2.0},"fixed_cost_km_equiv":0.0},
            {"name":"Moped","capacity":2,"max_speed_kmph":45,"fuel_l_per_100km":3.0,"co2_kg_per_liter":2.35,"fleet_size":35,"distance_band":{"lower_km":1.5,"upper_km":6.0},"fixed_cost_km_equiv":0.0},
            {"name":"Car","capacity":4,"max_speed_kmph":80,"fuel_l_per_100km":11.1,"co2_kg_per_liter":2.35,"fleet_size":17,"distance_band":{"lower_km":4.0,"upper_km":12.0},"fixed_cost_km_equiv":0.0},
            {"name":"Minibus","capacity":8,"max_speed_kmph":70,"fuel_l_per_100km":14.0,"co2_kg_per_liter":2.68,"fleet_size":9,"distance_band":{"lower_km":8.0,"upper_km":20.0},"fixed_cost_km_equiv":0.0}
    ]},
    "time_window": {"mode":"fixed_slots","interval_minutes":20,"start_time_minutes":420,"end_time_minutes":570,"buffer_before_deadline_minutes":0},
    "solver_config": {"time_limit_seconds": ${TIME_LIMIT_SECONDS}},
    "penalty_parameters": {"alpha":1.0,"beta":1.0,"penalty_mode":"multiplicative","preference_scale_m":500},
    "baseline_parameters": {"private_car_fuel_l_per_100km":11.1,"private_car_co2_kg_per_liter":2.35,"private_car_speed_kmph":80.0}
}
JSEOF
        echo "  multiplicative_x1.25.json"
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

echo "  Next: python3 experiments/scripts/plot_penalty_fleet_interaction.py"
