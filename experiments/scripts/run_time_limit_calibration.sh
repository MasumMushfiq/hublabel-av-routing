#!/usr/bin/env bash
set -euo pipefail

TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
export PYTHON_BIN="${PYTHON_BIN:-python3}"
PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/footscray_commuters_residential.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/footscray_station.csv
#   MATRICES_DIR  default: $ROOT/dataset/FOOTSCRAY/footscray_residential_matrix
COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/footscray_commuters_residential.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/footscray_station.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/FOOTSCRAY/footscray_residential_matrix}"
BASE_CONFIG="${BASE_CONFIG:-config/footscray_base_config.json}"
if [[ "$BASE_CONFIG" != /* ]]; then
    BASE_CONFIG="$ROOT/$BASE_CONFIG"
fi
DRY_RUN=${DRY_RUN:-0}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

EXPERIMENT="${EXPERIMENT:-time_limit_calibration_footscray_80seats}"
OUTPUT_ROOT="${OUTPUT_DIR:-$ROOT/experiments/results}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
RESULTS_DIR="$OUTPUT_ROOT/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
TIME_LIMITS_VALUE="${TIME_LIMITS:-${TIME_LIMITS_OVERRIDE:-10 20 30 60 120 180 240 300 450 600}}"
read -r -a TIME_LIMITS <<< "$TIME_LIMITS_VALUE"
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
echo "  Fleet    : Footscray 80-seat reference fleet (minibus capacity 10)"
echo "  Demand   : Footscray residential-origin demand"
echo "  Limits   : ${TIME_LIMITS[*]} seconds  |  Seeds: $N_SEEDS"
echo "  Experiment folder: $EXPERIMENT"
echo "  Total    : $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."
"$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR" "${TIME_LIMITS[@]}" << 'PYEOF'
import copy
import json
import sys
from pathlib import Path

base_config = Path(sys.argv[1])
configs_dir = Path(sys.argv[2])
time_limits = [int(value) for value in sys.argv[3:]]

base = json.loads(base_config.read_text())
for time_limit in time_limits:
    config = copy.deepcopy(base)
    config.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
    out = configs_dir / f"tl_{time_limit}s.json"
    out.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  {out.name}")
PYEOF
echo ""

[[ $DRY_RUN == 1 ]] && { echo "  DRY RUN"; cat "$JOB_FILE"; exit 0; }

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
    if "$PYTHON_BIN" "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
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
MISSING_METRICS=0
SUSPICIOUS_LOGS=0
while read -r tl seed; do
    out_dir="$RESULTS_DIR/tl_${tl}s/run_$seed"
    if [[ ! -s "$out_dir/metrics.json" ]]; then
        printf "  WARNING: missing or empty metrics: tl_%ss/run_%s\n" "$tl" "$seed" >&2
        MISSING_METRICS=$((MISSING_METRICS + 1))
    fi
    if [[ -f "$out_dir/simulation.log" ]] && \
       grep -Eqi 'ERROR|Traceback|Exception|failed' "$out_dir/simulation.log"; then
        SUSPICIOUS_LOGS=$((SUSPICIOUS_LOGS + 1))
    fi
done < "$JOB_FILE"

if [[ "$MISSING_METRICS" -gt 0 ]]; then
    echo "  WARNING: $MISSING_METRICS expected run(s) lack a non-empty metrics.json"
else
    echo "  All $TOTAL expected metrics.json files are present"
fi
[[ "$SUSPICIOUS_LOGS" -gt 0 ]] && \
    echo "  WARNING: $SUSPICIOUS_LOGS simulation log(s) contain error keywords"
echo ""

echo "  Next: $PYTHON_BIN experiments/scripts/plot_time_limit_calibration.py --results-dir $RESULTS_DIR --out $RESULTS_DIR/plots"
