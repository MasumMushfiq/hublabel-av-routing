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

EXPERIMENT=${EXPERIMENT:-seed_convergence_footscray_80seats}
OUTPUT_ROOT="${OUTPUT_DIR:-$ROOT/experiments/results}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
RESULTS_DIR="$OUTPUT_ROOT/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
N_SEEDS=${N_SEEDS:-50}
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-300}

JOB_FILE=$(mktemp /tmp/pyvrp_sc_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
for seed in $(seq 1 "$N_SEEDS"); do echo "$seed"; done > "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP SEED CONVERGENCE ANALYSIS                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Fleet    : Footscray 80-seat reference fleet (minibus capacity 10)"
echo "  Demand   : corrected Footscray residential-origin demand  |  Time: ${TIME_LIMIT_SECONDS}s"
echo "  Experiment folder: $EXPERIMENT"
echo "  Seeds    : 1 – $N_SEEDS  |  Total: $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
"$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR/seed_convergence.json" "$TIME_LIMIT_SECONDS" << 'PYEOF'
import copy
import json
import sys
from pathlib import Path

base_config = Path(sys.argv[1])
out_path = Path(sys.argv[2])
time_limit = int(sys.argv[3])

config = copy.deepcopy(json.loads(base_config.read_text()))
config.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
config["experiment_name"] = f"seed_convergence{time_limit}s"
out_path.write_text(json.dumps(config, indent=2) + "\n")
PYEOF
echo "  seed_convergence.json written"

[[ $DRY_RUN == 1 ]] && { echo "  DRY RUN"; cat "$JOB_FILE"; exit 0; }
export CONFIGS_DIR RESULTS_DIR PYVRP_SCRIPT COMMUTERS_CSV STATIONS_CSV MATRICES_DIR PYTHON_BIN

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
    local seed="$1"
    local out_dir="$RESULTS_DIR/run_$seed"
    local log="$out_dir/simulation.log"
    if [[ -f "$out_dir/metrics.json" ]] && [[ -s "$out_dir/metrics.json" ]] && \
       [[ -f "$out_dir/baseline.json" ]] && [[ -f "$out_dir/comparison.json" ]]; then
        printf "[seed_%s] already done, skipping\n" "$seed"
        progress_tick; return 0
    fi
    mkdir -p "$out_dir"
    cp "$CONFIGS_DIR/seed_convergence.json" "$out_dir/config.json"
    printf "[seed_%s] starting...\n" "$seed"
    if "$PYTHON_BIN" "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
            "$out_dir/assignments.csv" "$out_dir/av_routes.csv" \
            "$CONFIGS_DIR/seed_convergence.json" \
            "$out_dir/baseline.json" "$out_dir/metrics.json" "$out_dir/comparison.json" \
            "$seed" > "$log" 2>&1; then
        printf "[seed_%s] done\n" "$seed"
    else
        printf "[seed_%s] FAILED — see %s\n" "$seed" "$log" >&2
    fi
    progress_tick
}
export -f run_one

START=$(date +%s)
parallel --jobs "$PARALLEL_JOBS" --eta run_one {1} :::: "$JOB_FILE"
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

echo "  Next: $PYTHON_BIN experiments/scripts/plot_seed_convergence.py --results-dir $RESULTS_DIR --out $RESULTS_DIR/plots"
