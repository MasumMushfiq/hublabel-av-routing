#!/usr/bin/env bash
set -euo pipefail

# Active Footscray pilot-fleet demand sensitivity. Demand subsets are prefixes
# of one fixed-seed shuffle, so 25% is a subset of 50%, then 75%, then 100%.
# CONFIG_ONLY=1 generates configs, demand subsets, and metadata without solving.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SIM_SCRIPT="${SIM_SCRIPT:-$ROOT/python/simulate_first_mile_pyvrp.py}"
BASE_CONFIG="${BASE_CONFIG:-config/footscray_base_config.json}"
COMMUTERS_CSV="${COMMUTERS_CSV:-files/inputs/footscray_commuters_residential.csv}"
STATIONS_CSV="${STATIONS_CSV:-files/inputs/footscray_station.csv}"
MATRICES_DIR="${MATRICES_DIR:-dataset/FOOTSCRAY/footscray_residential_matrix}"
OUTPUT_DIR="${OUTPUT_DIR:-experiments/results/footscray}"
EXPERIMENT="${EXPERIMENT:-pilot_fleet_demand_sensitivity_footscray}"

for variable in BASE_CONFIG COMMUTERS_CSV STATIONS_CSV MATRICES_DIR OUTPUT_DIR; do
    value="${!variable}"
    [[ "$value" == /* ]] || printf -v "$variable" '%s/%s' "$ROOT" "$value"
done

RESULTS_DIR="$OUTPUT_DIR/$EXPERIMENT"
CONFIGS_DIR="${CONFIGS_DIR:-$RESULTS_DIR/configs}"
INPUTS_DIR="${INPUTS_DIR:-$RESULTS_DIR/inputs}"
[[ "$CONFIGS_DIR" == /* ]] || CONFIGS_DIR="$ROOT/$CONFIGS_DIR"
[[ "$INPUTS_DIR" == /* ]] || INPUTS_DIR="$ROOT/$INPUTS_DIR"

TIME_LIMIT_SECONDS="${TIME_LIMIT_SECONDS:-300}"
N_SEEDS="${N_SEEDS:-15}"
DEMAND_SAMPLE_SEED="${DEMAND_SAMPLE_SEED:-42}"
TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS="${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}"
RESUME="${RESUME:-1}"
CONFIG_ONLY="${CONFIG_ONLY:-0}"
DRY_RUN="${DRY_RUN:-0}"
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

generate_inputs_and_configs() {
    mkdir -p "$CONFIGS_DIR" "$INPUTS_DIR"
    "$PYTHON_BIN" - "$BASE_CONFIG" "$COMMUTERS_CSV" "$CONFIGS_DIR" "$INPUTS_DIR" \
        "$TIME_LIMIT_SECONDS" "$DEMAND_SAMPLE_SEED" <<'PYEOF'
import copy
import csv
import json
import random
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

base_path, demand_path = Path(sys.argv[1]), Path(sys.argv[2])
configs_dir, inputs_dir = Path(sys.argv[3]), Path(sys.argv[4])
time_limit, sample_seed = int(sys.argv[5]), int(sys.argv[6])
fractions = [(25, Decimal("0.25")), (50, Decimal("0.50")), (75, Decimal("0.75")), (100, Decimal("1.00"))]
vehicle_order = ["Scooter", "Moped", "Car", "Minibus"]
pilots = {
    "balanced_pilot": [10, 5, 2, 1],
    "vmt_oriented_pilot": [10, 0, 0, 3],
    "low_emission_pilot": [20, 10, 0, 0],
    "all_car_pilot": [0, 0, 10, 0],
}

for old_config in configs_dir.glob("*.json"):
    old_config.unlink()

with base_path.open(encoding="utf-8") as handle:
    base = json.load(handle)
base_vehicles = {item["name"]: item for item in base["fleet"]["vehicle_types"]}
capacities = {name: int(base_vehicles[name]["capacity"]) for name in vehicle_order}
expected = {"Scooter": 1, "Moped": 2, "Car": 4, "Minibus": 10}
if capacities != expected:
    raise ValueError(f"Footscray capacities must be {expected}; found {capacities}")

with demand_path.open(newline="", encoding="utf-8") as handle:
    reader = csv.DictReader(handle)
    fieldnames = reader.fieldnames
    demand_rows = list(reader)
if not fieldnames:
    raise ValueError(f"Missing CSV header in {demand_path}")
if len(demand_rows) != 586:
    raise ValueError(f"Expected 586 Footscray commuters; found {len(demand_rows)}")

order = list(range(len(demand_rows)))
random.Random(sample_seed).shuffle(order)
demand_metadata = []
for pct, fraction in fractions:
    requested = int((Decimal(len(demand_rows)) * fraction).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    selected = set(order[:requested])
    subset = [row for index, row in enumerate(demand_rows) if index in selected]
    level_dir = inputs_dir / f"demand_{pct:03d}"
    level_dir.mkdir(parents=True, exist_ok=True)
    subset_path = level_dir / "footscray_commuters_residential.csv"
    with subset_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(subset)
    demand_metadata.append({
        "demand_fraction": float(fraction),
        "demand_fraction_pct": pct,
        "requested_demand_count": requested,
        "actual_demand_count": len(subset),
        "demand_sample_seed": sample_seed,
        "commuters_csv": str(subset_path),
    })

config_rows = []
for pilot_name, counts in pilots.items():
    seats_by_type = {
        name: counts[index] * capacities[name]
        for index, name in enumerate(vehicle_order)
    }
    total_seats = sum(seats_by_type.values())
    fleet_metadata = {"pilot_fleet_name": pilot_name, "actual_total_seats": total_seats}
    for index, name in enumerate(vehicle_order):
        key = name.lower()
        fleet_metadata[f"{key}_count"] = counts[index]
        fleet_metadata[f"realized_{key}_seat_share_pct"] = round(100 * seats_by_type[name] / total_seats, 6)

    for demand in demand_metadata:
        condition = f"{pilot_name}_demand_{demand['demand_fraction_pct']:03d}"
        metadata = {**demand, **fleet_metadata}
        cfg = copy.deepcopy(base)
        cfg["experiment_name"] = condition
        cfg["pilot_fleet_metadata"] = metadata
        cfg.setdefault("solver_config", {})["time_limit_seconds"] = time_limit
        cfg["fleet"]["vehicle_types"] = []
        for index, name in enumerate(vehicle_order):
            if counts[index] == 0:
                continue
            vehicle = copy.deepcopy(base_vehicles[name])
            vehicle["fleet_size"] = counts[index]
            cfg["fleet"]["vehicle_types"].append(vehicle)
        with (configs_dir / f"{condition}.json").open("w", encoding="utf-8") as handle:
            json.dump(cfg, handle, indent=2)
        config_rows.append({"condition": condition, **metadata})

with (inputs_dir / "demand_level_summary.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=demand_metadata[0].keys())
    writer.writeheader()
    writer.writerows(demand_metadata)
with (configs_dir / "pilot_fleet_demand_metadata.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=config_rows[0].keys())
    writer.writeheader()
    writer.writerows(config_rows)
print(f"Wrote {len(config_rows)} configs and {len(demand_metadata)} nested demand subsets")
PYEOF
}

build_jobs() {
    local job_file="$1"
    "$PYTHON_BIN" - "$CONFIGS_DIR" "$job_file" "$N_SEEDS" <<'PYEOF'
import json
import sys
from pathlib import Path

configs_dir, job_path, n_seeds = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
with job_path.open("w", encoding="utf-8") as handle:
    for path in sorted(configs_dir.glob("*.json")):
        meta = json.loads(path.read_text(encoding="utf-8"))["pilot_fleet_metadata"]
        for seed in range(1, n_seeds + 1):
            handle.write(
                f"{path.stem}\t{meta['pilot_fleet_name']}\t"
                f"{meta['demand_fraction_pct']:03d}\t{meta['commuters_csv']}\t{seed}\n"
            )
PYEOF
}

progress_tick() {
    local lock_dir="${PROG_LOCK}.lock" done
    while ! mkdir "$lock_dir" 2>/dev/null; do sleep 0.02; done
    done=$(<"$PROG_COUNT")
    done=$((done + 1))
    printf '%s\n' "$done" > "$PROG_COUNT"
    printf '[progress] %d/%d completed\n' "$done" "$TOTAL"
    rmdir "$lock_dir"
}

run_one() {
    local condition="$1" pilot_name="$2" demand_pct="$3" commuters_csv="$4" seed="$5"
    local config_path="$CONFIGS_DIR/${condition}.json"
    local run_dir="$RESULTS_DIR/$pilot_name/demand_${demand_pct}/seed_${seed}"
    local log_file="$run_dir/simulation.log"
    if [[ "$RESUME" == "1" && -s "$run_dir/metrics.json" ]]; then
        printf '[SKIP] %s seed=%s already has metrics.json\n' "$condition" "$seed"
        progress_tick
        return 0
    fi
    mkdir -p "$run_dir"
    cp "$config_path" "$run_dir/config.json"
    printf '[RUN] %s seed=%s\n' "$condition" "$seed"
    if "$PYTHON_BIN" "$SIM_SCRIPT" \
        "$commuters_csv" "$STATIONS_CSV" "$MATRICES_DIR" \
        "$run_dir/assignments.csv" "$run_dir/av_routes.csv" "$config_path" \
        "$run_dir/baseline.json" "$run_dir/metrics.json" "$run_dir/comparison.json" \
        "$seed" >"$log_file" 2>&1; then
        printf '[DONE] %s seed=%s\n' "$condition" "$seed"
    else
        printf '[FAIL] %s seed=%s; see %s\n' "$condition" "$seed" "$log_file" >&2
    fi
    progress_tick
}
export -f progress_tick run_one

echo "Footscray pilot-fleet demand sensitivity"
echo "  Results: $RESULTS_DIR"
echo "  Demand:  25%, 50%, 75%, 100% of 586 commuters"
echo "  Fleets:  balanced, VMT-oriented, low-emission S50/M50, all-car pilots"
echo "  Seeds:   $N_SEEDS"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: missing $PYTHON_BIN" >&2; exit 1; }
for path in "$BASE_CONFIG" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
    [[ -f "$path" ]] || { echo "ERROR: missing file $path" >&2; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: missing matrix directory $MATRICES_DIR" >&2; exit 1; }

mkdir -p "$RESULTS_DIR"
generate_inputs_and_configs
[[ "$CONFIG_ONLY" == "1" ]] && { echo "CONFIG_ONLY=1: configuration generation complete"; exit 0; }

JOB_FILE=$(mktemp /tmp/footscray_pilot_jobs.XXXXXX)
PROG_COUNT=$(mktemp /tmp/footscray_pilot_progress.XXXXXX)
PROG_LOCK=$(mktemp /tmp/footscray_pilot_lock.XXXXXX)
trap 'rm -f "$JOB_FILE" "$PROG_COUNT" "$PROG_LOCK"' EXIT
build_jobs "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')
printf '0\n' > "$PROG_COUNT"
export PYTHON_BIN SIM_SCRIPT STATIONS_CSV MATRICES_DIR CONFIGS_DIR RESULTS_DIR RESUME
export PROG_COUNT PROG_LOCK TOTAL

if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN=1: jobs follow"
    cat "$JOB_FILE"
    exit 0
fi

if command -v parallel >/dev/null 2>&1; then
    parallel --jobs "$PARALLEL_JOBS" --colsep '\t' run_one {1} {2} {3} {4} {5} :::: "$JOB_FILE"
else
    echo "GNU parallel not found; running sequentially"
    while IFS=$'\t' read -r condition pilot_name demand_pct commuters_csv seed; do
        run_one "$condition" "$pilot_name" "$demand_pct" "$commuters_csv" "$seed"
    done < "$JOB_FILE"
fi

echo "Done: $RESULTS_DIR"
