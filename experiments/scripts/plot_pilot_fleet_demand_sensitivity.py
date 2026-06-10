#!/usr/bin/env python3
"""
Aggregate and plot pilot-fleet demand sensitivity results.

This script reads existing result files only. It does not rerun simulations.

Expected layout:

experiments/results/pilot_fleet_demand_sensitivity/
  all_car_pilot/
    x0.25/
      seed_1/
        metrics.json
        comparison.json
        config.json
      ...
  balanced_pilot/
  vmt_oriented_pilot/
  low_emission_pilot/

Paper-facing framing follows docs/PROJECT_SPEC.md:

- service_rate is the primary service metric;
- supported_commuters are commuters served on time by the AV fleet after pruning;
- fallback_private_cars are commuters not served on time by the AV fleet;
- VMT/CO2 reductions are retained as diagnostics only for this partial-demand
  pilot experiment unless their baseline can be confirmed as demand-matched.

Outputs:

  CSV:
    pilot_demand_sensitivity_runs.csv
    pilot_demand_sensitivity_summary.csv

  Main paper-facing figure:
    pilot_demand_sensitivity_service_fallback.pdf/.png

  Individual diagnostic plots where available:
    pilot_demand_sensitivity_avg_passengers_per_trip.pdf/.png
    pilot_demand_sensitivity_avg_in_vehicle_time.pdf/.png
    pilot_demand_sensitivity_system_vmt_reduction.pdf/.png
    pilot_demand_sensitivity_system_co2_reduction.pdf/.png
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import pandas as pd


_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from plot_pub_style import setup_pub_style  # noqa: E402


FLEET_ORDER = [
    "all_car_pilot",
    "balanced_pilot",
    "vmt_oriented_pilot",
    "low_emission_pilot",
]

FLEET_LABELS = {
    "all_car_pilot": "All-car pilot",
    "balanced_pilot": "Balanced pilot",
    "vmt_oriented_pilot": "VMT-oriented pilot",
    "low_emission_pilot": "Low-emission pilot",
}

FLEET_MARKERS = {
    "all_car_pilot": "o",
    "balanced_pilot": "s",
    "vmt_oriented_pilot": "^",
    "low_emission_pilot": "D",
}

FLEET_COLORS = {
    "all_car_pilot": "#0072B2",
    "balanced_pilot": "#E69F00",
    "vmt_oriented_pilot": "#56B4E9",
    "low_emission_pilot": "#CC79A7",
}

DEMAND_ORDER = ["x0.25", "x0.50", "x0.75", "x1.00"]
DEMAND_FRACTIONS = {"x0.25": 0.25, "x0.50": 0.50, "x0.75": 0.75, "x1.00": 1.00}

FULL_DEMAND = 1465
TOTAL_SEATS = 112
DEMAND_COUNTS = {
    "x0.25": 366,
    "x0.50": 733,
    "x0.75": 1099,
    "x1.00": 1465,
}

UNCERTAINTY_LABEL = "SEM"

SUMMARY_METRICS = [
    "service_rate",
    "supported_commuters",
    "fallback_private_cars",
    "avg_passengers_per_trip",
    "avg_in_vehicle_time_min",
    "system_vmt_reduction_pct",
    "system_co2_reduction_pct",
    "total_seats",
]


def configure_matplotlib() -> None:
    setup_pub_style()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_value(data: dict[str, Any], candidates: list[str]) -> tuple[float | None, str | None]:
    for key in candidates:
        cur: Any = data
        ok = True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur is not None and not isinstance(cur, (dict, list, tuple)):
            try:
                value = float(cur)
            except (TypeError, ValueError):
                continue
            if not math.isnan(value):
                return value, key
    return None, None


def normalize_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1.0 <= value <= 1.0:
        return value * 100.0
    return value


def first_from_sources(
    metrics_data: dict[str, Any],
    comparison_data: dict[str, Any],
    candidates: list[str],
) -> tuple[float | None, str]:
    value, key = find_value(metrics_data, candidates)
    if value is not None:
        return value, f"metrics.json:{key}"

    value, key = find_value(comparison_data, candidates)
    if value is not None:
        return value, f"comparison.json:{key}"

    return None, "missing"


def display_source(source: str) -> str:
    """Avoid exposing retired paper terminology in console summaries."""
    if source == "missing":
        return source
    if any(token in source for token in ["effective_on_time", "eff_on_time", "effective_supported"]):
        prefix = source.split(":", 1)[0]
        return f"{prefix}:legacy on-time support field"
    return source


def source_summary(source_counts: Counter) -> str:
    if not source_counts:
        return "missing"
    return ", ".join(
        f"{display_source(source)} ({count})" for source, count in source_counts.most_common()
    )


def system_reduction_from_sources(
    metrics_data: dict[str, Any],
    comparison_data: dict[str, Any],
    reduction_candidates: list[str],
    change_candidates: list[str],
) -> tuple[float | None, str]:
    value, source = first_from_sources(metrics_data, comparison_data, reduction_candidates)
    if value is not None:
        return normalize_percent(value), source

    change, source = first_from_sources(metrics_data, comparison_data, change_candidates)
    if change is not None:
        return normalize_percent(-change), f"{source} (negated)"

    return None, "missing"


def fleet_metadata_from_config(config: dict[str, Any]) -> dict[str, float | None]:
    capacity_meta = config.get("capacity_metadata", {})
    fleet = config.get("fleet", {})
    vehicle_types = fleet.get("vehicle_types", [])

    total_seats = capacity_meta.get("total_fleet_seats")
    if total_seats is None and isinstance(vehicle_types, list):
        total_seats = 0.0
        found_vehicle = False
        for vehicle_type in vehicle_types:
            try:
                total_seats += float(vehicle_type["fleet_size"]) * float(vehicle_type["capacity"])
                found_vehicle = True
            except (KeyError, TypeError, ValueError):
                pass
        if not found_vehicle:
            total_seats = None

    return {"total_seats": float(total_seats) if total_seats is not None else None}


def load_run_metadata(results_root: Path, fleet: str, demand_scale: str, seed_dir: Path) -> dict[str, float | None]:
    config_paths = [
        results_root / "configs" / f"{fleet}_{demand_scale}.json",
        seed_dir / "config.json",
    ]
    for config_path in config_paths:
        config = read_json(config_path)
        if config:
            return fleet_metadata_from_config(config)
    return {"total_seats": float(TOTAL_SEATS)}


def extract_metrics(
    run_dir: Path,
    actual_demand_count: int,
) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics_data = read_json(run_dir / "metrics.json")
    comparison_data = read_json(run_dir / "comparison.json")
    sources: dict[str, str] = {}

    supported_commuters, sources["supported_commuters"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "served_commuters",
            "metrics.served_commuters",
            "num_on_time",
            "on_time_count",
            "n_on_time",
            "on_time_arrivals",
            "av.num_on_time",
            "av.on_time_count",
            "metrics.num_on_time",
            "effective_supported_commuters",
        ],
    )

    fallback_private_cars, sources["fallback_private_cars"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "fallback_private_cars",
            "metrics.fallback_private_cars",
            "fallback_private_car_count",
        ],
    )
    if fallback_private_cars is None and supported_commuters is not None:
        fallback_private_cars = actual_demand_count - supported_commuters
        sources["fallback_private_cars"] = "derived from demand count - supported commuters"

    service_rate, sources["service_rate"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "service_rate",
            "service_rate_pct",
            "metrics.service_rate",
            "metrics.service_rate_pct",
            "served_rate",
            "served_pct",
            "av.service_rate",
        ],
    )
    service_rate = normalize_percent(service_rate)
    if service_rate is None and supported_commuters is not None:
        service_rate = 100.0 * supported_commuters / actual_demand_count
        sources["service_rate"] = "derived from supported commuters / demand count"

    if supported_commuters is None and service_rate is not None:
        supported_commuters = actual_demand_count * service_rate / 100.0
        sources["supported_commuters"] = "derived from service rate * demand count"

    if fallback_private_cars is None and supported_commuters is not None:
        fallback_private_cars = actual_demand_count - supported_commuters
        sources["fallback_private_cars"] = "derived from demand count - supported commuters"

    avg_passengers_per_trip, sources["avg_passengers_per_trip"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "avg_passengers_per_trip",
            "avg_pax_per_trip",
            "average_passengers_per_trip",
            "pax_per_trip",
            "av.avg_passengers_per_trip",
            "av.avg_pax_per_trip",
        ],
    )

    avg_in_vehicle_time_min, sources["avg_in_vehicle_time_min"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "avg_in_vehicle_time_min",
            "avg_ivt_min",
            "average_in_vehicle_time_min",
            "av.avg_in_vehicle_time_min",
        ],
    )

    system_vmt_reduction_pct, sources["system_vmt_reduction_pct"] = system_reduction_from_sources(
        metrics_data,
        comparison_data,
        [
            "system_vmt_reduction_pct",
            "system_vmt_reduction",
            "metrics.system_vmt_reduction_pct",
            "vmt_reduction_pct",
            "vmt_reduction",
        ],
        [
            "system_vmt_change_pct",
            "changes_percent.system_vmt",
            "vmt_change_pct",
            "changes_percent.vmt",
        ],
    )

    system_co2_reduction_pct, sources["system_co2_reduction_pct"] = system_reduction_from_sources(
        metrics_data,
        comparison_data,
        [
            "system_co2_reduction_pct",
            "system_co2_reduction",
            "metrics.system_co2_reduction_pct",
            "co2_reduction_pct",
            "co2_reduction",
        ],
        [
            "system_co2_change_pct",
            "changes_percent.system_co2",
            "co2_change_pct",
            "changes_percent.co2",
        ],
    )

    return (
        {
            "service_rate": service_rate,
            "supported_commuters": supported_commuters,
            "fallback_private_cars": fallback_private_cars,
            "avg_passengers_per_trip": avg_passengers_per_trip,
            "avg_in_vehicle_time_min": avg_in_vehicle_time_min,
            "system_vmt_reduction_pct": system_vmt_reduction_pct,
            "system_co2_reduction_pct": system_co2_reduction_pct,
        },
        sources,
    )


def collect_results(
    results_root: Path,
) -> tuple[pd.DataFrame, dict[tuple[str, str], int], dict[str, Counter]]:
    rows: list[dict[str, Any]] = []
    run_counts: dict[tuple[str, str], int] = {}
    source_counts: dict[str, Counter] = defaultdict(Counter)

    for fleet in FLEET_ORDER:
        for demand_scale in DEMAND_ORDER:
            demand_dir = results_root / fleet / demand_scale
            if not demand_dir.exists():
                print(f"[WARN] Missing directory: {demand_dir}")
                run_counts[(fleet, demand_scale)] = 0
                continue

            seed_dirs = sorted(demand_dir.glob("seed_*"), key=lambda p: p.name)
            found_for_cell = 0
            actual_demand_count = DEMAND_COUNTS[demand_scale]

            for seed_dir in seed_dirs:
                if not (seed_dir / "metrics.json").exists() and not (seed_dir / "comparison.json").exists():
                    print(f"[WARN] Missing metrics.json and comparison.json: {seed_dir}")
                    continue

                seed_str = seed_dir.name.replace("seed_", "")
                try:
                    seed = int(seed_str)
                except ValueError:
                    seed = None

                metric_values, metric_sources = extract_metrics(seed_dir, actual_demand_count)
                metadata = load_run_metadata(results_root, fleet, demand_scale, seed_dir)

                for metric_name, source in metric_sources.items():
                    source_counts[metric_name][source] += 1

                rows.append(
                    {
                        "fleet": fleet,
                        "fleet_label": FLEET_LABELS[fleet],
                        "demand_scale": demand_scale,
                        "demand_fraction": DEMAND_FRACTIONS[demand_scale],
                        "actual_demand_count": actual_demand_count,
                        "seed": seed,
                        **metadata,
                        **metric_values,
                    }
                )
                found_for_cell += 1

            run_counts[(fleet, demand_scale)] = found_for_cell

    if not rows:
        raise RuntimeError(f"No pilot-fleet demand sensitivity results found under {results_root}")

    return pd.DataFrame(rows), run_counts, source_counts


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = [
        "fleet",
        "fleet_label",
        "demand_scale",
        "demand_fraction",
        "actual_demand_count",
    ]

    available_metrics = [metric for metric in SUMMARY_METRICS if metric in df.columns]
    grouped = df.groupby(group_cols, as_index=False, dropna=False)
    summary = grouped[available_metrics].agg(["mean", "std", "count"])
    summary.columns = [
        "_".join(part for part in col if part)
        for col in summary.columns.to_flat_index()
    ]
    summary = summary.reset_index()

    for metric in available_metrics:
        count_col = f"{metric}_count"
        std_col = f"{metric}_std"
        sem_col = f"{metric}_sem"
        summary[sem_col] = summary[std_col] / summary[count_col].apply(
            lambda n: math.sqrt(n) if n and n > 0 else float("nan")
        )

    ordered_columns = group_cols[:]
    for metric in available_metrics:
        ordered_columns.extend(
            [f"{metric}_mean", f"{metric}_std", f"{metric}_sem", f"{metric}_count"]
        )

    summary = summary[ordered_columns]
    fleet_rank = {fleet: i for i, fleet in enumerate(FLEET_ORDER)}
    summary["_fleet_rank"] = summary["fleet"].map(fleet_rank)
    summary = summary.sort_values(["_fleet_rank", "demand_fraction"]).drop(columns="_fleet_rank")
    return summary


def plot_metric(
    summary: pd.DataFrame,
    output_dir: Path,
    metric: str,
    ylabel: str,
    filename: str,
    add_legend: bool = True,
) -> list[Path]:
    mean_col = f"{metric}_mean"
    sem_col = f"{metric}_sem"
    if mean_col not in summary.columns or summary[mean_col].isna().all():
        print(f"[SKIP] {metric} not available")
        return []

    fig, ax = plt.subplots(figsize=(4.8, 3.2))

    for i, fleet in enumerate(FLEET_ORDER):
        sub = summary[summary["fleet"] == fleet].sort_values("demand_fraction")
        if sub.empty or sub[mean_col].isna().all():
            continue

        ax.errorbar(
            sub["demand_fraction"],
            sub[mean_col],
            yerr=sub[sem_col] if sem_col in sub.columns else None,
            marker=FLEET_MARKERS[fleet],
            color=FLEET_COLORS[fleet],
            capsize=3,
            label=FLEET_LABELS[fleet],
        )

    ax.set_xlabel("Demand fraction")
    ax.set_ylabel(ylabel)
    ax.set_xticks([0.25, 0.50, 0.75, 1.00])
    ax.set_xticklabels(["0.25", "0.50", "0.75", "1.00"])
    ax.grid(True, linestyle=":", linewidth=0.7)
    if add_legend:
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.26),
            ncol=2,
            frameon=False,
            title=f"Mean ± {UNCERTAINTY_LABEL} across 15 seeds",
        )
    fig.subplots_adjust(left=0.15, right=0.98, top=0.94, bottom=0.34)

    pdf_path = output_dir / filename
    png_path = output_dir / filename.replace(".pdf", ".png")
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    return [pdf_path, png_path]


def plot_main_figure(summary: pd.DataFrame, output_dir: Path) -> list[Path]:
    panels = [
        ("service_rate", "Service rate (%)", "(a)"),
        ("fallback_private_cars", "Fallback private cars", "(b)"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(6.6, 3.1), sharex=True)

    for ax, (metric, ylabel, panel_label) in zip(axes, panels):
        mean_col = f"{metric}_mean"
        sem_col = f"{metric}_sem"

        for i, fleet in enumerate(FLEET_ORDER):
            sub = summary[summary["fleet"] == fleet].sort_values("demand_fraction")
            if sub.empty or mean_col not in sub.columns or sub[mean_col].isna().all():
                continue

            ax.errorbar(
                sub["demand_fraction"],
                sub[mean_col],
                yerr=sub[sem_col] if sem_col in sub.columns else None,
                marker=FLEET_MARKERS[fleet],
                color=FLEET_COLORS[fleet],
                capsize=3,
                linewidth=1.8,
            )

        ax.set_ylabel(ylabel)
        ax.set_xticks([0.25, 0.50, 0.75, 1.00])
        ax.set_xticklabels(["0.25", "0.50", "0.75", "1.00"])
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

    legend_handles = [
        Line2D(
            [0],
            [0],
            color=FLEET_COLORS[fleet],
            marker=FLEET_MARKERS[fleet],
            linestyle="-",
            linewidth=1.8,
        )
        for i, fleet in enumerate(FLEET_ORDER)
    ]
    legend_labels = [FLEET_LABELS[fleet] for fleet in FLEET_ORDER]
    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, -0.04),
        title=f"Mean ± {UNCERTAINTY_LABEL} across 15 seeds",
    )
    fig.supxlabel("Demand fraction", y=0.14)
    fig.subplots_adjust(left=0.10, right=0.99, top=0.94, bottom=0.34, wspace=0.34)

    pdf_path = output_dir / "pilot_demand_sensitivity_service_fallback.pdf"
    png_path = output_dir / "pilot_demand_sensitivity_service_fallback.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    return [pdf_path, png_path]


def latex_value(value: Any, decimals: int = 1) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.{decimals}f}"


def print_latex_table(summary: pd.DataFrame) -> None:
    headers = [
        "Fleet",
        "Demand",
        "Commuters",
        "Seats",
        "Service rate (\\%)",
        "Fallback cars",
    ]

    alignment = "l l r r r r"

    print()
    print("LaTeX table draft:")
    print()
    print(rf"\begin{{tabular}}{{{alignment}}}")
    print(r"\toprule")
    print(" & ".join(headers) + r" \\")
    print(r"\midrule")

    fleet_rank = {fleet: i for i, fleet in enumerate(FLEET_ORDER)}
    table = summary.copy()
    table["_fleet_rank"] = table["fleet"].map(fleet_rank)
    table = table.sort_values(["_fleet_rank", "demand_fraction"])

    for _, row in table.iterrows():
        seats = ""
        if "total_seats_mean" in row and not pd.isna(row["total_seats_mean"]):
            seats = f"{row['total_seats_mean']:.0f}"

        values = [
            row["fleet_label"],
            row["demand_scale"],
            f"{row['actual_demand_count']:.0f}",
            seats,
            latex_value(row.get("service_rate_mean"), 1),
            latex_value(row.get("fallback_private_cars_mean"), 1),
        ]
        print(" & ".join(values) + r" \\")

    print(r"\bottomrule")
    print(r"\end{tabular}")


def print_run_counts(run_counts: dict[tuple[str, str], int]) -> None:
    print("Runs found per fleet and demand scale:")
    for fleet in FLEET_ORDER:
        counts = [f"{scale}={run_counts.get((fleet, scale), 0)}" for scale in DEMAND_ORDER]
        print(f"  {FLEET_LABELS[fleet]}: " + ", ".join(counts))


def print_metric_sources(source_counts: dict[str, Counter]) -> None:
    print("Fields used for key paper metrics:")
    for metric in ["service_rate", "supported_commuters", "fallback_private_cars"]:
        print(f"  {metric}: {source_summary(source_counts.get(metric, Counter()))}")


def print_threshold_summary(summary: pd.DataFrame, service_rate_threshold: float) -> None:
    print()
    print("-" * 64)
    print("Threshold summary")
    print(f"  Service rate threshold: {service_rate_threshold}%")
    print("-" * 64)

    for fleet in FLEET_ORDER:
        label = FLEET_LABELS[fleet]
        sub = summary[summary["fleet"] == fleet].sort_values("demand_fraction")
        max_scale = None

        for _, row in sub.iterrows():
            service_rate = row.get("service_rate_mean")
            if pd.notna(service_rate) and service_rate >= service_rate_threshold:
                max_scale = row["demand_scale"]

        print(f"  {label:<22} service rate >= {service_rate_threshold}%: {max_scale or 'none'}")

    print("-" * 64)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate and plot pilot-fleet demand sensitivity results."
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
    parser.add_argument("--print_threshold_summary", action="store_true")
    parser.add_argument("--service_rate_threshold", type=float, default=99.0)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    configure_matplotlib()

    print(f"Reading results from: {args.results_root}")
    df, run_counts, source_counts = collect_results(args.results_root)
    summary = summarize(df)

    runs_csv = args.output_dir / "pilot_demand_sensitivity_runs.csv"
    summary_csv = args.output_dir / "pilot_demand_sensitivity_summary.csv"
    df.to_csv(runs_csv, index=False)
    summary.to_csv(summary_csv, index=False)

    summary = pd.read_csv(summary_csv)

    figure_paths: list[Path] = []
    figure_paths.extend(plot_main_figure(summary, args.output_dir))

    diagnostic_specs = [
        (
            "avg_passengers_per_trip",
            "Average passengers per trip",
            "pilot_demand_sensitivity_avg_passengers_per_trip.pdf",
        ),
        (
            "avg_in_vehicle_time_min",
            "Average in-vehicle time (min)",
            "pilot_demand_sensitivity_avg_in_vehicle_time.pdf",
        ),
        (
            "system_vmt_reduction_pct",
            "System VMT reduction (%) [diagnostic]",
            "pilot_demand_sensitivity_system_vmt_reduction.pdf",
        ),
        (
            "system_co2_reduction_pct",
            r"System CO$_2$ reduction (%) [diagnostic]",
            "pilot_demand_sensitivity_system_co2_reduction.pdf",
        ),
    ]
    for metric, ylabel, filename in diagnostic_specs:
        figure_paths.extend(plot_metric(summary, args.output_dir, metric, ylabel, filename))

    print_run_counts(run_counts)
    print()
    print(f"Wrote runs CSV: {runs_csv}")
    print(f"Wrote summary CSV: {summary_csv}")
    print("Wrote figure files:")
    for path in figure_paths:
        print(f"  {path}")
    print()
    print_metric_sources(source_counts)
    print()
    print("Definitions:")
    print("  supported_commuters means served on time by the AV fleet after pruning.")
    print("  fallback_private_cars means commuters not served on time by the AV fleet.")
    print(f"  Uncertainty is mean ± {UNCERTAINTY_LABEL} across 15 seeds.")
    print(
        "  VMT/CO2 diagnostics are excluded from the main pilot-demand figure unless "
        "the baseline is confirmed as demand-matched."
    )
    print(
        "  Interpret VMT/CO2 diagnostics cautiously if simulator output uses a "
        "full-demand baseline under partial demand."
    )

    if args.print_threshold_summary:
        print_threshold_summary(summary, args.service_rate_threshold)

    if args.print_latex:
        print_latex_table(summary)


if __name__ == "__main__":
    main()
