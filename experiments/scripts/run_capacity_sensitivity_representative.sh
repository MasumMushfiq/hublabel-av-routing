#!/usr/bin/env bash
set -euo pipefail

# Active Footscray representative-fleet capacity sensitivity.
#
# Vehicle counts are obtained by scaling each representative's 100% counts
# and rounding each count with round-half-up. A vehicle type present at 100%
# is kept at a minimum of one vehicle for every nonzero scale. Because this is
# integer count scaling, actual_total_seats can differ from target_seats.
#
# CONFIG_ONLY=1 generates configs/metadata and exits. LABELS_OVERRIDE accepts
# space-separated fleet names or representative labels. DRY_RUN=1 lists jobs.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SIM_SCRIPT="${SIM_SCRIPT:-$ROOT/python/simulate_first_mile_pyvrp.py}"
BASE_CONFIG="${BASE_CONFIG:-config/footscray_base_config.json}"
COMMUTERS_CSV="${COMMUTERS_CSV:-files/inputs/footscray_commuters_residential.csv}"
STATIONS_CSV="${STATIONS_CSV:-files/inputs/footscray_station.csv}"
MATRICES_DIR="${MATRICES_DIR:-dataset/FOOTSCRAY/footscray_residential_matrix}"
OUTPUT_DIR="${OUTPUT_DIR:-experiments/results/footscray}"
EXPERIMENT="${EXPERIMENT:-capacity_sensitivity_representative_footscray}"

for variable in BASE_CONFIG COMMUTERS_CSV STATIONS_CSV MATRICES_DIR OUTPUT_DIR; do
    value="${!variable}"
    [[ "$value" == /* ]] || printf -v "$variable" '%s/%s' "$ROOT" "$value"
done

RESULTS_DIR="$OUTPUT_DIR/$EXPERIMENT"
CONFIGS_DIR="${CONFIGS_DIR:-$RESULTS_DIR/configs}"
[[ "$CONFIGS_DIR" == /* ]] || CONFIGS_DIR="$ROOT/$CONFIGS_DIR"

TIME_LIMIT_SECONDS="${TIME_LIMIT_SECONDS:-300}"
N_SEEDS="${N_SEEDS:-15}"
TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS="${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}"
RESUME="${RESUME:-1}"
CONFIG_ONLY="${CONFIG_ONLY:-0}"
DRY_RUN="${DRY_RUN:-0}"
LABELS_OVERRIDE="${LABELS_OVERRIDE:-}"
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

generate_configs() {
    mkdir -p "$CONFIGS_DIR"
    "$PYTHON_BIN" - "$BASE_CONFIG" "$CONFIGS_DIR" "$TIME_LIMIT_SECONDS" <<'PYEOF'
import copy
import csv
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

base_path, configs_dir, time_limit = sys.argv[1], Path(sys.argv[2]), int(sys.argv[3])
reference_seats = 80
scales = [50, 100, 150, 200]
vehicle_order = ["Scooter", "Moped", "Car", "Minibus"]
representatives = {
    "balanced": ("comp_S25_M25_C25_MB25", [20, 10, 5, 2]),
    "vmt_oriented": ("comp_S25_M0_C0_MB75", [20, 0, 0, 6]),
    "low_emission": ("comp_S50_M50_C0_MB0", [40, 20, 0, 0]),
    "all_car": ("comp_S0_M0_C100_MB0", [0, 0, 20, 0]),
}

for old_config in configs_dir.glob("*.json"):
    old_config.unlink()

with open(base_path, encoding="utf-8") as handle:
    base = json.load(handle)
base_vehicles = {item["name"]: item for item in base["fleet"]["vehicle_types"]}
capacities = {name: int(base_vehicles[name]["capacity"]) for name in vehicle_order}
expected = {"Scooter": 1, "Moped": 2, "Car": 4, "Minibus": 10}
if capacities != expected:
    raise ValueError(f"Footscray capacities must be {expected}; found {capacities}")

def round_half_up(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

rows = []
for fleet_name, (representative_label, base_counts) in representatives.items():
    for nominal_scale_pct in scales:
        factor = Decimal(nominal_scale_pct) / Decimal(100)
        counts = []
        for count in base_counts:
            scaled = round_half_up(Decimal(count) * factor)
            counts.append(max(1, scaled) if count > 0 and nominal_scale_pct > 0 else 0)
        seats_by_type = {
            name: counts[index] * capacities[name]
            for index, name in enumerate(vehicle_order)
        }
        actual_total_seats = sum(seats_by_type.values())
        metadata = {
            "fleet_name": fleet_name,
            "representative_label": representative_label,
            "nominal_scale_pct": nominal_scale_pct,
            "target_seats": reference_seats * nominal_scale_pct / 100,
            "actual_total_seats": actual_total_seats,
            "rounding_rule": "round-half-up per vehicle count; minimum 1 for types present at 100%",
        }
        for index, name in enumerate(vehicle_order):
            key = name.lower()
            metadata[f"{key}_count"] = counts[index]
            metadata[f"realized_{key}_seat_share_pct"] = round(
                100 * seats_by_type[name] / actual_total_seats, 6
            )

        cfg = copy.deepcopy(base)
        condition = f"{fleet_name}_scale_{nominal_scale_pct:03d}"
        cfg["experiment_name"] = condition
        cfg["capacity_metadata"] = metadata
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
        rows.append({"condition": condition, **metadata})

metadata_path = configs_dir / "capacity_sensitivity_metadata.csv"
with metadata_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {len(rows)} configs and {metadata_path}")
PYEOF
}

build_jobs() {
    local job_file="$1"
    "$PYTHON_BIN" - "$CONFIGS_DIR" "$job_file" "$N_SEEDS" "$LABELS_OVERRIDE" <<'PYEOF'
import json
import sys
from pathlib import Path

configs_dir, job_path = Path(sys.argv[1]), Path(sys.argv[2])
n_seeds, override = int(sys.argv[3]), sys.argv[4].split()
configs = []
for path in sorted(configs_dir.glob("*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    meta = data["capacity_metadata"]
    if override and meta["fleet_name"] not in override and meta["representative_label"] not in override:
        continue
    configs.append((path.stem, meta["fleet_name"], int(meta["nominal_scale_pct"])))
if override and not configs:
    raise SystemExit("LABELS_OVERRIDE did not match any fleet name or representative label")
with job_path.open("w", encoding="utf-8") as handle:
    for condition, fleet_name, scale in configs:
        for seed in range(1, n_seeds + 1):
            handle.write(f"{condition}\t{fleet_name}\t{scale}\t{seed}\n")
print(f"Built {len(configs) * n_seeds} jobs from {len(configs)} conditions")
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
    local condition="$1" fleet_name="$2" scale="$3" seed="$4"
    local config_path="$CONFIGS_DIR/${condition}.json"
    local run_dir="$RESULTS_DIR/$fleet_name/scale_${scale}/seed_${seed}"
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
        "$COMMUTERS_CSV" "$STATIONS_CSV" "$MATRICES_DIR" \
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

echo "Footscray representative capacity sensitivity"
echo "  Results: $RESULTS_DIR"
echo "  Scales:  50%, 100%, 150%, 200% of the 80-seat reference"
echo "  Seeds:   $N_SEEDS"
echo "  Solver:  ${TIME_LIMIT_SECONDS}s"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: missing $PYTHON_BIN" >&2; exit 1; }
for path in "$BASE_CONFIG" "$COMMUTERS_CSV" "$STATIONS_CSV"; do
    [[ -f "$path" ]] || { echo "ERROR: missing file $path" >&2; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: missing matrix directory $MATRICES_DIR" >&2; exit 1; }

mkdir -p "$RESULTS_DIR"
generate_configs
[[ "$CONFIG_ONLY" == "1" ]] && { echo "CONFIG_ONLY=1: configuration generation complete"; exit 0; }

JOB_FILE=$(mktemp /tmp/footscray_capacity_jobs.XXXXXX)
PROG_COUNT=$(mktemp /tmp/footscray_capacity_progress.XXXXXX)
PROG_LOCK=$(mktemp /tmp/footscray_capacity_lock.XXXXXX)
trap 'rm -f "$JOB_FILE" "$PROG_COUNT" "$PROG_LOCK"' EXIT
build_jobs "$JOB_FILE"
TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')
printf '0\n' > "$PROG_COUNT"
export PYTHON_BIN SIM_SCRIPT COMMUTERS_CSV STATIONS_CSV MATRICES_DIR CONFIGS_DIR RESULTS_DIR RESUME
export PROG_COUNT PROG_LOCK TOTAL

if [[ "$DRY_RUN" == "1" ]]; then
    echo "DRY_RUN=1: jobs follow"
    cat "$JOB_FILE"
    exit 0
fi

if command -v parallel >/dev/null 2>&1; then
    parallel --jobs "$PARALLEL_JOBS" --colsep '\t' run_one {1} {2} {3} {4} :::: "$JOB_FILE"
else
    echo "GNU parallel not found; running sequentially"
    while IFS=$'\t' read -r condition fleet_name scale seed; do
        run_one "$condition" "$fleet_name" "$scale" "$seed"
    done < "$JOB_FILE"
fi

echo "Done: $RESULTS_DIR"
