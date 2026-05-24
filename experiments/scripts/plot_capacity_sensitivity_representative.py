#!/usr/bin/env python3
"""
Aggregate and plot representative-fleet capacity sensitivity results.

Expected result layout from the runner:

experiments/results/capacity_sensitivity_representative/
  balanced/
    x0.90/
      seed_1/
        comparison.json
      seed_2/
        comparison.json
      ...
  vmt_oriented/
    x1.00/
      seed_1/
        comparison.json
  low_emission/
    x1.25/
      seed_15/
        comparison.json

The script is intentionally tolerant to different comparison.json key names.
If your simulator uses different metric names, update extract_metrics().
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from plot_pub_style import setup_pub_style as apply_pub_style
from matplotlib.lines import Line2D
import pandas as pd


FLEET_ORDER = ["balanced", "vmt_oriented", "low_emission"]
FLEET_LABELS = {
    "balanced": "Balanced",
    "vmt_oriented": "VMT-oriented",
    "low_emission": "Low-emission",
}

SCALE_ORDER = ["x0.90", "x1.00", "x1.10", "x1.25"]

SEATS = {
    ("balanced", "x0.90"): 200,
    ("balanced", "x1.00"): 224,
    ("balanced", "x1.10"): 247,
    ("balanced", "x1.25"): 280,

    ("vmt_oriented", "x0.90"): 204,
    ("vmt_oriented", "x1.00"): 224,
    ("vmt_oriented", "x1.10"): 244,
    ("vmt_oriented", "x1.25"): 284,

    ("low_emission", "x0.90"): 198,
    ("low_emission", "x1.00"): 224,
    ("low_emission", "x1.10"): 250,
    ("low_emission", "x1.25"): 282,
}


def find_value(data: dict[str, Any], candidates: list[str], default: float | None = None) -> float | None:
    """
    Search nested dictionaries using dot-separated candidate keys.
    Returns the first numeric value found.
    """
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
    """
    Some scripts store percentages as 0.975, others as 97.5.
    Convert fractions to percentages.
    """
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def extract_metrics(path: Path) -> dict[str, float | None]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    metrics_path = path.with_name("metrics.json")
    metrics_data: dict[str, Any] = {}
    if metrics_path.exists():
        with metrics_path.open("r", encoding="utf-8") as f:
            metrics_data = json.load(f)

    def find_in_outputs(candidates: list[str], default: float | None = None) -> float | None:
        if metrics_data:
            value = find_value(metrics_data, candidates)
            if value is not None:
                return value
        return find_value(data, candidates, default)

    served_pct = normalize_percent(find_value(data, [
        "service_rate_pct",
        "service_rate",
        "served_rate",
        "served_pct",
        "av.service_rate",
        "av.served_rate",
        "av.served_pct",
        "metrics.service_rate",
        "metrics.served_rate",
        "metrics.served_pct",
    ]))

    on_time_pct = normalize_percent(find_value(data, [
        "on_time_rate_pct",
        "on_time_rate",
        "av.on_time_rate",
        "metrics.on_time_rate",
    ]))

    eff_on_time_pct = normalize_percent(find_in_outputs([
        "effective_on_time_service_rate",
        "effective_on_time_rate",
        "effective_on_time_pct",
        "eff_on_time_rate",
        "eff_on_time_pct",
        "av.effective_on_time_rate",
        "av.effective_on_time_pct",
        "metrics.effective_on_time_rate",
        "metrics.effective_on_time_pct",
    ]))
    if eff_on_time_pct is None and served_pct is not None and on_time_pct is not None:
        # comparison.json stores on_time_rate_pct over served riders; convert it
        # to the stricter total-demand effective on-time service rate.
        eff_on_time_pct = served_pct * on_time_pct / 100.0

    _vmt_raw = find_value(data, [
        "vmt_reduction",
        "vmt_reduction_pct",
        "vmt_reduction_percent",
        "comparison.vmt_reduction",
        "comparison.vmt_reduction_pct",
        "metrics.vmt_reduction",
        "metrics.vmt_reduction_pct",
    ])
    if _vmt_raw is None:
        # vmt_change_pct is stored as a negative number (e.g. -35.2 = 35% reduction)
        _vmt_change = find_value(data, ["vmt_change_pct", "changes_percent.vmt"])
        _vmt_raw = -_vmt_change if _vmt_change is not None else None
    vmt_reduction_pct = normalize_percent(_vmt_raw)

    _co2_raw = find_value(data, [
        "co2_reduction",
        "co2_reduction_pct",
        "co2_reduction_percent",
        "comparison.co2_reduction",
        "comparison.co2_reduction_pct",
        "metrics.co2_reduction",
        "metrics.co2_reduction_pct",
    ])
    if _co2_raw is None:
        _co2_change = find_value(data, ["co2_change_pct", "changes_percent.co2"])
        _co2_raw = -_co2_change if _co2_change is not None else None
    co2_reduction_pct = normalize_percent(_co2_raw)

    late_count = find_value(data, [
        "late_deliveries",
        "late_count",
        "num_late",
        "late_arrivals",
        "av.late_count",
        "metrics.late_count",
        "metrics.late_arrivals",
    ])

    avg_pax_per_trip = find_value(data, [
        "avg_passengers_per_trip",
        "avg_pax_per_trip",
        "average_passengers_per_trip",
        "pax_per_trip",
        "av.avg_pax_per_trip",
        "metrics.avg_pax_per_trip",
    ])

    avg_ivt_min = find_value(data, [
        "avg_in_vehicle_time_min",
        "avg_ivt_min",
        "average_in_vehicle_time_min",
        "av.avg_in_vehicle_time_min",
        "metrics.avg_in_vehicle_time_min",
    ])

    return {
        "served_pct": served_pct,
        "eff_on_time_pct": eff_on_time_pct,
        "vmt_reduction_pct": vmt_reduction_pct,
        "co2_reduction_pct": co2_reduction_pct,
        "late_count": late_count,
        "avg_pax_per_trip": avg_pax_per_trip,
        "avg_ivt_min": avg_ivt_min,
    }


def collect_results(results_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for fleet in FLEET_ORDER:
        for scale in SCALE_ORDER:
            scale_dir = results_root / fleet / scale
            if not scale_dir.exists():
                print(f"[WARN] Missing directory: {scale_dir}")
                continue

            for seed_dir in sorted(scale_dir.glob("seed_*")):
                comparison_path = seed_dir / "comparison.json"
                if not comparison_path.exists():
                    print(f"[WARN] Missing comparison.json: {seed_dir}")
                    continue

                seed_str = seed_dir.name.replace("seed_", "")
                try:
                    seed = int(seed_str)
                except ValueError:
                    seed = None

                metrics = extract_metrics(comparison_path)

                row = {
                    "fleet": fleet,
                    "fleet_label": FLEET_LABELS[fleet],
                    "scale": scale,
                    "scale_value": float(scale.replace("x", "")),
                    "total_seats": SEATS.get((fleet, scale)),
                    "seed": seed,
                    **metrics,
                }
                rows.append(row)

    if not rows:
        raise RuntimeError(f"No results found under {results_root}")

    return pd.DataFrame(rows)


def mean_std_summary(df: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [
        "served_pct",
        "eff_on_time_pct",
        "vmt_reduction_pct",
        "co2_reduction_pct",
        "late_count",
        "avg_pax_per_trip",
        "avg_ivt_min",
    ]

    grouped = df.groupby(
        ["fleet", "fleet_label", "scale", "scale_value", "total_seats"],
        as_index=False,
    )

    summary = grouped[metric_cols].agg(["mean", "std", "count"])
    summary.columns = [
        "_".join([c for c in col if c])
        for col in summary.columns.to_flat_index()
    ]
    summary = summary.reset_index()

    # More convenient aliases.
    for metric in metric_cols:
        summary[f"{metric}_sem"] = summary[f"{metric}_std"] / summary[f"{metric}_count"].apply(
            lambda n: math.sqrt(n) if n and n > 0 else float("nan")
        )

    return summary


def configure_matplotlib() -> None:
    apply_pub_style()
    return

    plt.rcParams.update({
        "font.family": "Times New Roman",
        "font.size": 10,
        "axes.labelsize": 10,
        "axes.titlesize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "lines.linewidth": 1.8,
        "lines.markersize": 5,
        "mathtext.fontset": "stix",
    })


def plot_metric(
    summary: pd.DataFrame,
    output_dir: Path,
    metric: str,
    ylabel: str,
    filename: str,
    add_reference_line: bool = True,
) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.2))

    for fleet in FLEET_ORDER:
        sub = summary[summary["fleet"] == fleet].sort_values("scale_value")

        x = sub["scale_value"]
        y = sub[f"{metric}_mean"]
        yerr = sub[f"{metric}_sem"]

        ax.errorbar(
            x,
            y,
            yerr=yerr,
            marker="o",
            capsize=3,
            label=FLEET_LABELS[fleet],
        )

    if add_reference_line:
        ax.axvline(1.0, linestyle="--", linewidth=1.0)

    ax.set_xlabel("Capacity scale relative to 224-seat reference")
    ax.set_ylabel(ylabel)
    ax.set_xticks([0.90, 1.00, 1.10, 1.25])
    ax.set_xticklabels(["0.90", "1.00", "1.10", "1.25"])
    ax.grid(True, linestyle=":", linewidth=0.7)
    ax.legend(frameon=False)
    fig.tight_layout()

    fig.savefig(output_dir / filename, bbox_inches="tight")
    fig.savefig(output_dir / filename.replace(".pdf", ".png"), bbox_inches="tight")
    plt.close(fig)


def plot_combined_figure(summary: pd.DataFrame, output_dir: Path) -> None:
    metrics = [
        ("served_pct", "Service rate (%)", "(a)", "service"),
        ("eff_on_time_pct", "Effective on-time service (%)", "(b)", "effective_on_time"),
        ("vmt_reduction_pct", "VMT reduction (%)", "(c)", "vmt"),
        ("co2_reduction_pct", r"CO$_2$ reduction (%)", "(d)", "co2"),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(7.0, 5.0), sharex=True)
    axes_flat = axes.flat

    legend_handles = [
        Line2D([0], [0], color=f"C{i}", marker="o", linestyle="-", linewidth=1.8)
        for i in range(len(FLEET_ORDER))
    ]
    legend_labels = [FLEET_LABELS[fleet] for fleet in FLEET_ORDER]

    for ax, (metric, ylabel, panel_label, _) in zip(axes_flat, metrics):
        for fleet in FLEET_ORDER:
            sub = summary[summary["fleet"] == fleet].sort_values("scale_value")

            x = sub["scale_value"]
            y = sub[f"{metric}_mean"]
            yerr = sub[f"{metric}_sem"]

            ax.errorbar(
                x,
                y,
                yerr=yerr,
                marker="o",
                capsize=3,
            )

        ax.axvline(1.0, linestyle="--", linewidth=1.0)
        ax.set_ylabel(ylabel)
        ax.set_xticks([0.90, 1.00, 1.10, 1.25])
        ax.set_xticklabels(["0.90", "1.00", "1.10", "1.25"])
        ax.grid(True, linestyle=":", linewidth=0.7)
        ax.text(
            0.02,
            0.96,
            panel_label,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontweight="bold",
        )

    for ax in axes[0, :]:
        ax.set_xlabel("Capacity scale relative to 224-seat reference", labelpad=8)
        ax.tick_params(axis="x", labelbottom=True)

    for ax in axes[1, :]:
        ax.set_xlabel("Capacity scale relative to 224-seat reference")

    fig.subplots_adjust(left=0.08, right=0.98, top=0.93, bottom=0.18, wspace=0.28, hspace=0.36)
    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        ncol=3,
        frameon=False,
        bbox_to_anchor=(0.5, 0.02),
        handlelength=2.4,
        columnspacing=1.8,
    )

    fig.savefig(output_dir / "capacity_sensitivity_combined.pdf", bbox_inches="tight")
    fig.savefig(output_dir / "capacity_sensitivity_combined.png", bbox_inches="tight")
    plt.close(fig)


def print_latex_table(summary: pd.DataFrame) -> None:
    cols = [
        "fleet_label",
        "scale",
        "total_seats",
        "served_pct_mean",
        "eff_on_time_pct_mean",
        "late_count_mean",
        "vmt_reduction_pct_mean",
        "co2_reduction_pct_mean",
        "avg_pax_per_trip_mean",
    ]

    table = summary[cols].copy()
    table = table.sort_values(["fleet_label", "scale"])

    rename = {
        "fleet_label": "Fleet",
        "scale": "Scale",
        "total_seats": "Seats",
        "served_pct_mean": "Served (\\%)",
        "eff_on_time_pct_mean": "Eff. on-time (\\%)",
        "late_count_mean": "Late",
        "vmt_reduction_pct_mean": "VMT red. (\\%)",
        "co2_reduction_pct_mean": "\\COtwo{} red. (\\%)",
        "avg_pax_per_trip_mean": "Pax/trip",
    }

    table = table.rename(columns=rename)

    float_cols = [
        "Served (\\%)",
        "Eff. on-time (\\%)",
        "Late",
        "VMT red. (\\%)",
        "\\COtwo{} red. (\\%)",
        "Pax/trip",
    ]

    for col in float_cols:
        table[col] = table[col].map(lambda x: f"{x:.2f}" if pd.notna(x) else "")

    print()
    print("LaTeX table draft:")
    print()
    print(table.to_latex(index=False, escape=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results_root",
        type=Path,
        default=Path("experiments/results/capacity_sensitivity_representative"),
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=Path("experiments/results/capacity_sensitivity_representative/plots"),
    )
    parser.add_argument(
        "--print_latex",
        action="store_true",
    )

    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    configure_matplotlib()

    df = collect_results(args.results_root)
    summary = mean_std_summary(df)

    raw_csv = args.output_dir / "capacity_sensitivity_runs.csv"
    summary_csv = args.output_dir / "capacity_sensitivity_summary.csv"

    df.to_csv(raw_csv, index=False)
    summary.to_csv(summary_csv, index=False)

    # Reload the summary CSV so the combined figure explicitly uses the
    # experiment-produced summary artifact as its input.
    summary = pd.read_csv(summary_csv)

    plot_metric(
        summary,
        args.output_dir,
        metric="served_pct",
        ylabel="Service rate (%)",
        filename="capacity_sensitivity_service.pdf",
    )

    plot_metric(
        summary,
        args.output_dir,
        metric="eff_on_time_pct",
        ylabel="Effective on-time service (%)",
        filename="capacity_sensitivity_effective_on_time.pdf",
    )

    plot_metric(
        summary,
        args.output_dir,
        metric="vmt_reduction_pct",
        ylabel="VMT reduction (%)",
        filename="capacity_sensitivity_vmt.pdf",
    )

    plot_metric(
        summary,
        args.output_dir,
        metric="co2_reduction_pct",
        ylabel="CO$_2$ reduction (%)",
        filename="capacity_sensitivity_co2.pdf",
    )

    plot_metric(
        summary,
        args.output_dir,
        metric="late_count",
        ylabel="Late arrivals",
        filename="capacity_sensitivity_late.pdf",
    )

    plot_metric(
        summary,
        args.output_dir,
        metric="avg_pax_per_trip",
        ylabel="Average passengers per trip",
        filename="capacity_sensitivity_pax_per_trip.pdf",
    )

    plot_combined_figure(summary, args.output_dir)

    print(f"Wrote raw run CSV:     {raw_csv}")
    print(f"Wrote summary CSV:     {summary_csv}")
    print(f"Wrote plots to:        {args.output_dir}")

    if args.print_latex:
        print_latex_table(summary)


if __name__ == "__main__":
    main()
