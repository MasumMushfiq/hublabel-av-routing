#!/usr/bin/env python3
"""
plot_pilot_fleet_demand_sensitivity.py
=======================================
Aggregate and plot pilot-fleet demand sensitivity results.

Expected layout produced by run_pilot_fleet_demand_sensitivity.sh:

    experiments/results/pilot_fleet_demand_sensitivity/
      balanced_pilot/
        x0.25/
          seed_1/  {comparison.json, metrics.json, assignments.csv, ...}
          seed_2/  ...
      vmt_oriented_pilot/
        x0.75/
          seed_1/  ...
      ...

Outputs (written to --output_dir):
    pilot_demand_sensitivity_runs.csv
    pilot_demand_sensitivity_summary.csv
    pilot_demand_sensitivity_combined.pdf / .png
    pilot_demand_sensitivity_{metric}.pdf   (individual diagnostics)

Key metric:
    effective_supported_commuters = number of on-time arrivals
    This is the primary operational answer: with a 112-seat pilot fleet,
    how many commuters can actually be served on time?

Usage:
    python3 experiments/scripts/plot_pilot_fleet_demand_sensitivity.py
    python3 experiments/scripts/plot_pilot_fleet_demand_sensitivity.py \\
        --results_root experiments/results/pilot_fleet_demand_sensitivity \\
        --output_dir  experiments/results/pilot_fleet_demand_sensitivity/plots \\
        --print_latex \\
        --service_rate_threshold 99 \\
        --on_time_threshold 95
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd

# ---------------------------------------------------------------------------
# Import shared publication style (same directory as this script)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from plot_pub_style import setup_pub_style  # noqa: E402

# ---------------------------------------------------------------------------
# Experiment constants
# ---------------------------------------------------------------------------

FLEET_ORDER = [
    "balanced_pilot",
    "vmt_oriented_pilot",
    "low_emission_pilot",
    "all_minibus_pilot",
]

FLEET_LABELS = {
    "balanced_pilot":     "Balanced pilot",
    "vmt_oriented_pilot": "VMT-oriented pilot",
    "low_emission_pilot": "Low-emission pilot",
    "all_minibus_pilot":  "All-minibus pilot",
}

DEMAND_ORDER  = ["x0.25", "x0.50", "x0.75", "x1.00"]
DEMAND_VALUES = {"x0.25": 0.25, "x0.50": 0.50, "x0.75": 0.75, "x1.00": 1.00}

TOTAL_SEATS   = 112
FULL_DEMAND   = 1465

DEMAND_APPROX = {
    "x0.25": 366,
    "x0.50": 733,
    "x0.75": 1099,
    "x1.00": 1465,
}

# ---------------------------------------------------------------------------
# Metric extraction helpers (tolerant to varied key names across simulator
# versions — mirrors the approach in plot_capacity_sensitivity_representative.py)
# ---------------------------------------------------------------------------

def find_value(
    data: dict[str, Any],
    candidates: list[str],
    default: float | None = None,
) -> float | None:
    for key in candidates:
        cur: Any = data
        ok = True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None:
            try:
                return float(cur)
            except (TypeError, ValueError):
                pass
    return default


def normalize_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def _valid(v: float | None) -> bool:
    """True iff v is a non-None, non-NaN number."""
    return v is not None and not math.isnan(v)


def extract_metrics(
    comparison_path: Path,
    actual_demand_count: int | None = None,
) -> dict[str, float | None]:
    with comparison_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    metrics_data: dict[str, Any] = {}
    metrics_path = comparison_path.with_name("metrics.json")
    if metrics_path.exists():
        with metrics_path.open("r", encoding="utf-8") as f:
            metrics_data = json.load(f)

    def find_in_both(candidates: list[str], default: float | None = None) -> float | None:
        if metrics_data:
            v = find_value(metrics_data, candidates)
            if v is not None:
                return v
        return find_value(data, candidates, default)

    served_pct = normalize_percent(find_value(data, [
        "service_rate_pct", "service_rate", "served_rate", "served_pct",
        "av.service_rate", "av.served_rate", "metrics.service_rate",
    ]))

    on_time_pct = normalize_percent(find_value(data, [
        "on_time_rate_pct", "on_time_rate",
        "av.on_time_rate", "metrics.on_time_rate",
    ]))

    eff_on_time_pct = normalize_percent(find_in_both([
        "effective_on_time_service_rate", "effective_on_time_rate",
        "effective_on_time_pct", "eff_on_time_rate", "eff_on_time_pct",
        "av.effective_on_time_rate", "av.effective_on_time_pct",
        "metrics.effective_on_time_rate",
    ]))
    if eff_on_time_pct is None and served_pct is not None and on_time_pct is not None:
        eff_on_time_pct = served_pct * on_time_pct / 100.0

    num_served = find_in_both([
        "num_served", "n_served", "served_count",
        "av.num_served", "metrics.num_served",
    ])

    num_on_time = find_in_both([
        "num_on_time", "n_on_time", "on_time_count", "on_time_arrivals",
        "av.num_on_time", "av.on_time_arrivals", "metrics.num_on_time",
    ])

    # Derive num_served if missing
    if not _valid(num_served) and actual_demand_count is not None and _valid(served_pct):
        num_served = actual_demand_count * served_pct / 100.0  # type: ignore[operator]

    # Derive effective_supported_commuters
    # Primary source: num_on_time (direct count of on-time arrivals).
    # Fallback 1: actual_demand_count * eff_on_time_pct / 100 (preserves partial-service context).
    # Fallback 2: estimate total demand from num_served / served_pct (legacy path).
    eff_supported: float | None = None
    if _valid(num_on_time):
        eff_supported = num_on_time
    elif _valid(eff_on_time_pct) and actual_demand_count is not None:
        eff_supported = actual_demand_count * eff_on_time_pct / 100.0  # type: ignore[operator]
    elif _valid(eff_on_time_pct) and _valid(num_served) and _valid(served_pct):
        total_demand_est = num_served / (served_pct / 100.0)  # type: ignore[operator]
        eff_supported = eff_on_time_pct / 100.0 * total_demand_est  # type: ignore[operator]

    late_arrivals = find_in_both([
        "late_deliveries", "late_count", "num_late",
        "late_arrivals", "av.late_count", "metrics.late_arrivals",
    ])
    # Derive late arrivals if not directly available
    if not _valid(late_arrivals) and _valid(num_served) and _valid(eff_supported):
        late_arrivals = num_served - eff_supported  # type: ignore[operator]

    # NOTE: VMT and CO2 reductions below are computed against the full-demand
    # baseline in the simulator.  When service is partial (demand fraction < 1.0)
    # the fleet operates fewer trips, so reported reductions over-state the
    # per-commuter impact.  Treat as diagnostic only; do not use as primary
    # comparison metrics in the demand-sensitivity figure.
    _vmt_raw = find_value(data, [
        "vmt_reduction", "vmt_reduction_pct", "vmt_reduction_percent",
        "comparison.vmt_reduction", "metrics.vmt_reduction",
    ])
    if _vmt_raw is None:
        _vmt_change = find_value(data, ["vmt_change_pct", "changes_percent.vmt"])
        _vmt_raw = -_vmt_change if _vmt_change is not None else None
    vmt_reduction_pct = normalize_percent(_vmt_raw)

    _co2_raw = find_value(data, [
        "co2_reduction", "co2_reduction_pct", "co2_reduction_percent",
        "comparison.co2_reduction", "metrics.co2_reduction",
    ])
    if _co2_raw is None:
        _co2_change = find_value(data, ["co2_change_pct", "changes_percent.co2"])
        _co2_raw = -_co2_change if _co2_change is not None else None
    co2_reduction_pct = normalize_percent(_co2_raw)

    avg_pax_per_trip = find_in_both([
        "avg_passengers_per_trip", "avg_pax_per_trip",
        "average_passengers_per_trip", "av.avg_pax_per_trip",
    ])

    avg_ivt_min = find_in_both([
        "avg_in_vehicle_time_min", "avg_ivt_min",
        "average_in_vehicle_time_min", "av.avg_in_vehicle_time_min",
    ])

    return {
        "served_pct":              served_pct,
        "eff_on_time_pct":         eff_on_time_pct,
        "eff_supported_commuters": eff_supported,
        "num_served":              num_served,
        "num_on_time":             num_on_time,
        "late_arrivals":           late_arrivals,
        # Diagnostic only — full-demand baseline reductions; misleading under partial service
        "vmt_reduction_pct":       vmt_reduction_pct,
        "co2_reduction_pct":       co2_reduction_pct,
        "avg_pax_per_trip":        avg_pax_per_trip,
        "avg_ivt_min":             avg_ivt_min,
    }


# ---------------------------------------------------------------------------
# Result collection
# ---------------------------------------------------------------------------

def collect_results(results_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    missing: list[str] = []

    for fleet in FLEET_ORDER:
        for demand in DEMAND_ORDER:
            demand_dir = results_root / fleet / demand
            if not demand_dir.exists():
                missing.append(f"{fleet}/{demand}")
                continue

            seed_dirs = sorted(demand_dir.glob("seed_*"))
            for seed_dir in seed_dirs:
                comparison_path = seed_dir / "comparison.json"
                if not comparison_path.exists():
                    print(f"[WARN] Missing comparison.json: {seed_dir}")
                    continue

                try:
                    seed = int(seed_dir.name.replace("seed_", ""))
                except ValueError:
                    seed = None

                metrics = extract_metrics(comparison_path, DEMAND_APPROX.get(demand))

                rows.append({
                    "fleet":             fleet,
                    "fleet_label":       FLEET_LABELS[fleet],
                    "demand_level":      demand,
                    "demand_fraction":   DEMAND_VALUES[demand],
                    "actual_demand_count": DEMAND_APPROX.get(demand),
                    "total_seats":       TOTAL_SEATS,
                    "seed":              seed,
                    **metrics,
                })

    if missing:
        print(f"[WARN] Missing fleet/demand directories: {missing}")

    if not rows:
        raise RuntimeError(f"No completed results found under {results_root}")

    return pd.DataFrame(rows)


def check_seed_counts(df: pd.DataFrame) -> None:
    counts = (
        df.groupby(["fleet", "demand_level"])["seed"]
        .count()
        .reset_index(name="seed_count")
    )
    max_seeds = counts["seed_count"].max()
    unequal = counts[counts["seed_count"] != max_seeds]
    if unequal.empty:
        print(f"[OK] Seed counts consistent: {max_seeds} seeds per cell")
    else:
        print(f"[WARN] Unequal seed counts across fleet-demand cells:")
        print(unequal.to_string(index=False))
        print(f"  Max seeds seen: {max_seeds}. Cells with fewer seeds listed above.")
        print(f"  Plots will still be generated from available seeds.")


# ---------------------------------------------------------------------------
# Summary aggregation
# ---------------------------------------------------------------------------

METRIC_COLS = [
    "served_pct",
    "eff_on_time_pct",
    "eff_supported_commuters",
    "num_served",
    "num_on_time",
    "late_arrivals",
    # Diagnostic — full-demand baseline reductions; not primary under partial service
    "vmt_reduction_pct",
    "co2_reduction_pct",
    "avg_pax_per_trip",
    "avg_ivt_min",
]


def mean_std_summary(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["fleet", "fleet_label", "demand_level", "demand_fraction",
                  "actual_demand_count", "total_seats"]

    available_metrics = [c for c in METRIC_COLS if c in df.columns]
    grouped = df.groupby(group_cols, as_index=False)

    summary = grouped[available_metrics].agg(["mean", "std", "count"])
    summary.columns = [
        "_".join([c for c in col if c])
        for col in summary.columns.to_flat_index()
    ]
    summary = summary.reset_index()

    for metric in available_metrics:
        count_col = f"{metric}_count"
        std_col   = f"{metric}_std"
        sem_col   = f"{metric}_sem"
        if count_col in summary.columns:
            summary[sem_col] = summary[std_col] / summary[count_col].apply(
                lambda n: math.sqrt(n) if n and n > 0 else float("nan")
            )

    return summary


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------

def configure_matplotlib() -> None:
    setup_pub_style()


def _fleet_color(i: int) -> str:
    return f"C{i}"


def plot_metric(
    summary: pd.DataFrame,
    output_dir: Path,
    metric: str,
    ylabel: str,
    filename: str,
) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.2))

    for i, fleet in enumerate(FLEET_ORDER):
        sub = summary[summary["fleet"] == fleet].sort_values("demand_fraction")
        if sub.empty:
            continue

        mean_col = f"{metric}_mean"
        sem_col  = f"{metric}_sem"
        if mean_col not in sub.columns:
            continue

        x    = sub["demand_fraction"].values
        y    = sub[mean_col].values
        yerr = sub[sem_col].values if sem_col in sub.columns else None

        ax.errorbar(
            x, y, yerr=yerr,
            marker="o", capsize=3,
            color=_fleet_color(i),
            label=FLEET_LABELS[fleet],
        )

    ax.set_xlabel("Demand fraction (relative to 1,465 commuters)")
    ax.set_ylabel(ylabel)
    ax.set_xticks([0.25, 0.50, 0.75, 1.00])
    ax.set_xticklabels(["0.25", "0.50", "0.75", "1.00"])
    ax.grid(True, linestyle=":", linewidth=0.7)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()

    pdf_path = output_dir / filename
    png_path = output_dir / filename.replace(".pdf", ".png")
    fig.savefig(pdf_path, bbox_inches="tight", dpi=300)
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)


def plot_combined_figure(summary: pd.DataFrame, output_dir: Path) -> None:
    # Main 2×2 figure uses service-quality metrics only.
    # VMT and CO2 reductions are intentionally excluded: they are computed
    # against the full-demand baseline and over-state per-commuter impact when
    # service is partial (demand fraction < 1.0).  See diagnostic plots instead.
    panels = [
        ("served_pct",              "Service rate (%)",                "(a)"),
        ("eff_on_time_pct",         "Effective on-time service (%)",   "(b)"),
        ("eff_supported_commuters", "Effective supported commuters",   "(c)"),
        ("late_arrivals",           "Late arrivals",                   "(d)"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0), sharex=True)
    axes_flat = axes.flat

    legend_handles = [
        Line2D([0], [0], color=_fleet_color(i), marker="o",
               linestyle="-", linewidth=1.8)
        for i in range(len(FLEET_ORDER))
    ]
    legend_labels = [FLEET_LABELS[f] for f in FLEET_ORDER]

    for ax, (metric, ylabel, panel_label) in zip(axes_flat, panels):
        mean_col = f"{metric}_mean"
        sem_col  = f"{metric}_sem"

        for i, fleet in enumerate(FLEET_ORDER):
            sub = summary[summary["fleet"] == fleet].sort_values("demand_fraction")
            if sub.empty or mean_col not in sub.columns:
                continue

            x    = sub["demand_fraction"].values
            y    = sub[mean_col].values
            yerr = sub[sem_col].values if sem_col in sub.columns else None

            ax.errorbar(
                x, y, yerr=yerr,
                marker="o", capsize=3,
                color=_fleet_color(i),
            )

        ax.set_ylabel(ylabel)
        ax.set_xticks([0.25, 0.50, 0.75, 1.00])
        ax.set_xticklabels(["0.25", "0.50", "0.75", "1.00"])
        ax.grid(True, linestyle=":", linewidth=0.7, alpha=0.30)
        ax.text(
            0.02, 0.96, panel_label,
            transform=ax.transAxes,
            ha="left", va="top", fontweight="bold",
        )

    xlabel = "Demand fraction (relative to 1,465 commuters)"
    for ax in axes[1, :]:
        ax.set_xlabel(xlabel)
    for ax in axes[0, :]:
        ax.set_xlabel(xlabel)
        ax.tick_params(axis="x", labelbottom=True)

    fig.subplots_adjust(
        left=0.08, right=0.98, top=0.93, bottom=0.18,
        wspace=0.28, hspace=0.36,
    )
    fig.legend(
        legend_handles, legend_labels,
        loc="lower center", ncol=4, frameon=False,
        bbox_to_anchor=(0.5, 0.01),
        handlelength=2.0, columnspacing=1.4,
    )

    pdf_path = output_dir / "pilot_demand_sensitivity_combined.pdf"
    png_path = output_dir / "pilot_demand_sensitivity_combined.png"
    fig.savefig(pdf_path, bbox_inches="tight", dpi=300)
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"Wrote combined figure: {pdf_path}")


# ---------------------------------------------------------------------------
# Threshold summary
# ---------------------------------------------------------------------------

def print_threshold_summary(
    summary: pd.DataFrame,
    service_rate_threshold: float,
    on_time_threshold: float,
) -> None:
    print()
    print("─" * 64)
    print("Threshold summary")
    print(f"  Service rate threshold      : {service_rate_threshold}%")
    print(f"  Effective on-time threshold : {on_time_threshold}%")
    print("─" * 64)

    for fleet in FLEET_ORDER:
        label = FLEET_LABELS[fleet]
        sub   = summary[summary["fleet"] == fleet].sort_values("demand_fraction")

        sr_max  = None
        eot_max = None

        for _, row in sub.iterrows():
            sr  = row.get("served_pct_mean")
            eot = row.get("eff_on_time_pct_mean")
            dlvl = row["demand_level"]

            if sr is not None and not math.isnan(sr) and sr >= service_rate_threshold:
                sr_max = dlvl
            if eot is not None and not math.isnan(eot) and eot >= on_time_threshold:
                eot_max = dlvl

        sr_str  = sr_max  if sr_max  is not None else "none"
        eot_str = eot_max if eot_max is not None else "none"
        print(f"  {label:<24}  service≥{service_rate_threshold}%: {sr_str:<6}  "
              f"eff-on-time≥{on_time_threshold}%: {eot_str}")

    print("─" * 64)


# ---------------------------------------------------------------------------
# LaTeX table
# ---------------------------------------------------------------------------

def print_latex_table(summary: pd.DataFrame) -> None:
    cols = [
        "fleet_label", "demand_level", "actual_demand_count", "total_seats",
        "served_pct_mean", "eff_on_time_pct_mean",
        "eff_supported_commuters_mean",
        "late_arrivals_mean",
        # Diagnostic: full-demand baseline reductions; misleading under partial service
        "vmt_reduction_pct_mean", "co2_reduction_pct_mean",
    ]
    available = [c for c in cols if c in summary.columns]
    table = summary[available].copy()
    table = table.sort_values(["fleet_label", "demand_fraction"]
                              if "demand_fraction" in table.columns
                              else ["fleet_label", "demand_level"])

    rename = {
        "fleet_label":                   "Fleet",
        "demand_level":                  "Demand",
        "actual_demand_count":           "Commuters",
        "total_seats":                   "Seats",
        "served_pct_mean":               "Served (\\%)",
        "eff_on_time_pct_mean":          "Eff. on-time (\\%)",
        "eff_supported_commuters_mean":  "Eff. supported",
        "late_arrivals_mean":            "Late",
        "vmt_reduction_pct_mean":        "VMT red. (\\%)",
        "co2_reduction_pct_mean":        "\\COtwo{} red. (\\%)",
    }
    table = table.rename(columns={k: v for k, v in rename.items() if k in table.columns})

    float_cols = [
        "Served (\\%)", "Eff. on-time (\\%)", "Eff. supported",
        "Late", "VMT red. (\\%)", "\\COtwo{} red. (\\%)",
    ]
    for col in float_cols:
        if col in table.columns:
            table[col] = table[col].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")

    print()
    print("LaTeX table draft:")
    print()
    print(table.to_latex(index=False, escape=False))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate and plot pilot fleet demand sensitivity results."
    )
    parser.add_argument(
        "--results_root",
        type=Path,
        default=Path("experiments/results/pilot_fleet_demand_sensitivity"),
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=Path("experiments/results/pilot_fleet_demand_sensitivity/plots"),
    )
    parser.add_argument("--print_latex", action="store_true")
    parser.add_argument("--service_rate_threshold", type=float, default=99.0)
    parser.add_argument("--on_time_threshold", type=float, default=95.0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_matplotlib()

    print(f"Reading results from: {args.results_root}")
    df = collect_results(args.results_root)

    check_seed_counts(df)

    summary = mean_std_summary(df)

    runs_csv    = args.output_dir / "pilot_demand_sensitivity_runs.csv"
    summary_csv = args.output_dir / "pilot_demand_sensitivity_summary.csv"
    df.to_csv(runs_csv, index=False)
    summary.to_csv(summary_csv, index=False)
    print(f"Wrote runs CSV    : {runs_csv}")
    print(f"Wrote summary CSV : {summary_csv}")

    # Reload from CSV to use the authoritative artifact as plot input
    summary = pd.read_csv(summary_csv)

    # --- Combined 2×2 figure ------------------------------------------------
    plot_combined_figure(summary, args.output_dir)

    # --- Individual diagnostic plots ----------------------------------------
    # VMT and CO2 are retained as diagnostics but excluded from the combined
    # figure because they are full-demand baseline reductions and over-state
    # per-commuter impact when the experiment runs at partial demand.
    diagnostics = [
        ("served_pct",              "Service rate (%)",
         "pilot_demand_sensitivity_service.pdf"),
        ("eff_on_time_pct",         "Effective on-time service (%)",
         "pilot_demand_sensitivity_effective_on_time.pdf"),
        ("eff_supported_commuters", "Effective supported commuters",
         "pilot_demand_sensitivity_eff_supported.pdf"),
        ("late_arrivals",           "Late arrivals",
         "pilot_demand_sensitivity_late.pdf"),
        ("vmt_reduction_pct",       "VMT reduction (%) [diagnostic: full-demand baseline]",
         "pilot_demand_sensitivity_vmt.pdf"),
        ("co2_reduction_pct",       r"CO$_2$ reduction (%) [diagnostic: full-demand baseline]",
         "pilot_demand_sensitivity_co2.pdf"),
    ]

    for metric, ylabel, filename in diagnostics:
        if f"{metric}_mean" not in summary.columns:
            print(f"[SKIP] {metric} not available in summary")
            continue
        plot_metric(summary, args.output_dir, metric, ylabel, filename)
        print(f"Wrote: {args.output_dir / filename}")

    # --- Threshold summary --------------------------------------------------
    print_threshold_summary(
        summary,
        service_rate_threshold=args.service_rate_threshold,
        on_time_threshold=args.on_time_threshold,
    )

    if args.print_latex:
        print_latex_table(summary)


if __name__ == "__main__":
    main()
