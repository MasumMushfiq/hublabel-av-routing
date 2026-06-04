#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# run_pilot_fleet_demand_sensitivity.sh
#
# Fixed-fleet pilot demand sensitivity for SIGSPATIAL 2026 AV first-mile paper.
#
# Research question:
#   If an agency starts with a smaller fixed pilot fleet (112 seats), how much
#   morning-peak demand can it support effectively?
#
# Design:
#   - 4 pilot fleets, each exactly 112 seats
#   - 4 demand fractions of 1465 Myki commuters: x0.25, x0.50, x0.75, x1.00
#   - Demand sampled once per level (DEMAND_SAMPLE_SEED=42), nested subsets
#   - All fleets and seeds solve the same demand instance at each level
#   - Solver: PyVRP/HGS, 180s, fixed_slots 20-min, buffer 0, penalty none
#   - x1.00 is intentionally an overload/stress-test case
#
# Pilot fleets (112 seats each):
#   balanced_pilot    : 24 scooters, 12 mopeds, 6 cars, 5 minibuses
#   vmt_oriented_pilot: 28 scooters, 14 mopeds, 0 cars, 7 minibuses
#   low_emission_pilot: 24 scooters, 28 mopeds, 0 cars, 4 minibuses
#   all_minibus_pilot : 0  scooters, 0  mopeds, 0 cars, 14 minibuses
#
# Result layout:
#   experiments/results/pilot_fleet_demand_sensitivity/
#     configs/
#     inputs/x0.25/commuters.csv  ...  inputs/demand_level_summary.csv
#     balanced_pilot/x0.25/seed_1/{assignments,av_routes,baseline,metrics,comparison}.json
#     ...
#
# Usage:
#   bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#   DRY_RUN=1 bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#   NUM_SEEDS=3  RESUME=1 JOBS=10 bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#   NUM_SEEDS=10 RESUME=1 JOBS=10 bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/commuters.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/stations.csv
#   MATRICES_DIR  default: $ROOT/dataset/MELTON/melton_generic_matrix
# =============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$ROOT_DIR"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SIM_SCRIPT="${SIM_SCRIPT:-python/simulate_first_mile_pyvrp.py}"

EXPERIMENT="pilot_fleet_demand_sensitivity"
RESULTS_ROOT="${RESULTS_ROOT:-experiments/results/${EXPERIMENT}}"
CONFIG_DIR="${RESULTS_ROOT}/configs"
INPUT_DIR="${RESULTS_ROOT}/inputs"

TIME_LIMIT="${TIME_LIMIT:-180}"
NUM_SEEDS="${NUM_SEEDS:-3}"
JOBS="${JOBS:-10}"
RESUME="${RESUME:-1}"
DRY_RUN="${DRY_RUN:-0}"
DEMAND_SAMPLE_SEED="${DEMAND_SAMPLE_SEED:-42}"

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

FULL_COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_generic_matrix}"

JOBS_FILE="${RESULTS_ROOT}/jobs.txt"
JOBLOG="${RESULTS_ROOT}/parallel_joblog.tsv"

declare -a FLEETS=(
  "balanced_pilot"
  "vmt_oriented_pilot"
  "low_emission_pilot"
  "all_minibus_pilot"
)

declare -a DEMAND_LEVELS=(
  "x0.25"
  "x0.50"
  "x0.75"
  "x1.00"
)

# -----------------------------------------------------------------------------
# Fleet vehicle counts. Output: scooters mopeds cars minibuses total_seats
# Zero-count types are excluded from configs downstream.
# -----------------------------------------------------------------------------
get_fleet_counts() {
  case "$1" in
    balanced_pilot)     echo "24 12 6 5 112" ;;   # 24+24+24+40 = 112
    vmt_oriented_pilot) echo "28 14 0 7 112" ;;   # 28+28+0+56  = 112
    low_emission_pilot) echo "24 28 0 4 112" ;;   # 24+56+0+32  = 112
    all_minibus_pilot)  echo "0  0  0 14 112" ;;  # 0+0+0+112   = 112
    *) echo "Unknown fleet: $1" >&2; exit 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# Generate one JSON config per pilot fleet.
# Vehicle types with fleet_size=0 are omitted (PyVRP requires num_available>0).
# -----------------------------------------------------------------------------
generate_configs() {
  mkdir -p "$CONFIG_DIR"

  for fleet in "${FLEETS[@]}"; do
    read -r n_scooter n_moped n_car n_minibus total_seats < <(get_fleet_counts "$fleet")
    local config_path="${CONFIG_DIR}/${fleet}.json"

    "$PYTHON_BIN" - \
        "$fleet" "$n_scooter" "$n_moped" "$n_car" "$n_minibus" \
        "$total_seats" "$TIME_LIMIT" "$config_path" << 'PYEOF'
import sys, json

fleet       = sys.argv[1]
n_scooter   = int(sys.argv[2])
n_moped     = int(sys.argv[3])
n_car       = int(sys.argv[4])
n_minibus   = int(sys.argv[5])
total_seats = int(sys.argv[6])
time_limit  = int(sys.argv[7])
out_path    = sys.argv[8]

VEHICLE_PARAMS = {
    "scooter": {
        "capacity": 1, "max_speed_kmph": 25,
        "fuel_l_per_100km": 2.0, "co2_kg_per_liter": 2.35,
        "distance_band": {"lower_km": 0.0, "upper_km": 2.0},
    },
    "moped": {
        "capacity": 2, "max_speed_kmph": 45,
        "fuel_l_per_100km": 3.0, "co2_kg_per_liter": 2.35,
        "distance_band": {"lower_km": 1.5, "upper_km": 6.0},
    },
    "car": {
        "capacity": 4, "max_speed_kmph": 80,
        "fuel_l_per_100km": 11.1, "co2_kg_per_liter": 2.35,
        "distance_band": {"lower_km": 4.0, "upper_km": 12.0},
    },
    "minibus": {
        "capacity": 8, "max_speed_kmph": 70,
        "fuel_l_per_100km": 14.0, "co2_kg_per_liter": 2.68,
        "distance_band": {"lower_km": 8.0, "upper_km": 20.0},
    },
}

counts = {
    "scooter": n_scooter,
    "moped":   n_moped,
    "car":     n_car,
    "minibus": n_minibus,
}

vehicle_types = []
for vt in ["scooter", "moped", "car", "minibus"]:
    n = counts[vt]
    if n <= 0:
        continue
    p = VEHICLE_PARAMS[vt]
    vehicle_types.append({
        "name":                vt,
        "fleet_size":          n,
        "capacity":            p["capacity"],
        "max_speed_kmph":      p["max_speed_kmph"],
        "fuel_l_per_100km":    p["fuel_l_per_100km"],
        "co2_kg_per_liter":    p["co2_kg_per_liter"],
        "distance_band":       p["distance_band"],
        "fixed_cost_km_equiv": 0.0,
    })

cfg = {
    "experiment_name": f"pilot_fleet_demand_sensitivity_{fleet}",
    "pilot_fleet_metadata": {
        "fleet_key":    fleet,
        "total_seats":  total_seats,
        "note": (
            "Approximately balanced 112-seat integer fleet; exact 25% seat "
            "shares are not possible with integer minibuses at 112 seats."
            if fleet == "balanced_pilot" else
            f"Fixed 112-seat pilot fleet: {fleet}"
        ),
    },
    "fleet": {"vehicle_types": vehicle_types},
    "solver_config": {
        "time_limit_seconds": time_limit,
    },
    "time_window": {
        "mode":                        "fixed_slots",
        "interval_minutes":            20,
        "start_time_minutes":          420,
        "end_time_minutes":            570,
        "buffer_before_deadline_minutes": 0,
    },
    "penalty_parameters": {
        "alpha":              1.0,
        "beta":               1.0,
        "penalty_mode":       "none",
        "preference_scale_m": 500,
    },
    "baseline_parameters": {
        "private_car_fuel_l_per_100km": 11.1,
        "private_car_co2_kg_per_liter": 2.35,
        "private_car_speed_kmph":       80.0,
    },
}

with open(out_path, "w") as f:
    json.dump(cfg, f, indent=2)

print(f"  Wrote config: {out_path}")
PYEOF
  done
}

# -----------------------------------------------------------------------------
# Generate stratified, nested commuter subsets for each demand level.
# All fractions are nested: x0.25 ⊂ x0.50 ⊂ x0.75 ⊂ x1.00.
# Within each 20-minute train slot, commuters are shuffled once with
# DEMAND_SAMPLE_SEED=42 and the first k are taken for each fraction.
# x1.00 is a straight copy of the original file.
# -----------------------------------------------------------------------------
generate_demand() {
  mkdir -p \
    "${INPUT_DIR}/x0.25" \
    "${INPUT_DIR}/x0.50" \
    "${INPUT_DIR}/x0.75" \
    "${INPUT_DIR}/x1.00"

  "$PYTHON_BIN" - \
      "$FULL_COMMUTERS_CSV" \
      "$INPUT_DIR" \
      "$DEMAND_SAMPLE_SEED" << 'PYEOF'
import sys, csv, math, random, shutil
from collections import defaultdict
from pathlib import Path

full_csv   = sys.argv[1]
input_dir  = Path(sys.argv[2])
rng_seed   = int(sys.argv[3])

FRACTIONS = [0.25, 0.50, 0.75, 1.00]
LABELS    = ["x0.25", "x0.50", "x0.75", "x1.00"]

# --- Read full commuter list ------------------------------------------------
with open(full_csv, newline="") as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    rows = list(reader)

if fieldnames is None:
    raise RuntimeError(f"No header found in {full_csv}")
if "drop_off_latest" not in fieldnames:
    raise RuntimeError(
        f"Expected column 'drop_off_latest' in {full_csv}, "
        f"but columns are: {fieldnames}"
    )

n_total = len(rows)

# --- Assign each commuter to a 20-minute train-aligned slot -----------------
# Slot is derived from drop_off_latest (station deadline) using floor division.
# This preserves the Myki-derived temporal demand profile.
# Slot indices 0..7 map to: 07:00, 07:20, 07:40, 08:00, 08:20, 08:40, 09:00, 09:20

SLOT_START_MIN = 420   # 07:00
SLOT_INTERVAL  = 20

def time_to_slot(t, start_min=SLOT_START_MIN, interval=SLOT_INTERVAL):
    t = str(t).strip()
    if ":" not in t:
        raise ValueError(f"Expected HH:MM drop_off_latest, got: {t!r}")
    h, m = t.split(":")[:2]
    mins = int(h) * 60 + int(m)
    return (mins - start_min) // interval

def slot_label(slot_idx):
    total_min = SLOT_START_MIN + slot_idx * SLOT_INTERVAL
    return f"{total_min // 60:02d}:{total_min % 60:02d}"

EXPECTED_FULL_SLOT_COUNTS = {0: 194, 1: 244, 2: 274, 3: 284,
                              4: 190, 5: 136, 6: 104, 7: 39}

slot_groups: dict[int, list[int]] = defaultdict(list)
for idx, row in enumerate(rows):
    slot = time_to_slot(row["drop_off_latest"])
    slot_groups[slot].append(idx)

slots = sorted(slot_groups.keys())

# --- Validate that slot counts match the known full-demand distribution -----
slot_ok = True
for s, expected in EXPECTED_FULL_SLOT_COUNTS.items():
    actual = len(slot_groups.get(s, []))
    if actual != expected:
        print(f"WARNING: slot {slot_label(s)} expected {expected} commuters, "
              f"got {actual}. Check drop_off_latest slotting.", file=__import__('sys').stderr)
        slot_ok = False
unexpected = [s for s in slot_groups if s not in EXPECTED_FULL_SLOT_COUNTS]
if unexpected:
    labels = [slot_label(s) for s in unexpected]
    print(f"WARNING: unexpected slot indices {unexpected} ({labels}). "
          f"These commuters fall outside the 07:00-09:20 window.",
          file=__import__('sys').stderr)
    slot_ok = False
if slot_ok:
    print("  Slot validation: all 8 slot counts match expected full-demand distribution.")

# --- Shuffle each slot group once with the fixed seed -----------------------
rng = random.Random(rng_seed)
shuffled: dict[int, list[int]] = {}
for slot in slots:
    group = list(slot_groups[slot])
    rng.shuffle(group)
    shuffled[slot] = group

# --- Sample fraction, rounding with largest-remainder method ----------------
def sample_indices(fraction: float) -> list[int]:
    target = int(fraction * n_total + 0.5)  # standard arithmetic rounding

    floor_counts: dict[int, int] = {}
    remainders: list[tuple[float, int]] = []
    total_floor = 0
    for slot in slots:
        exact       = fraction * len(shuffled[slot])
        fc          = math.floor(exact)
        remainder   = exact - fc
        floor_counts[slot] = fc
        total_floor += fc
        remainders.append((remainder, slot))

    # Distribute leftover seats to slots with largest fractional remainders
    remaining = target - total_floor
    remainders.sort(key=lambda x: -x[0])
    for i in range(remaining):
        slot = remainders[i][1]
        max_available = len(shuffled[slot])
        if floor_counts[slot] < max_available:
            floor_counts[slot] += 1

    selected: list[int] = []
    for slot in slots:
        selected.extend(shuffled[slot][: floor_counts[slot]])

    selected.sort()  # restore original row order
    return selected

# --- Write each demand level -------------------------------------------------
summary_rows = []
prev_indices: set[int] = set()

for label, fraction in zip(LABELS, FRACTIONS):
    out_csv = input_dir / label / "commuters.csv"

    if fraction == 1.00:
        shutil.copy(full_csv, out_csv)
        actual_count = n_total
        selected_indices = list(range(n_total))
    else:
        selected_indices = sample_indices(fraction)
        actual_count = len(selected_indices)
        selected_set = set(selected_indices)
        with open(out_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for idx in selected_indices:
                writer.writerow(rows[idx])

    target_count = int(fraction * n_total + 0.5) if fraction < 1.00 else n_total
    print(f"  {label}: target={target_count}  actual={actual_count}  file={out_csv}")

    # Per-slot breakdown for summary
    selected_set = set(selected_indices)
    for slot in slots:
        orig_slot_indices  = slot_groups[slot]
        sampled_slot_count = sum(1 for i in orig_slot_indices if i in selected_set)
        summary_rows.append({
            "demand_level":        label,
            "demand_fraction":     fraction,
            "target_total_count":  target_count,
            "actual_total_count":  actual_count,
            "slot_index":          slot,
            "slot_label":          slot_label(slot),
            "original_slot_count": len(orig_slot_indices),
            "sampled_slot_count":  sampled_slot_count,
        })

# --- Write summary CSV -------------------------------------------------------
summary_csv = input_dir / "demand_level_summary.csv"
summary_fields = [
    "demand_level", "demand_fraction", "target_total_count",
    "actual_total_count", "slot_index", "slot_label",
    "original_slot_count", "sampled_slot_count",
]
with open(summary_csv, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=summary_fields)
    writer.writeheader()
    writer.writerows(summary_rows)

print(f"  Summary: {summary_csv}")
PYEOF
}

# -----------------------------------------------------------------------------
# Build jobs.txt — one line per (fleet, demand_level, seed).
# Existing jobs are always listed; RESUME filtering happens in run_one.
# -----------------------------------------------------------------------------
build_jobs() {
  > "$JOBS_FILE"
  for fleet in "${FLEETS[@]}"; do
    for demand in "${DEMAND_LEVELS[@]}"; do
      for seed in $(seq 1 "$NUM_SEEDS"); do
        local config_path="${CONFIG_DIR}/${fleet}.json"
        local commuters_csv="${INPUT_DIR}/${demand}/commuters.csv"
        local run_dir="${RESULTS_ROOT}/${fleet}/${demand}/seed_${seed}"
        printf "%s %s %s %s %s %s\n" \
          "$fleet" "$demand" "$seed" "$config_path" "$commuters_csv" "$run_dir" \
          >> "$JOBS_FILE"
      done
    done
  done
}

# -----------------------------------------------------------------------------
# Run one simulation job.
# -----------------------------------------------------------------------------
run_one() {
  local fleet="$1" demand="$2" seed="$3"
  local config_path="$4" commuters_csv="$5" run_dir="$6"
  local log_file="${run_dir}/simulation.log"

  if [[ "${RESUME:-1}" == "1" ]] && \
     [[ -f "${run_dir}/comparison.json" ]] && \
     [[ -f "${run_dir}/metrics.json"    ]] && \
     [[ -s "${run_dir}/metrics.json"    ]] && \
     [[ -f "${run_dir}/baseline.json"   ]]; then
    printf "[SKIP] %s %s seed=%s already complete\n" "$fleet" "$demand" "$seed"
    progress_tick; return 0
  fi

  mkdir -p "$run_dir"
  cp "$config_path" "${run_dir}/config.json"
  printf "[RUN] fleet=%s demand=%s seed=%s\n" "$fleet" "$demand" "$seed"

  if "${PYTHON_BIN}" "${SIM_SCRIPT}" \
      "${commuters_csv}" \
      "${STATIONS_CSV}" \
      "${MATRICES_DIR}" \
      "${run_dir}/assignments.csv" \
      "${run_dir}/av_routes.csv" \
      "${config_path}" \
      "${run_dir}/baseline.json" \
      "${run_dir}/metrics.json" \
      "${run_dir}/comparison.json" \
      "${seed}" \
      > "${log_file}" 2>&1; then
    printf "[DONE] fleet=%s demand=%s seed=%s\n" "$fleet" "$demand" "$seed"
    progress_tick
    return 0
  else
    printf "[FAIL] fleet=%s demand=%s seed=%s — see %s\n" \
      "$fleet" "$demand" "$seed" "$log_file" >&2
    progress_tick
    return 1
  fi
}
export -f run_one

progress_tick() {
  local lock_dir="${PROG_LOCK}.lock"
  while ! mkdir "$lock_dir" 2>/dev/null; do sleep 0.02; done
  local done; done=$(<"$PROG_COUNT")
  done=$((done + 1))
  echo "$done" > "$PROG_COUNT"
  printf "[progress] %d/%d completed\n" "$done" "$TOTAL"
  rmdir "$lock_dir"
}
export -f progress_tick

# =============================================================================
# Main
# =============================================================================

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     PyVRP PILOT FLEET DEMAND SENSITIVITY — 112 SEATS FIXED     ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Experiment    : ${EXPERIMENT}"
echo "  Results root  : ${RESULTS_ROOT}"
echo "  Config dir    : ${CONFIG_DIR}"
echo "  Input dir     : ${INPUT_DIR}"
echo "  Matrix dir    : ${MATRICES_DIR}"
echo ""
echo "  Pilot fleets (each exactly 112 seats):"
for fleet in "${FLEETS[@]}"; do
  read -r ns nm nc nb seats < <(get_fleet_counts "$fleet")
  printf "    %-22s  scooters=%2d  mopeds=%2d  cars=%d  minibuses=%2d  seats=%d\n" \
    "$fleet" "$ns" "$nm" "$nc" "$nb" "$seats"
done
echo ""
echo "  Demand levels (fractions of 1465 commuters):"
echo "    x0.25 ≈ 366   x0.50 ≈ 733   x0.75 ≈ 1099   x1.00 = 1465 (overload)"
echo "  Note: x1.00 is intentionally an overload/stress-test case."
echo ""
echo "  Seeds         : ${NUM_SEEDS}"
echo "  Time limit    : ${TIME_LIMIT}s"
echo "  DRY_RUN       : ${DRY_RUN}"
echo "  RESUME        : ${RESUME}"
echo "  JOBS          : ${JOBS}"
echo "  DEMAND_SAMPLE_SEED: ${DEMAND_SAMPLE_SEED}"
echo ""

# Validate prerequisites
command -v "$PYTHON_BIN" >/dev/null 2>&1 \
  || { echo "ERROR: Python not found: $PYTHON_BIN"; exit 1; }
for f in "$SIM_SCRIPT" "$FULL_COMMUTERS_CSV" "$STATIONS_CSV"; do
  [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

mkdir -p "$RESULTS_ROOT" "$CONFIG_DIR" "$INPUT_DIR"

# Generate demand subsets
echo "Generating demand subsets (seed=${DEMAND_SAMPLE_SEED})..."
generate_demand
echo ""

# Generate fleet configs
echo "Generating fleet configs..."
generate_configs
echo ""

# Build job list
echo "Building job list..."
build_jobs

TOTAL=$(wc -l < "$JOBS_FILE" | tr -d ' ')
RUNNABLE=0
if [[ "$RESUME" == "1" ]]; then
  while IFS=' ' read -r fleet demand seed config_path commuters_csv run_dir; do
    if [[ ! -f "${run_dir}/comparison.json" ]] || \
       [[ ! -f "${run_dir}/metrics.json"    ]] || \
       [[ ! -s "${run_dir}/metrics.json"    ]] || \
       [[ ! -f "${run_dir}/baseline.json"   ]]; then
      RUNNABLE=$((RUNNABLE + 1))
    fi
  done < "$JOBS_FILE"
else
  RUNNABLE=$TOTAL
fi

echo "  Total planned jobs  : ${TOTAL}  (${NUM_SEEDS} seeds × 4 fleets × 4 demand levels)"
echo "  Runnable after RESUME filter: ${RUNNABLE}"
echo ""

if [[ "$DRY_RUN" == "1" ]]; then
  if [[ -f "${INPUT_DIR}/demand_level_summary.csv" ]]; then
    echo ""
    echo "Demand level summary:"
    cat "${INPUT_DIR}/demand_level_summary.csv"
    echo ""
  fi
  echo "DRY RUN — job list (fleet demand seed config_path commuters_csv run_dir):"
  cat "$JOBS_FILE"
  echo ""
  echo "  (${TOTAL} total jobs, ${RUNNABLE} runnable)"
  exit 0
fi

PROG_COUNT=$(mktemp /tmp/pilot_demand_prog.XXXXXX)
PROG_LOCK=$(mktemp /tmp/pilot_demand_lock.XXXXXX)
echo "0" > "$PROG_COUNT"
trap "rm -f '$PROG_COUNT' '$PROG_LOCK'" EXIT
export PROG_COUNT PROG_LOCK TOTAL

export PYTHON_BIN SIM_SCRIPT STATIONS_CSV MATRICES_DIR RESULTS_ROOT CONFIG_DIR INPUT_DIR RESUME

START=$(date +%s)

if command -v parallel &>/dev/null; then
  parallel \
    --jobs "$JOBS" \
    --colsep ' ' \
    --eta \
    --joblog "$JOBLOG" \
    run_one {1} {2} {3} {4} {5} {6} \
    :::: "$JOBS_FILE"
else
  echo "WARNING: GNU parallel not found, running sequentially"
  while IFS=' ' read -r fleet demand seed config_path commuters_csv run_dir; do
    run_one "$fleet" "$demand" "$seed" "$config_path" "$commuters_csv" "$run_dir"
  done < "$JOBS_FILE"
fi

END=$(date +%s)

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PILOT FLEET DEMAND SENSITIVITY COMPLETE                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
printf "  Total time : %ds\n" $((END - START))
echo "  Results    : ${RESULTS_ROOT}"
echo ""

FAILED=$(find "$RESULTS_ROOT" -name "simulation.log" -print0 \
  | xargs -0 grep -El "Error|Traceback|ValueError|FAIL" 2>/dev/null \
  | wc -l | tr -d " ")
[[ "$FAILED" -gt 0 ]] \
  && echo "  WARNING: ${FAILED} run(s) may have failed (check simulation.log files)" \
  || echo "  No failures detected"

echo ""
echo "  Next: python3 experiments/scripts/plot_pilot_fleet_demand_sensitivity.py"
echo ""
