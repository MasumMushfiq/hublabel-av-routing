#!/usr/bin/env bash
# =============================================================================
# run_fleet_composition_grid.sh
# Fleet composition grid experiment — fixed 224-seat capacity sweep.
#
# Purpose:
#   Enumerate all 25%-increment seat-share combinations across Scooter,
#   Moped, Car, and Minibus with total capacity fixed at 224 seats. Writes
#   one JSON config per composition plus a composition_metadata.csv.
#
# Design:
#   Grid    : shares in {0,25,50,75,100} with s+m+c+b == 100%
#   Total   : 35 compositions × N_SEEDS (default 15) jobs
#   Capacity: 224 seats fixed across all conditions (56 seats per 25% block)
#   Demand  : 1465 Myki commuters
#   Solver  : PyVRP/HGS, default time limit 180s, fixed_slots 20 min, buffer 0,
#             penalty 'none'
#
# Results and configs:
#   experiments/results/fleet_composition_grid_224seats/
#   experiments/results/fleet_composition_grid_224seats/configs/
#
# Environment variables:
#   --dry-run        list jobs only (also supported as first arg)
#   DRY_RUN=1        list jobs only, do not run
#   CONFIG_ONLY=1    only generate configs and exit
#   RESUME=1         skip completed runs (default: skip if done)
#   PARALLEL_JOBS=N  parallel workers (default: ncpu-2)
#   LABELS_OVERRIDE  space-separated list of condition labels to run only
#   TIME_LIMIT_SECONDS   solver time limit (default: 180)
#   N_SEEDS              number of random seeds (default: 15)
#   OUTPUT_DIR           output root (default: experiments/results/fleet_composition_grid_224seats)
#                        RESULTS_DIR is also accepted as a legacy alias
#   CONFIGS_DIR          configs output dir (default: OUTPUT_DIR/configs)
#   BASE_CONFIG          canonical config template (default: config/base_config.json)
#   COMMUTERS_CSV        commuter demand file (default: $ROOT/files/inputs/commuters.csv)
#   MATRICES_DIR         distance/duration matrix dir (default: $ROOT/dataset/MELTON/melton_generic_matrix)
#   STATIONS_CSV         station file (default: $ROOT/files/inputs/stations.csv)
#
# Usage (from hub_label/ root):
#   bash experiments/scripts/run_fleet_composition_grid.sh
#   bash experiments/scripts/run_fleet_composition_grid.sh --dry-run
#   CONFIG_ONLY=1 bash experiments/scripts/run_fleet_composition_grid.sh
#   PARALLEL_JOBS=8 N_SEEDS=5 bash experiments/scripts/run_fleet_composition_grid.sh
#   OUTPUT_DIR=experiments/test_results/fleet_composition_grid_224seats \
#       TIME_LIMIT_SECONDS=60 N_SEEDS=1 bash experiments/scripts/run_fleet_composition_grid.sh
# =============================================================================

set -euo pipefail

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# ── Parallelism ───────────────────────────────────────────────────────────────
TOTAL_CORES=$(sysctl -n hw.logicalcpu 2>/dev/null || nproc 2>/dev/null || echo 4)
PARALLEL_JOBS=${PARALLEL_JOBS:-$(( TOTAL_CORES > 2 ? TOTAL_CORES - 2 : 1 ))}

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PYVRP_SCRIPT="$ROOT/python/simulate_first_mile_pyvrp.py"
COMMUTERS_CSV="${COMMUTERS_CSV:-$ROOT/files/inputs/commuters.csv}"
STATIONS_CSV="${STATIONS_CSV:-$ROOT/files/inputs/stations.csv}"
MATRICES_DIR="${MATRICES_DIR:-$ROOT/dataset/MELTON/melton_generic_matrix}"
BASE_CONFIG=${BASE_CONFIG:-config/base_config.json}
if [[ "$BASE_CONFIG" != /* ]]; then
    BASE_CONFIG="$ROOT/$BASE_CONFIG"
fi

EXPERIMENT="fleet_composition_grid_224seats"
DEFAULT_RESULTS_DIR="$ROOT/experiments/results/$EXPERIMENT"
RESULTS_DIR="${OUTPUT_DIR:-${RESULTS_DIR:-$DEFAULT_RESULTS_DIR}}"
if [[ "$RESULTS_DIR" != /* ]]; then
    RESULTS_DIR="$ROOT/$RESULTS_DIR"
fi
CONFIGS_DIR="${CONFIGS_DIR:-$RESULTS_DIR/configs}"
if [[ "$CONFIGS_DIR" != /* ]]; then
    CONFIGS_DIR="$ROOT/$CONFIGS_DIR"
fi

# ── Parameters ────────────────────────────────────────────────────────────────
TIME_LIMIT_SECONDS=${TIME_LIMIT_SECONDS:-180}
N_SEEDS=${N_SEEDS:-15}
DRY_RUN=${DRY_RUN:-0}
RESUME=${RESUME:-1}
# Optional overrides
LABELS_OVERRIDE=${LABELS_OVERRIDE:-}
CONFIG_ONLY=${CONFIG_ONLY:-0}

# ── Step 1: Generate all 35 configs via inline Python ────────────────────────
generate_configs() {
    rm -rf "$CONFIGS_DIR"
    mkdir -p "$CONFIGS_DIR"
    python3 - "$CONFIGS_DIR" "$TIME_LIMIT_SECONDS" "$BASE_CONFIG" << 'PYEOF'
import sys, json, csv, copy
from itertools import product

CONFIGS_DIR = sys.argv[1]
TIME_LIMIT = int(sys.argv[2])
BASE_CONFIG = sys.argv[3]
SHARES = [0,25,50,75,100]
SEATS_PER_25 = 56

with open(BASE_CONFIG, "r", encoding="utf-8") as f:
    base_cfg = json.load(f)

base_vehicle_by_name = {
    v["name"]: v
    for v in base_cfg["fleet"]["vehicle_types"]
}
vehicle_order = ["Scooter", "Moped", "Car", "Minibus"]
missing = [name for name in vehicle_order if name not in base_vehicle_by_name]
if missing:
    raise ValueError(f"Base config missing vehicle definitions: {missing}")
CAPS = {name: int(base_vehicle_by_name[name]["capacity"]) for name in vehicle_order}

# Build compositions
comps = []
for ss, ms, cs, bs in product(SHARES, repeat=4):
    if ss + ms + cs + bs != 100:
        continue
    s_seats = (ss // 25) * SEATS_PER_25
    m_seats = (ms // 25) * SEATS_PER_25
    c_seats = (cs // 25) * SEATS_PER_25
    b_seats = (bs // 25) * SEATS_PER_25

    ns = int(s_seats // CAPS["Scooter"]) if s_seats > 0 else 0
    nm = int(m_seats // CAPS["Moped"])   if m_seats > 0 else 0
    nc = int(c_seats // CAPS["Car"])     if c_seats > 0 else 0
    nb = int(b_seats // CAPS["Minibus"]) if b_seats > 0 else 0

    total = s_seats + m_seats + c_seats + b_seats
    total_v = ns + nm + nc + nb
    label = f"comp_S{ss}_M{ms}_C{cs}_MB{bs}"
    comps.append({
        "condition": label,
        "target_scooter_share": ss,
        "target_moped_share": ms,
        "target_car_share": cs,
        "target_minibus_share": bs,
        "scooter_count": ns,
        "moped_count": nm,
        "car_count": nc,
        "minibus_count": nb,
        "actual_scooter_seats": s_seats,
        "actual_moped_seats": m_seats,
        "actual_car_seats": c_seats,
        "actual_minibus_seats": b_seats,
        "actual_scooter_share": round(s_seats / total * 100, 1) if total else 0,
        "actual_moped_share": round(m_seats / total * 100, 1) if total else 0,
        "actual_car_share": round(c_seats / total * 100, 1) if total else 0,
        "actual_minibus_share": round(b_seats / total * 100, 1) if total else 0,
        "total_fleet_seats": total,
        "total_fleet_vehicles": total_v,
    })

# Print composition table
print(f"\n  {'Condition':<35} {'S%':>4} {'M%':>4} {'C%':>4} {'B%':>4} | {'S#':>4} {'M#':>4} {'C#':>4} {'B#':>4} | {'Seats':>5} {'Veh':>4}")
print(f"  {'-'*110}")
for c in comps:
    ok = '' if c['total_fleet_seats'] == 224 else f" ← {c['total_fleet_seats']}"
    print(f"  {c['condition']:<35} {c['target_scooter_share']:>4} {c['target_moped_share']:>4} {c['target_car_share']:>4} {c['target_minibus_share']:>4} | {c['scooter_count']:>4} {c['moped_count']:>4} {c['car_count']:>4} {c['minibus_count']:>4} | {c['total_fleet_seats']:>5}{ok} {c['total_fleet_vehicles']:>4}")

not224 = [c for c in comps if c['total_fleet_seats'] != 224]
print(f"\n  Compositions not exactly 224 seats: {len(not224)}")
print(f"  Total compositions: {len(comps)}\n")

# Write configs
for c in comps:
    ns = c['scooter_count']; nm = c['moped_count']
    nc = c['car_count'];     nb = c['minibus_count']
    cfg = copy.deepcopy(base_cfg)
    cfg['experiment_name'] = c['condition']
    cfg['composition_metadata'] = {k: c[k] for k in c if k != 'condition'}
    cfg.setdefault('solver_config', {})['time_limit_seconds'] = TIME_LIMIT
    cfg['fleet']['vehicle_types'] = []

    for vt, n in [('Scooter', ns), ('Moped', nm), ('Car', nc), ('Minibus', nb)]:
        if n == 0:
            continue
        vehicle_cfg = copy.deepcopy(base_vehicle_by_name[vt])
        vehicle_cfg['fleet_size'] = n
        cfg['fleet']['vehicle_types'].append(vehicle_cfg)

    cfg_path = f"{CONFIGS_DIR}/{c['condition']}.json"
    with open(cfg_path, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)

# Write metadata CSV
meta_path = f"{CONFIGS_DIR}/composition_metadata.csv"
fields = list(comps[0].keys())
with open(meta_path, 'w', newline='') as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(comps)

print(f"  Written {len(comps)} configs to: {CONFIGS_DIR}/")
print(f"  Metadata CSV: {meta_path}")
PYEOF
}

# ── Step 2: Build job list ────────────────────────────────────────────────────
build_jobs() {
    local job_file="$1"
    # Build SEEDS string from N_SEEDS
    SEEDS="$(seq -s ' ' 1 $N_SEEDS)"
    python3 - "$CONFIGS_DIR" "$job_file" << 'PYEOF'
import sys, json, os

configs_dir = sys.argv[1]
job_file    = sys.argv[2]

conditions = sorted([
    f.replace(".json", "")
    for f in os.listdir(configs_dir)
    if f.endswith(".json") and f != "composition_metadata.csv"
    and not f.endswith(".csv")
])

seeds_env = os.environ.get("SEEDS", "1")
seeds = [int(s) for s in seeds_env.split()]
lines = []
for cond in conditions:
    for seed in seeds:
        lines.append(f"{cond} {seed}")

with open(job_file, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"  {len(conditions)} conditions × {len(seeds)} seeds = {len(lines)} jobs")
PYEOF
}

# ── Step 3: Worker function ───────────────────────────────────────────────────
run_one() {
    local condition="$1"
    local seed="$2"
    local config_path="$CONFIGS_DIR/${condition}.json"
    local out_dir="$RESULTS_DIR/$condition/run_$seed"
    local log_file="$out_dir/simulation.log"

    if [[ "${RESUME:-1}" == "1" ]] && \
       [[ -f "$out_dir/metrics.json"    ]] && \
       [[ -s "$out_dir/metrics.json"    ]] && \
       [[ -f "$out_dir/baseline.json"   ]] && \
       [[ -f "$out_dir/comparison.json" ]]; then
        printf "[%s seed_%s] already done, skipping\n" "$condition" "$seed"
        progress_tick; return 0
    fi

    mkdir -p "$out_dir"
    # Save config copy into run folder for reproducibility
    cp "$config_path" "$out_dir/config.json"
    printf "[%s seed_%s] starting...\n" "$condition" "$seed"

    if python3 "$PYVRP_SCRIPT" \
            "$COMMUTERS_CSV" \
            "$STATIONS_CSV" \
            "$MATRICES_DIR" \
            "$out_dir/assignments.csv" \
            "$out_dir/av_routes.csv" \
            "$config_path" \
            "$out_dir/baseline.json" \
            "$out_dir/metrics.json" \
            "$out_dir/comparison.json" \
            "$seed" \
        > "$log_file" 2>&1; then
        printf "[%s seed_%s] done\n" "$condition" "$seed"
    else
        printf "[%s seed_%s] FAILED — see %s\n" \
            "$condition" "$seed" "$log_file" >&2
    fi
    progress_tick
}
export -f run_one

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

# ── Main ──────────────────────────────────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        PyVRP FLEET COMPOSITION GRID — 224 SEATS FIXED          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "  Demand   : 1465 Myki commuters"
echo "  Capacity : 224 seats fixed across all conditions"
echo "  Balanced reference: comp_S25_M25_C25_MB25 = 56S / 28M / 14C / 7MB"
echo "  Solver   : ${TIME_LIMIT_SECONDS}s, fixed_slots 20 min, buffer 0, penalty none"
echo "  Grid     : 25% seat-share increments, 35 compositions"
echo "  Seeds    : $N_SEEDS"
echo "  Parallel : $PARALLEL_JOBS workers ($TOTAL_CORES cores, 2 reserved)"
echo "  Output   : $RESULTS_DIR"
echo "  Base cfg : $BASE_CONFIG"
echo ""

# Validate prereqs
for f in "$PYVRP_SCRIPT" "$COMMUTERS_CSV" "$STATIONS_CSV" "$BASE_CONFIG"; do
    [[ -f "$f" ]] || { echo "ERROR: Missing file: $f"; exit 1; }
done
[[ -d "$MATRICES_DIR" ]] || { echo "ERROR: Missing matrices dir: $MATRICES_DIR"; exit 1; }

# Generate configs
echo "Generating fleet composition configs..."
generate_configs
echo ""

if [[ "${CONFIG_ONLY:-0}" == "1" ]]; then
    echo "CONFIG_ONLY=1: configs generated. Exiting as requested."
    exit 0
fi

# Build job list
JOB_FILE=$(mktemp /tmp/pyvrp_fcg_jobs.XXXXXX)
trap "rm -f $JOB_FILE" EXIT
echo "Building job list..."
# Export SEEDS from N_SEEDS for the helper
export SEEDS="$(seq -s ' ' 1 $N_SEEDS)"
if [[ -n "${LABELS_OVERRIDE:-}" ]]; then
    echo "  LABELS_OVERRIDE set: using only specified labels"
    # Build job file from override labels
    > "$JOB_FILE"
    for label in ${LABELS_OVERRIDE}; do
        if [[ ! -f "$CONFIGS_DIR/${label}.json" ]]; then
            echo "ERROR: requested label missing config: $label" >&2
            exit 1
        fi
        for seed in $SEEDS; do
            echo "$label $seed" >> "$JOB_FILE"
        done
    done
    TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')
    echo "  Total jobs (override): $TOTAL"
else
    build_jobs "$JOB_FILE"
    TOTAL=$(wc -l < "$JOB_FILE" | tr -d ' ')
    echo "  Total jobs: $TOTAL"
fi
echo ""

if [[ "${DRY_RUN:-0}" == "1" ]]; then
    echo "DRY RUN — first 10 jobs:"
    head -10 "$JOB_FILE"
    echo "  ..."
    echo "  (${TOTAL} total)"
    exit 0
fi

# Progress tracking
PROG_COUNT=$(mktemp /tmp/pyvrp_fcg_prog.XXXXXX)
PROG_LOCK=$(mktemp /tmp/pyvrp_fcg_lock.XXXXXX)
echo "0" > "$PROG_COUNT"
trap "rm -f $JOB_FILE $PROG_COUNT $PROG_LOCK" EXIT
export PROG_COUNT PROG_LOCK TOTAL

export CONFIGS_DIR RESULTS_DIR PYVRP_SCRIPT COMMUTERS_CSV STATIONS_CSV MATRICES_DIR RESUME

START=$(date +%s)

if command -v parallel &>/dev/null; then
    parallel \
        --jobs "$PARALLEL_JOBS" \
        --colsep ' ' \
        --eta \
        run_one {1} {2} \
        :::: "$JOB_FILE"
else
    echo "  WARNING: GNU parallel not found, running sequentially"
    while IFS=' ' read -r condition seed; do
        run_one "$condition" "$seed"
    done < "$JOB_FILE"
fi

END=$(date +%s)

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        FLEET COMPOSITION GRID COMPLETE                         ║"
echo "╚════════════════════════════════════════════════════════════════╝"
printf "  Total time: %ds\n" $((END - START))
echo ""

FAILED=$(find "$RESULTS_DIR" -name "simulation.log" \
    | xargs grep -l "Error\|Traceback" 2>/dev/null | wc -l | tr -d " ")
[[ "$FAILED" -gt 0 ]] \
    && echo "  WARNING: $FAILED run(s) may have failed" \
    || echo "  No failures detected"

echo ""
echo "  Next: python3 experiments/scripts/plot_fleet_composition_grid.py"
echo ""
