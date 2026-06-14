#!/usr/bin/env bash
set -euo pipefail

# OPTIONAL FOOTSCRAY DIAGNOSTIC: compares time-window representations.
# This is not the archived pre-departure-margin sweep; BUFFER_MINUTES is retained
# only as the existing override for a fixed margin applied to every condition.

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

EXPERIMENT="${EXPERIMENT:-tw_mode_comparison_footscray_80seats}"
OUTPUT_ROOT="${OUTPUT_DIR:-$ROOT/experiments/results}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
RESULTS_DIR="$OUTPUT_ROOT/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
LABELS=(${LABELS_OVERRIDE:-individual fixed_5min fixed_10min fixed_15min fixed_20min fixed_30min fixed_60min})
N_SEEDS=${N_SEEDS:-15}
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-300}
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
echo "  Fleet    : Footscray 80-seat reference fleet (minibus capacity 10)"
echo "  Demand   : Footscray residential-origin demand  |  Time: ${TIME_LIMIT_SECONDS}s"
echo "  Pre-departure margin: ${BUFFER_MINUTES} min (fixed across conditions)"
echo "  Distance-band penalty: none"
echo "  Experiment folder: $EXPERIMENT"
echo "  Conditions: ${LABELS[*]}"
echo "  Seeds    : $N_SEEDS per condition  |  Total: $TOTAL jobs  |  Parallel: $PARALLEL_JOBS workers"

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."
"$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR" "$TIME_LIMIT_SECONDS" "$BUFFER_MINUTES" "${LABELS[@]}" << 'PYEOF'
import copy
import json
import sys
from pathlib import Path

base_config = Path(sys.argv[1])
configs_dir = Path(sys.argv[2])
time_limit = int(sys.argv[3])
buffer_minutes = float(sys.argv[4])
labels = sys.argv[5:]

base = json.loads(base_config.read_text())
for label in labels:
    config = copy.deepcopy(base)
    config["experiment_name"] = f"tw_mode_{label}"
    config.setdefault("solver_config", {})["time_limit_seconds"] = time_limit

    if label == "individual":
        config["time_window"] = {
            "mode": "individual",
            "buffer_before_deadline_minutes": buffer_minutes,
        }
    elif label.startswith("fixed_") and label.endswith("min"):
        interval = int(label.replace("fixed_", "").replace("min", ""))
        config["time_window"] = copy.deepcopy(base.get("time_window", {}))
        config["time_window"]["mode"] = "fixed_slots"
        config["time_window"]["interval_minutes"] = interval
        config["time_window"]["buffer_before_deadline_minutes"] = buffer_minutes
    else:
        raise SystemExit(f"ERROR: Unknown label {label!r}")

    out = configs_dir / f"{label}.json"
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
    if "$PYTHON_BIN" "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
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

MISSING_METRICS=0
FAILURE_LOGS=0
while read -r label seed; do
    out_dir="$RESULTS_DIR/$label/run_$seed"
    metrics="$out_dir/metrics.json"
    log="$out_dir/simulation.log"

    if [[ ! -s "$metrics" ]]; then
        printf "  WARNING: missing or empty metrics: %s\n" "$metrics"
        MISSING_METRICS=$((MISSING_METRICS + 1))
    fi

    if [[ -f "$log" ]] && grep -Eq 'ERROR|Error|Traceback|Exception|FAILED|failed' "$log"; then
        printf "  WARNING: failure marker found in: %s\n" "$log"
        FAILURE_LOGS=$((FAILURE_LOGS + 1))
    fi
done < "$JOB_FILE"

if (( MISSING_METRICS == 0 )); then
    printf "  Metrics: %d/%d metrics.json files present\n" "$TOTAL" "$TOTAL"
else
    printf "  WARNING: %d/%d runs are missing a non-empty metrics.json\n" \
        "$MISSING_METRICS" "$TOTAL"
fi

if (( FAILURE_LOGS == 0 )); then
    echo "  Logs: no failure markers detected"
else
    printf "  WARNING: %d simulation log(s) contain failure markers\n" "$FAILURE_LOGS"
fi
echo ""

echo "  Next: $PYTHON_BIN experiments/scripts/plot_tw_mode_comparison_2x2.py --results-dir $RESULTS_DIR --out $RESULTS_DIR/plots"
