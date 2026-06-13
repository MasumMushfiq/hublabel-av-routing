#!/usr/bin/env bash
set -euo pipefail

TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_generic_matrix}"
BASE_CONFIG="${BASE_CONFIG:-$ROOT/config/legacy_melton_base_config.json}"
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
#
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/commuters.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/stations.csv
#   MATRICES_DIR  default: $ROOT/dataset/MELTON/melton_generic_matrix
# =============================================================================

EXPERIMENT="penalty_fleet_interaction_224seats"
OUTPUT_ROOT="${OUTPUT_DIR:-$ROOT/experiments/results}"
if [[ "$OUTPUT_ROOT" != /* ]]; then
    OUTPUT_ROOT="$ROOT/$OUTPUT_ROOT"
fi
RESULTS_DIR="$OUTPUT_ROOT/$EXPERIMENT"
CONFIGS_DIR="$RESULTS_DIR/configs"
# Defaults (can be overridden from environment)
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-300}
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

for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

rm -rf "$CONFIGS_DIR"
mkdir -p "$CONFIGS_DIR"
echo "Writing configs..."
"$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR" "$TIME_LIMIT_SECONDS" "${LABELS[@]}" << 'PYEOF'
import copy
import json
import sys
from pathlib import Path

base_config = Path(sys.argv[1])
configs_dir = Path(sys.argv[2])
time_limit = int(sys.argv[3])
labels = sys.argv[4:]

fleet_sizes = {
    "x0.90": {"Scooter": 50, "Moped": 25, "Car": 13, "Minibus": 6},
    "x1.00": {"Scooter": 56, "Moped": 28, "Car": 14, "Minibus": 7},
    "x1.10": {"Scooter": 61, "Moped": 31, "Car": 15, "Minibus": 8},
    "x1.25": {"Scooter": 70, "Moped": 35, "Car": 17, "Minibus": 9},
}

base = json.loads(base_config.read_text())
for label in labels:
    mode, scale = label.rsplit("_", 1)
    if mode not in {"none", "multiplicative"}:
        raise SystemExit(f"ERROR: Unknown penalty mode in {label!r}")
    if scale not in fleet_sizes:
        raise SystemExit(f"ERROR: Unknown fleet scale in {label!r}")

    config = copy.deepcopy(base)
    config["experiment_name"] = f"penalty_fleet_{mode}_{scale}"
    config.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
    config.setdefault("penalty_parameters", {})["penalty_mode"] = mode

    sizes = fleet_sizes[scale]
    for vehicle in config.get("fleet", {}).get("vehicle_types", []):
        name = vehicle.get("name")
        if name not in sizes:
            raise SystemExit(f"ERROR: Unexpected vehicle type {name!r}")
        vehicle["fleet_size"] = sizes[name]

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
FAILED=$(find "$RESULTS_DIR" -name "simulation.log" \
    | xargs grep -l "Error\|Traceback" 2>/dev/null | wc -l | tr -d " ")
[[ "$FAILED" -gt 0 ]] && echo "  WARNING: $FAILED run(s) may have failed" \
    || echo "  No failures detected"
echo ""

echo "  Next: python3 experiments/scripts/plot_penalty_fleet_interaction.py"
