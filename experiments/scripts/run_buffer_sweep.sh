#!/usr/bin/env bash
set -euo pipefail

TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/commuters.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/stations.csv
#   MATRICES_DIR  default: $ROOT/dataset/MELTON/melton_generic_matrix
COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_generic_matrix}"
BASE_CONFIG="${BASE_CONFIG:-$ROOT/config/base_config.json}"
DRY_RUN=${DRY_RUN:-0}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

EXPERIMENT=${EXPERIMENT:-buffer_sweep_224seats}
OUTPUT_ROOT="${OUTPUT_DIR:-$ROOT/experiments/results}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
RESULTS_DIR="$OUTPUT_ROOT/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
BUFFER_VALUES=(${BUFFER_VALUES_OVERRIDE:-0 1 2 3 4 5})
N_SEEDS=${N_SEEDS:-15}
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-300}

JOB_FILE=$(mktemp /tmp/pyvrp_buf_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
for buf in "${BUFFER_VALUES[@]}"; do
    for seed in $(seq 1 "$N_SEEDS"); do echo "$buf $seed"; done
done > "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP PRE-DEPARTURE MARGIN SWEEP                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Fleet    : 56S/28M/14C/7MB (224 seats, balanced 25/25/25/25 seat share)"
echo "  Demand   : $COMMUTERS_CSV  |  Time: ${TIME_LIMIT_SECONDS}s  |  Distance-band penalty: none"
echo "  Buffer   : ${BUFFER_VALUES[*]} minutes  |  Seeds: $N_SEEDS"
echo "  Experiment folder: $EXPERIMENT"
echo "  Total    : $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."
"$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR" "$TIME_LIMIT_SECONDS" "${BUFFER_VALUES[@]}" << 'PYEOF'
import copy
import json
import sys
from pathlib import Path

base_config = Path(sys.argv[1])
configs_dir = Path(sys.argv[2])
time_limit = int(sys.argv[3])
buffers = [int(value) for value in sys.argv[4:]]

base = json.loads(base_config.read_text())
for buf in buffers:
    config = copy.deepcopy(base)
    config["experiment_name"] = f"buffer_sweep{buf}min_{time_limit}s"
    config.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
    config.setdefault("time_window", {})["buffer_before_deadline_minutes"] = buf
    out = configs_dir / f"buf_{buf}min.json"
    out.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  {out.name}")
PYEOF

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
    local buf="$1" seed="$2"
    local out_dir="$RESULTS_DIR/buf_${buf}min/run_$seed"
    local log="$out_dir/simulation.log"
    if [[ -f "$out_dir/metrics.json" ]] && [[ -s "$out_dir/metrics.json" ]] && \
       [[ -f "$out_dir/baseline.json" ]] && [[ -f "$out_dir/comparison.json" ]]; then
        printf "[buf_%smin seed_%s] already done, skipping\n" "$buf" "$seed"
        progress_tick; return 0
    fi
    mkdir -p "$out_dir"
    cp "$CONFIGS_DIR/buf_${buf}min.json" "$out_dir/config.json"
    printf "[buf_%smin seed_%s] starting...\n" "$buf" "$seed"
    if "$PYTHON_BIN" "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
            "$out_dir/assignments.csv" "$out_dir/av_routes.csv" \
            "$CONFIGS_DIR/buf_${buf}min.json" \
            "$out_dir/baseline.json" "$out_dir/metrics.json" "$out_dir/comparison.json" \
            "$seed" > "$log" 2>&1; then
        printf "[buf_%smin seed_%s] done\n" "$buf" "$seed"
    else
        printf "[buf_%smin seed_%s] FAILED — see %s\n" "$buf" "$seed" "$log" >&2
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

echo "  Next: python3 experiments/scripts/plot_buffer_sweep.py"
