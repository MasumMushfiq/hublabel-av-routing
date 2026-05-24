#!/usr/bin/env bash
# =============================================================================
# run_representative_fleet_comparison.sh
# Gather/copy representative fleet outputs from the already-completed
# fleet composition grid experiment (224 seats, 180s, 15 seeds).
#
# Source:
#   experiments/results/fleet_composition_grid_224seats/
# Destination:
#   experiments/results/representative_fleet_comparison/
#
# Usage:
#   bash experiments/scripts/run_representative_fleet_comparison.sh
#   bash experiments/scripts/run_representative_fleet_comparison.sh --dry-run
#   LABELS_OVERRIDE="balanced vmt_oriented" bash experiments/scripts/run_representative_fleet_comparison.sh
#   FORCE=1 bash experiments/scripts/run_representative_fleet_comparison.sh
#   SRC_ROOT=experiments/test_results/fleet_composition_grid_224seats \
#       DST_ROOT=experiments/test_results/representative_fleet_comparison \
#       bash experiments/scripts/run_representative_fleet_comparison.sh
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SRC_ROOT="${SRC_ROOT:-$ROOT/experiments/results/fleet_composition_grid_224seats}"
DST_ROOT="${DST_ROOT:-${OUTPUT_DIR:-$ROOT/experiments/results/representative_fleet_comparison}}"
if [[ "$SRC_ROOT" != /* ]]; then
    SRC_ROOT="$ROOT/$SRC_ROOT"
fi
if [[ "$DST_ROOT" != /* ]]; then
    DST_ROOT="$ROOT/$DST_ROOT"
fi

DRY_RUN=${DRY_RUN:-0}
FORCE=${FORCE:-0}
LABELS_OVERRIDE=${LABELS_OVERRIDE:-}
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

# display_label|source_condition|destination_label|category|description
MAPPINGS=(
    "balanced|comp_S25_M25_C25_MB25|balanced|heterogeneous|Balanced 25/25/25/25 fleet"
    "vmt_oriented|comp_S25_M25_C0_MB50|vmt_oriented|heterogeneous|VMT-oriented minibus-heavy fleet"
    "co2_oriented|comp_S25_M50_C0_MB25|co2_oriented|heterogeneous|CO2-oriented moped-heavy fleet"
    "all_scooter|comp_S100_M0_C0_MB0|all_scooter|homogeneous|All-scooter baseline"
    "all_moped|comp_S0_M100_C0_MB0|all_moped|homogeneous|All-moped baseline"
    "all_car|comp_S0_M0_C100_MB0|all_car|homogeneous|All-car baseline"
    "all_minibus|comp_S0_M0_C0_MB100|all_minibus|homogeneous|All-minibus baseline"
)

BASE_LABELS=(balanced vmt_oriented co2_oriented all_scooter all_moped all_car all_minibus)

if [[ -n "$LABELS_OVERRIDE" ]]; then
    # shellcheck disable=SC2206
    LABELS=($LABELS_OVERRIDE)
else
    LABELS=("${BASE_LABELS[@]}")
fi

declare -A SELECTED=()
for l in "${LABELS[@]}"; do
    SELECTED["$l"]=1
done

cat <<MSG

╔════════════════════════════════════════════════════════════════╗
║      GATHER REPRESENTATIVE FLEET COMPARISON RESULTS           ║
╚════════════════════════════════════════════════════════════════╝
    Source      : $SRC_ROOT
    Destination : $DST_ROOT
    Labels      : ${LABELS[*]}
    FORCE       : $FORCE
    DRY_RUN     : $DRY_RUN
MSG

[[ -d "$SRC_ROOT" ]] || { echo "ERROR: Missing source root: $SRC_ROOT"; exit 1; }

if [[ "$FORCE" == "1" ]]; then
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "DRY RUN: would remove destination root: $DST_ROOT"
    else
        rm -rf "$DST_ROOT"
        echo "Removed destination root due to FORCE=1: $DST_ROOT"
    fi
fi

if [[ "$DRY_RUN" == "0" ]]; then
    mkdir -p "$DST_ROOT"
fi

total_conditions_copied=0
total_runs_copied=0
total_runs_skipped=0

missing_source_conditions=()
skipped_incomplete_runs=()

for entry in "${MAPPINGS[@]}"; do
    IFS='|' read -r display_label source_condition destination_label category description <<< "$entry"

    if [[ -z "${SELECTED[$destination_label]+x}" ]]; then
        continue
    fi

    src_cond_dir="$SRC_ROOT/$source_condition"
    dst_cond_dir="$DST_ROOT/$destination_label"

    if [[ ! -d "$src_cond_dir" ]]; then
        echo "WARNING: Missing source condition: $source_condition"
        missing_source_conditions+=("$source_condition")
        continue
    fi

    condition_had_copy=0
    echo ""
    echo "[$destination_label] source=$source_condition"

    found_any_run=0
    for src_run_dir in "$src_cond_dir"/run_*; do
        [[ -d "$src_run_dir" ]] || continue
        found_any_run=1

        run_name="$(basename "$src_run_dir")"
        dst_run_dir="$dst_cond_dir/$run_name"

        # Required files
        if [[ ! -f "$src_run_dir/metrics.json" ]] || [[ ! -f "$src_run_dir/baseline.json" ]] || [[ ! -f "$src_run_dir/comparison.json" ]]; then
            echo "  WARNING: skipping incomplete run: $source_condition/$run_name (missing required metrics/baseline/comparison)"
            skipped_incomplete_runs+=("$source_condition/$run_name")
            total_runs_skipped=$((total_runs_skipped + 1))
            continue
        fi

        if [[ "$FORCE" != "1" ]] && [[ -d "$dst_run_dir" ]]; then
            echo "  skip existing: $destination_label/$run_name"
            total_runs_skipped=$((total_runs_skipped + 1))
            continue
        fi

        if [[ "$DRY_RUN" == "1" ]]; then
            echo "  would copy: $source_condition/$run_name -> $destination_label/$run_name"
            total_runs_copied=$((total_runs_copied + 1))
            condition_had_copy=1
            continue
        fi

        mkdir -p "$dst_run_dir"

        cp -f "$src_run_dir/metrics.json" "$dst_run_dir/metrics.json"
        cp -f "$src_run_dir/baseline.json" "$dst_run_dir/baseline.json"
        cp -f "$src_run_dir/comparison.json" "$dst_run_dir/comparison.json"

        [[ -f "$src_run_dir/assignments.csv" ]] && cp -f "$src_run_dir/assignments.csv" "$dst_run_dir/assignments.csv"
        [[ -f "$src_run_dir/av_routes.csv" ]] && cp -f "$src_run_dir/av_routes.csv" "$dst_run_dir/av_routes.csv"
        [[ -f "$src_run_dir/config.json" ]] && cp -f "$src_run_dir/config.json" "$dst_run_dir/config.json"
        [[ -f "$src_run_dir/simulation.log" ]] && cp -f "$src_run_dir/simulation.log" "$dst_run_dir/simulation.log"

        echo "  copied: $source_condition/$run_name -> $destination_label/$run_name"
        total_runs_copied=$((total_runs_copied + 1))
        condition_had_copy=1
    done

    if [[ "$found_any_run" == "0" ]]; then
        echo "  WARNING: no run_* folders found under $source_condition"
    fi

    if [[ "$condition_had_copy" == "1" ]]; then
        total_conditions_copied=$((total_conditions_copied + 1))
    fi
done

mapping_csv="$DST_ROOT/representative_fleet_mapping.csv"
if [[ "$DRY_RUN" == "1" ]]; then
    echo ""
    echo "DRY RUN: would write mapping CSV: $mapping_csv"
else
    mkdir -p "$DST_ROOT"
    {
        echo "display_label,source_condition,destination_label,category,description"
        for entry in "${MAPPINGS[@]}"; do
            IFS='|' read -r display_label source_condition destination_label category description <<< "$entry"
            if [[ -n "${SELECTED[$destination_label]+x}" ]]; then
                printf "%s,%s,%s,%s,%s\n" "$display_label" "$source_condition" "$destination_label" "$category" "$description"
            fi
        done
    } > "$mapping_csv"
    echo ""
    echo "Wrote: $mapping_csv"
fi

echo ""
echo "╔════════════════════════════════════════════════════════════════╗"
echo "║        REPRESENTATIVE FLEET GATHER/COPY COMPLETE              ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo "  Total conditions copied : $total_conditions_copied"
echo "  Total runs copied       : $total_runs_copied"
echo "  Total runs skipped      : $total_runs_skipped"
echo "  Missing source conds    : ${#missing_source_conditions[@]}"
echo "  Incomplete runs skipped : ${#skipped_incomplete_runs[@]}"

if [[ ${#missing_source_conditions[@]} -gt 0 ]]; then
    echo ""
    echo "Missing source conditions:"
    for c in "${missing_source_conditions[@]}"; do
        echo "  - $c"
    done
fi

if [[ ${#skipped_incomplete_runs[@]} -gt 0 ]]; then
    echo ""
    echo "Skipped incomplete runs:"
    for r in "${skipped_incomplete_runs[@]}"; do
        echo "  - $r"
    done
fi

echo ""
echo "Next: python3 experiments/scripts/plot_representative_fleet_comparison.py"
