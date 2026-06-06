#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# run_pilot_fleet_demand_sensitivity.sh
#
# Fixed-fleet pilot demand sensitivity for SIGSPATIAL 2026 AV first-mile paper.
#
# Research question:
#   If an agency starts with a smaller near-112-seat pilot fleet, how much
#   observed residential-origin morning-peak demand can it support?
#
# Design:
#   - 4 default pilot fleets around the 112-seat reference
#   - 4 demand fractions of 1465 Myki commuters: x0.25, x0.50, x0.75, x1.00
#   - Demand sampled once per level (DEMAND_SAMPLE_SEED=42), nested subsets
#   - All fleets and seeds solve the same demand instance at each level
#   - Solver: PyVRP/HGS, 300s, fixed_slots 20-min, buffer 0, penalty none
#   - All-electric energy/emissions model from config/base_config.json
#   - Raw-distance objective; cost and parking are evaluation-only metrics
#   - x1.00 is intentionally an overload/stress-test case
#
# Pilot fleets:
#   balanced_pilot     : 28 scooters, 14 mopeds, 7 cars, 3 minibuses = 104 seats
#   vmt_oriented_pilot : 28 scooters, 0 mopeds, 0 cars, 10 minibuses = 108 seats
#   low_emission_pilot : 28 scooters, 42 mopeds, 0 cars, 0 minibuses = 112 seats
#   all_car_pilot      : 0 scooters, 0 mopeds, 28 cars, 0 minibuses = 112 seats
#   all_minibus_pilot  : optional diagnostic with INCLUDE_ALL_MINIBUS=1
#
# Result layout:
#   experiments/results/pilot_fleet_demand_sensitivity/
#     configs/{fleet}_{demand}.json
#     inputs/x0.25/commuters.csv  ...  inputs/demand_level_summary.csv
#     balanced_pilot/x0.25/seed_1/{assignments,av_routes,baseline,metrics,comparison}.json
#     ...
#
# Usage:
#   bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#   DRY_RUN=1 bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#   NUM_SEEDS=15 RESUME=1 JOBS=10 bash experiments/scripts/run_pilot_fleet_demand_sensitivity.sh
#
# Input overrides:
#   COMMUTERS_CSV default: $ROOT/files/inputs/commuters_residential.csv
#   STATIONS_CSV  default: $ROOT/files/inputs/stations.csv
#   MATRICES_DIR  default: $ROOT/dataset/MELTON/melton_residential_matrix
#   BASE_CONFIG   default: $ROOT/config/base_config.json
# =============================================================================

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ROOT="$ROOT_DIR"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
SIM_SCRIPT="${SIM_SCRIPT:-python/simulate_first_mile_pyvrp.py}"

EXPERIMENT="pilot_fleet_demand_sensitivity"
RESULTS_ROOT="${RESULTS_ROOT:-experiments/results/${EXPERIMENT}}"
CONFIG_DIR="${CONFIG_DIR:-${CONFIG_ROOT:-${RESULTS_ROOT}/configs}}"
INPUT_DIR="${INPUT_DIR:-${RESULTS_ROOT}/inputs}"

TIME_LIMIT="${TIME_LIMIT:-300}"
NUM_SEEDS="${NUM_SEEDS:-15}"
JOBS="${JOBS:-${PARALLEL_JOBS:-10}}"
RESUME="${RESUME:-1}"
DRY_RUN="${DRY_RUN:-0}"
DEMAND_SAMPLE_SEED="${DEMAND_SAMPLE_SEED:-42}"
INCLUDE_ALL_MINIBUS="${INCLUDE_ALL_MINIBUS:-0}"

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

FULL_COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters_residential.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_residential_matrix}"
BASE_CONFIG="${BASE_CONFIG:-$ROOT/config/base_config.json}"
if [[ "$BASE_CONFIG" != /* ]]; then
  BASE_CONFIG="$ROOT/$BASE_CONFIG"
fi

JOBS_FILE="${RESULTS_ROOT}/jobs.txt"
JOBLOG="${RESULTS_ROOT}/parallel_joblog.tsv"

declare -a FLEETS=(
  "balanced_pilot"
  "vmt_oriented_pilot"
  "low_emission_pilot"
  "all_car_pilot"
)
if [[ "$INCLUDE_ALL_MINIBUS" == "1" ]]; then
  FLEETS+=("all_minibus_pilot")
fi

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
    balanced_pilot)     echo "28 14 7 3 104" ;;   # 28+28+28+24 = 104
    vmt_oriented_pilot) echo "28 0  0 10 108" ;;  # 28+0+0+80   = 108
    low_emission_pilot) echo "28 42 0 0 112" ;;   # 28+84+0+0   = 112
    all_car_pilot)      echo "0  0 28 0 112" ;;   # 0+0+112+0   = 112
    all_minibus_pilot)  echo "0  0  0 14 112" ;;  # optional diagnostic
    *) echo "Unknown fleet: $1" >&2; exit 1 ;;
  esac
}

# -----------------------------------------------------------------------------
# Generate one JSON config per pilot fleet/demand level.
# Vehicle types with fleet_size=0 are omitted (PyVRP requires num_available>0).
# -----------------------------------------------------------------------------
generate_configs() {
  mkdir -p "$CONFIG_DIR"

  for fleet in "${FLEETS[@]}"; do
    read -r n_scooter n_moped n_car n_minibus total_seats < <(get_fleet_counts "$fleet")
    for demand in "${DEMAND_LEVELS[@]}"; do
      local config_path="${CONFIG_DIR}/${fleet}_${demand}.json"

      "$PYTHON_BIN" - \
          "$BASE_CONFIG" "$config_path" "$fleet" "$demand" "$TIME_LIMIT" \
          "$n_scooter" "$n_moped" "$n_car" "$n_minibus" "$total_seats" \
          "$DEMAND_SAMPLE_SEED" << 'PYEOF'
import copy
import json
import sys

base_config, out_path, fleet, demand_scale = sys.argv[1:5]
time_limit = int(sys.argv[5])
counts = {
    "scooter": int(sys.argv[6]),
    "moped": int(sys.argv[7]),
    "car": int(sys.argv[8]),
    "minibus": int(sys.argv[9]),
}
total_seats = int(sys.argv[10])
demand_sample_seed = int(sys.argv[11])

labels = {
    "balanced_pilot": ("Balanced pilot", "S25/M25/C25/MB25"),
    "vmt_oriented_pilot": ("VMT-Opt pilot", "S25/M0/C0/MB75"),
    "low_emission_pilot": ("Low-Emission pilot", "S25/M75/C0/MB0"),
    "all_car_pilot": ("All-Car pilot", "S0/M0/C100/MB0"),
    "all_minibus_pilot": ("All-minibus pilot", "S0/M0/C0/MB100"),
}

with open(base_config, "r", encoding="utf-8") as f:
    cfg = json.load(f)

base_vehicle_by_name = {
    vehicle["name"].lower(): vehicle
    for vehicle in cfg["fleet"]["vehicle_types"]
}
missing = [name for name in counts if name not in base_vehicle_by_name]
if missing:
    raise ValueError(f"Base config missing vehicle definitions: {missing}")

cfg["experiment_name"] = f"pilot_fleet_demand_sensitivity_{fleet}_{demand_scale}"
cfg.setdefault("solver_config", {})["time_limit_seconds"] = time_limit

display_label, seat_share_label = labels[fleet]
cfg["pilot_fleet_metadata"] = {
    "fleet_key": fleet,
    "display_label": display_label,
    "target_seat_share_label": seat_share_label,
    "total_seats": total_seats,
    "scooter_count": counts["scooter"],
    "moped_count": counts["moped"],
    "car_count": counts["car"],
    "minibus_count": counts["minibus"],
    "demand_sensitivity_experiment": True,
    "demand_scale": demand_scale,
    "demand_sample_seed": demand_sample_seed,
    "note": (
        "Near-112-seat pilot fleet for demand sensitivity. Some target "
        "seat-share compositions approximate the 112-seat pilot reference "
        "because integer vehicle counts make the exact capacity impossible."
    ),
}

cfg["fleet"]["vehicle_types"] = []
for name in ["scooter", "moped", "car", "minibus"]:
    count = counts[name]
    if count <= 0:
        continue
    vehicle_cfg = copy.deepcopy(base_vehicle_by_name[name])
    vehicle_cfg["fleet_size"] = count
    cfg["fleet"]["vehicle_types"].append(vehicle_cfg)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print(f"  Wrote config: {out_path}")
PYEOF
    done
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
        local config_path="${CONFIG_DIR}/${fleet}_${demand}.json"
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
echo "║     PyVRP PILOT FLEET DEMAND SENSITIVITY — NEAR-112 SEATS       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Experiment    : ${EXPERIMENT}"
echo "  Results root  : ${RESULTS_ROOT}"
echo "  Config dir    : ${CONFIG_DIR}"
echo "  Input dir     : ${INPUT_DIR}"
echo "  Matrix dir    : ${MATRICES_DIR}"
echo "  Base config   : ${BASE_CONFIG}"
echo ""
echo "  Pilot fleets (near the 112-seat pilot reference):"
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
echo "  INCLUDE_ALL_MINIBUS: ${INCLUDE_ALL_MINIBUS}"
echo ""

# Validate prerequisites
command -v "$PYTHON_BIN" >/dev/null 2>&1 \
  || { echo "ERROR: Python not found: $PYTHON_BIN"; exit 1; }
for f in "$SIM_SCRIPT" "$FULL_COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
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

echo "  Total planned jobs  : ${TOTAL}  (${NUM_SEEDS} seeds × ${#FLEETS[@]} fleets × 4 demand levels)"
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
