#!/usr/bin/env python3
"""
Aggregate and plot residential-origin representative-fleet capacity sensitivity.

This script reads existing results only. It does not rerun optimization.

Expected result layout:

experiments/results/capacity_sensitivity_representative_residential/
  all_car/
    x0.90/
      seed_1/
        metrics.json
        comparison.json
        config.json
      ...
  balanced/
  vmt_oriented/
  low_emission/

The main paper-facing capacity figure uses explicit system-level VMT and CO2
reductions. Service rate and fallback private cars remain available in summary
tables and individual diagnostic plots. System metrics include AV service plus
fallback private-car trips.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from plot_pub_style import setup_pub_style as apply_pub_style


FLEET_ORDER = ["all_car", "balanced", "vmt_oriented", "low_emission"]
FLEET_LABELS = {
    "all_car": "All-car",
    "balanced": "Balanced",
    "vmt_oriented": "VMT-oriented",
    "low_emission": "Low-emission",
}
FLEET_MARKERS = {
    "all_car": "o",
    "balanced": "s",
    "vmt_oriented": "^",
    "low_emission": "D",
}
FLEET_COLORS = {
    "all_car": "#0072B2",
    "balanced": "#E69F00",
    "vmt_oriented": "#56B4E9",
    "low_emission": "#CC79A7",
}

SCALE_ORDER = ["x0.90", "x1.00", "x1.10", "x1.25"]

PRIMARY_METRICS = [
    "service_rate",
    "fallback_private_cars",
    "system_vmt_reduction_pct",
    "system_co2_reduction_pct",
]
OPTIONAL_METRICS = [
    "avg_in_vehicle_time_min",
    "avg_passengers_per_trip",
]
METADATA_METRICS = [
    "total_seats",
    "total_fleet_vehicles",
]
SUMMARY_METRICS = PRIMARY_METRICS + METADATA_METRICS + OPTIONAL_METRICS
UNCERTAINTY_LABEL = "SEM"


def configure_matplotlib() -> None:
    apply_pub_style()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def find_value(data: dict[str, Any], candidates: list[str]) -> tuple[float | None, str | None]:
    """Search nested dictionaries using dot-separated candidate keys."""
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
                return float(cur), key
            except (TypeError, ValueError):
                pass
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


def system_reduction_from_sources(
    metrics_data: dict[str, Any],
    comparison_data: dict[str, Any],
    reduction_key: str,
    change_key: str,
) -> tuple[float | None, str]:
    value, source = first_from_sources(metrics_data, comparison_data, [reduction_key])
    if value is not None:
        return normalize_percent(value), source

    change, source = first_from_sources(metrics_data, comparison_data, [change_key])
    if change is not None:
        return normalize_percent(-change), f"{source} (negated)"

    return None, "missing"


def extract_metrics(run_dir: Path) -> tuple[dict[str, float | None], dict[str, str]]:
    metrics_data = read_json(run_dir / "metrics.json")
    comparison_data = read_json(run_dir / "comparison.json")
    sources: dict[str, str] = {}

    service_rate, sources["service_rate"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "service_rate",
            "service_rate_pct",
            "metrics.service_rate",
            "metrics.service_rate_pct",
        ],
    )
    service_rate = normalize_percent(service_rate)

    fallback_private_cars, sources["fallback_private_cars"] = first_from_sources(
        metrics_data,
        comparison_data,
        [
            "fallback_private_cars",
            "metrics.fallback_private_cars",
        ],
    )
    if fallback_private_cars is None:
        late, late_source = first_from_sources(metrics_data, comparison_data, ["late_deliveries"])
        unserved, unserved_source = first_from_sources(
            metrics_data, comparison_data, ["unserved_commuters"]
        )
        if late is not None or unserved is not None:
            fallback_private_cars = (late or 0.0) + (unserved or 0.0)
            sources["fallback_private_cars"] = (
                f"derived from {late_source} + {unserved_source}"
            )

    system_vmt_reduction_pct, sources["system_vmt_reduction_pct"] = system_reduction_from_sources(
        metrics_data,
        comparison_data,
        "system_vmt_reduction_pct",
        "system_vmt_change_pct",
    )
    system_co2_reduction_pct, sources["system_co2_reduction_pct"] = system_reduction_from_sources(
        metrics_data,
        comparison_data,
        "system_co2_reduction_pct",
        "system_co2_change_pct",
    )

    avg_in_vehicle_time_min, sources["avg_in_vehicle_time_min"] = first_from_sources(
        metrics_data,
        comparison_data,
        ["avg_in_vehicle_time_min", "avg_ivt_min"],
    )
    avg_passengers_per_trip, sources["avg_passengers_per_trip"] = first_from_sources(
        metrics_data,
        comparison_data,
        ["avg_passengers_per_trip", "avg_pax_per_trip", "pax_per_trip"],
    )

    return (
        {
            "service_rate": service_rate,
            "fallback_private_cars": fallback_private_cars,
            "system_vmt_reduction_pct": system_vmt_reduction_pct,
            "system_co2_reduction_pct": system_co2_reduction_pct,
            "avg_in_vehicle_time_min": avg_in_vehicle_time_min,
            "avg_passengers_per_trip": avg_passengers_per_trip,
        },
        sources,
    )


def fleet_metadata_from_config(config: dict[str, Any]) -> dict[str, float | None]:
    capacity_meta = config.get("capacity_metadata", {})
    fleet = config.get("fleet", {})
    vehicle_types = fleet.get("vehicle_types", [])

    total_seats = capacity_meta.get("total_fleet_seats")
    if total_seats is None and isinstance(vehicle_types, list):
        total_seats = 0
        found_vehicle = False
        for vehicle_type in vehicle_types:
            try:
                total_seats += float(vehicle_type["fleet_size"]) * float(vehicle_type["capacity"])
                found_vehicle = True
            except (KeyError, TypeError, ValueError):
                pass
        if not found_vehicle:
            total_seats = None

    count_keys = ["scooter_count", "moped_count", "car_count", "minibus_count"]
    counts = [capacity_meta.get(key) for key in count_keys]
    total_fleet_vehicles = None
    if any(count is not None for count in counts):
        total_fleet_vehicles = sum(float(count or 0.0) for count in counts)
    elif isinstance(vehicle_types, list):
        total_fleet_vehicles = 0
        found_vehicle = False
        for vehicle_type in vehicle_types:
            try:
                total_fleet_vehicles += float(vehicle_type["fleet_size"])
                found_vehicle = True
            except (KeyError, TypeError, ValueError):
                pass
        if not found_vehicle:
            total_fleet_vehicles = None

    return {
        "total_seats": float(total_seats) if total_seats is not None else None,
        "total_fleet_vehicles": (
            float(total_fleet_vehicles) if total_fleet_vehicles is not None else None
        ),
    }


def load_scale_metadata(results_root: Path, fleet: str, scale: str, seed_dir: Path) -> dict[str, float | None]:
    config_paths = [
        results_root / "configs" / f"{fleet}_{scale}.json",
        seed_dir / "config.json",
    ]
    for config_path in config_paths:
        config = read_json(config_path)
        if config:
            return fleet_metadata_from_config(config)
    return {"total_seats": None, "total_fleet_vehicles": None}


def collect_results(results_root: Path) -> tuple[pd.DataFrame, dict[tuple[str, str], int], dict[str, Counter]]:
    rows: list[dict[str, Any]] = []
    run_counts: dict[tuple[str, str], int] = {}
    source_counts: dict[str, Counter] = defaultdict(Counter)

    for fleet in FLEET_ORDER:
        for scale in SCALE_ORDER:
            scale_dir = results_root / fleet / scale
            if not scale_dir.exists():
                print(f"[WARN] Missing directory: {scale_dir}")
                run_counts[(fleet, scale)] = 0
                continue

            seed_dirs = sorted(scale_dir.glob("seed_*"), key=lambda p: p.name)
            found_for_scale = 0

            for seed_dir in seed_dirs:
                if not (seed_dir / "metrics.json").exists() and not (seed_dir / "comparison.json").exists():
                    print(f"[WARN] Missing metrics.json and comparison.json: {seed_dir}")
                    continue

                seed_str = seed_dir.name.replace("seed_", "")
                try:
                    seed = int(seed_str)
                except ValueError:
                    seed = None

                metric_values, metric_sources = extract_metrics(seed_dir)
                metadata = load_scale_metadata(results_root, fleet, scale, seed_dir)

                for metric_name, source in metric_sources.items():
                    source_counts[metric_name][source] += 1

                rows.append(
                    {
                        "fleet": fleet,
                        "fleet_label": FLEET_LABELS[fleet],
                        "scale": scale,
                        "scale_value": float(scale.replace("x", "")),
                        "seed": seed,
                        **metadata,
                        **metric_values,
                    }
                )
                found_for_scale += 1

            run_counts[(fleet, scale)] = found_for_scale

    if not rows:
        raise RuntimeError(f"No residential-origin capacity results found under {results_root}")

    return pd.DataFrame(rows), run_counts, source_counts


def mean_std_sem_summary(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby(
        [
            "fleet",
            "fleet_label",
            "scale",
            "scale_value",
        ],
        as_index=False,
        dropna=False,
    )

    summary = grouped[SUMMARY_METRICS].agg(["mean", "std", "count"])
    summary.columns = [
        "_".join([part for part in col if part])
        for col in summary.columns.to_flat_index()
    ]
    summary = summary.reset_index()

    for metric in SUMMARY_METRICS:
        summary[f"{metric}_sem"] = summary[f"{metric}_std"] / summary[
            f"{metric}_count"
        ].apply(lambda n: math.sqrt(n) if n and n > 0 else float("nan"))

    ordered_columns = [
        "fleet",
        "fleet_label",
        "scale",
        "scale_value",
    ]
    for metric in SUMMARY_METRICS:
        ordered_columns.extend(
            [
                f"{metric}_mean",
                f"{metric}_std",
                f"{metric}_sem",
                f"{metric}_count",
            ]
        )

    summary = summary[ordered_columns]
    fleet_rank = {fleet: i for i, fleet in enumerate(FLEET_ORDER)}
    summary["_fleet_rank"] = summary["fleet"].map(fleet_rank)
    summary = summary.sort_values(["_fleet_rank", "scale_value"]).drop(columns="_fleet_rank")
    return summary


def plot_metric(
    summary: pd.DataFrame,
    output_dir: Path,
    metric: str,
    ylabel: str,
    filename: str,
    add_legend: bool = True,
) -> Path:
    fig, ax = plt.subplots(figsize=(4.8, 3.2))

    for fleet in FLEET_ORDER:
        sub = summary[summary["fleet"] == fleet].sort_values("scale_value")
        if sub.empty or sub[f"{metric}_mean"].isna().all():
            continue

        ax.errorbar(
            sub["scale_value"],
            sub[f"{metric}_mean"],
            yerr=sub[f"{metric}_sem"],
            marker=FLEET_MARKERS[fleet],
            color=FLEET_COLORS[fleet],
            capsize=3,
            label=FLEET_LABELS[fleet],
        )

    ax.axvline(1.0, linestyle="--", linewidth=1.0, color="0.35")
    ax.set_xlabel("Capacity scale relative to 224-seat reference")
    ax.set_ylabel(ylabel)
    ax.set_xticks([0.90, 1.00, 1.10, 1.25])
    ax.set_xticklabels(["0.90", "1.00", "1.10", "1.25"])
    ax.grid(True, linestyle=":", linewidth=0.7)
    if add_legend:
        ax.legend(frameon=False, title=f"Mean ± {UNCERTAINTY_LABEL}")
    fig.tight_layout()

    pdf_path = output_dir / filename
    png_path = output_dir / filename.replace(".pdf", ".png")
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    return pdf_path


def plot_vmt_co2_figure(summary: pd.DataFrame, output_dir: Path) -> list[Path]:
    panels = [
        ("system_vmt_reduction_pct", "System VMT reduction (%)", "(a)"),
        ("system_co2_reduction_pct", r"System CO$_2$ reduction (%)", "(b)"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(6.8, 3.2), sharex=True)

    for ax, (metric, ylabel, panel_label) in zip(axes, panels):
        for fleet in FLEET_ORDER:
            sub = summary[summary["fleet"] == fleet].sort_values("scale_value")
            if sub.empty or sub[f"{metric}_mean"].isna().all():
                continue

            ax.errorbar(
                sub["scale_value"],
                sub[f"{metric}_mean"],
                yerr=sub[f"{metric}_sem"],
                marker=FLEET_MARKERS[fleet],
                color=FLEET_COLORS[fleet],
                capsize=3,
                linewidth=1.8,
            )

        ax.axvline(1.0, linestyle="--", linewidth=1.0, color="0.35")
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

    legend_handles = [
        Line2D(
            [0],
            [0],
            color=FLEET_COLORS[fleet],
            marker=FLEET_MARKERS[fleet],
            linestyle="-",
            linewidth=1.8,
        )
        for fleet in FLEET_ORDER
    ]
    legend_labels = [FLEET_LABELS[fleet] for fleet in FLEET_ORDER]
    fig.legend(
        legend_handles,
        legend_labels,
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.01),
        title=f"Mean ± {UNCERTAINTY_LABEL} across seeds",
    )
    fig.supxlabel("Capacity scale relative to 224-seat reference", y=0.17)
    fig.subplots_adjust(left=0.10, right=0.99, top=0.94, bottom=0.36, wspace=0.34)

    pdf_path = output_dir / "capacity_sensitivity_vmt_co2.pdf"
    png_path = output_dir / "capacity_sensitivity_vmt_co2.png"
    fig.savefig(pdf_path, bbox_inches="tight")
    fig.savefig(png_path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    return [pdf_path, png_path]


def latex_value(value: Any, decimals: int = 1) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.{decimals}f}"


def print_latex_table(summary: pd.DataFrame) -> None:
    print()
    print("LaTeX table draft:")
    print()
    headers = [
        "Fleet",
        "Scale",
        "Seats",
        "Service rate (\\%)",
        "Fallback cars",
        "System VMT red. (\\%)",
        "System \\COtwo{} red. (\\%)",
    ]
    print(r"\begin{tabular}{l l r r r r r}")
    print(r"\toprule")
    print(" & ".join(headers) + r" \\")
    print(r"\midrule")

    fleet_rank = {fleet: i for i, fleet in enumerate(FLEET_ORDER)}
    table = summary.copy()
    table["_fleet_rank"] = table["fleet"].map(fleet_rank)
    table = table.sort_values(["_fleet_rank", "scale_value"])
    for _, row in table.iterrows():
        seats = "" if pd.isna(row["total_seats_mean"]) else f"{row['total_seats_mean']:.0f}"
        values = [
            row["fleet_label"],
            row["scale"],
            seats,
            latex_value(row["service_rate_mean"], 1),
            latex_value(row["fallback_private_cars_mean"], 1),
            latex_value(row["system_vmt_reduction_pct_mean"], 1),
            latex_value(row["system_co2_reduction_pct_mean"], 1),
        ]
        print(" & ".join(values) + r" \\")

    print(r"\bottomrule")
    print(r"\end{tabular}")


def print_run_counts(run_counts: dict[tuple[str, str], int]) -> None:
    print("Runs found per fleet and scale:")
    for fleet in FLEET_ORDER:
        counts = [f"{scale}={run_counts.get((fleet, scale), 0)}" for scale in SCALE_ORDER]
        print(f"  {FLEET_LABELS[fleet]}: " + ", ".join(counts))


def print_metric_sources(source_counts: dict[str, Counter]) -> None:
    labels = {
        "service_rate": "service",
        "fallback_private_cars": "fallback",
        "system_vmt_reduction_pct": "system VMT",
        "system_co2_reduction_pct": "system CO2",
    }
    print("Metric fields used:")
    for metric in PRIMARY_METRICS:
        counts = source_counts.get(metric, Counter())
        details = ", ".join(f"{source} ({count})" for source, count in counts.most_common())
        print(f"  {labels[metric]}: {details or 'missing'}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results_root",
        type=Path,
        default=Path("experiments/results/capacity_sensitivity_representative_residential"),
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=Path("experiments/results/capacity_sensitivity_representative_residential/plots"),
    )
    parser.add_argument("--print_latex", action="store_true")

    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    configure_matplotlib()

    df, run_counts, source_counts = collect_results(args.results_root)
    summary = mean_std_sem_summary(df)

    raw_csv = args.output_dir / "capacity_sensitivity_runs.csv"
    summary_csv = args.output_dir / "capacity_sensitivity_summary.csv"
    df.to_csv(raw_csv, index=False)
    summary.to_csv(summary_csv, index=False)

    # Reload the summary CSV so plots use the written summary artifact.
    summary = pd.read_csv(summary_csv)

    main_figure_paths = plot_vmt_co2_figure(summary, args.output_dir)
    diagnostic_figure_paths: list[Path] = []
    diagnostic_figure_paths.append(
        plot_metric(
            summary,
            args.output_dir,
            "service_rate",
            "Service rate (%)",
            "capacity_sensitivity_service.pdf",
        )
    )
    diagnostic_figure_paths.append(
        plot_metric(
            summary,
            args.output_dir,
            "fallback_private_cars",
            "Fallback private cars",
            "capacity_sensitivity_fallback_private_cars.pdf",
        )
    )
    diagnostic_figure_paths.append(
        plot_metric(
            summary,
            args.output_dir,
            "system_vmt_reduction_pct",
            "System VMT reduction (%)",
            "capacity_sensitivity_vmt.pdf",
        )
    )
    diagnostic_figure_paths.append(
        plot_metric(
            summary,
            args.output_dir,
            "system_co2_reduction_pct",
            r"System CO$_2$ reduction (%)",
            "capacity_sensitivity_co2.pdf",
        )
    )
    if "avg_passengers_per_trip_mean" in summary and not summary[
        "avg_passengers_per_trip_mean"
    ].isna().all():
        diagnostic_figure_paths.append(
            plot_metric(
                summary,
                args.output_dir,
                "avg_passengers_per_trip",
                "Average passengers per trip",
                "capacity_sensitivity_pax_per_trip.pdf",
            )
        )

    print_run_counts(run_counts)
    print(f"Wrote raw run CSV:     {raw_csv}")
    print(f"Wrote summary CSV:     {summary_csv}")
    print("Wrote main paper-facing capacity figure:")
    for path in main_figure_paths:
        print(f"  {path}")
    print("Diagnostic figure files:")
    for path in diagnostic_figure_paths:
        print(f"  {path}")
        png_path = path.with_suffix(".png")
        if png_path.exists() and png_path not in diagnostic_figure_paths:
            print(f"  {png_path}")
    print("Diagnostic 1x3 system-metrics figure: suppressed by default.")
    print_metric_sources(source_counts)
    print("Note: system metrics include AV service and fallback private-car trips.")
    print(
        "Note: this capacity sweep is a local sensitivity analysis around the "
        "224-seat reference, not fleet-size optimization."
    )
    print(f"Uncertainty shown as mean +/- {UNCERTAINTY_LABEL} across seeds.")

    if args.print_latex:
        print_latex_table(summary)


if __name__ == "__main__":
    main()
