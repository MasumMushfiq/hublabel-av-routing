#!/usr/bin/env python3
"""Aggregate and plot the Footscray pilot-fleet demand sensitivity."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from plot_pub_style import setup_pub_style  # noqa: E402

DEFAULT_RESULTS = Path(
    "experiments/results/footscray/pilot_fleet_demand_sensitivity_footscray"
)
FLEET_ORDER = ["balanced_pilot", "vmt_oriented_pilot", "low_emission_pilot", "all_car_pilot"]
FLEET_LABELS = {
    "balanced_pilot": "Balanced pilot",
    "vmt_oriented_pilot": "VMT-oriented pilot",
    "low_emission_pilot": "Low-emission S50/M50 pilot",
    "all_car_pilot": "All-car pilot",
}
COLORS = dict(zip(FLEET_ORDER, ["#E69F00", "#56B4E9", "#CC79A7", "#0072B2"]))
MARKERS = dict(zip(FLEET_ORDER, ["s", "^", "D", "o"]))

REQUIRED_METRICS = [
    "service_rate",
    "fallback_private_cars",
    "system_vmt_reduction_pct",
    "system_energy_reduction_pct",
    "system_co2_reduction_pct",
    "avg_passengers_per_trip",
]
OPTIONAL_METRICS = [
    "system_total_vmt_km",
    "system_total_energy_kwh",
    "system_total_co2_kg",
    "av_fleet_fixed_cost",
    "av_distance_operating_cost",
    "av_energy_cost",
    "av_total_operating_cost",
    "av_cost_per_served_commuter",
    "av_cost_per_commuter_total",
    "av_cost_per_passenger_km",
    "av_cost_per_vehicle_km",
    "baseline_parking_spaces",
    "station_commuter_parking_spaces",
    "station_parking_reduction_pct",
    "fleet_storage_equiv_spaces",
    "net_parking_equiv_if_fleet_stored_at_station",
    "net_parking_reduction_pct_if_fleet_stored_at_station",
]
COUNT_COLUMNS = ["scooter_count", "moped_count", "car_count", "minibus_count"]
SHARE_COLUMNS = [
    "realized_scooter_seat_share_pct",
    "realized_moped_seat_share_pct",
    "realized_car_seat_share_pct",
    "realized_minibus_seat_share_pct",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def number(*values: Any) -> float:
    for value in values:
        if value is None or isinstance(value, (dict, list)):
            continue
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isnan(result):
            return result
    return float("nan")


def reduction_pct(metric: str, metrics: dict[str, Any], comparison: dict[str, Any], baseline: dict[str, Any]) -> float:
    direct = number(comparison.get(f"system_{metric}_reduction_pct"), metrics.get(f"system_{metric}_reduction_pct"))
    if not math.isnan(direct):
        return direct * 100 if -1 <= direct <= 1 else direct
    change = number(comparison.get(f"system_{metric}_change_pct"), metrics.get(f"system_{metric}_change_pct"))
    if not math.isnan(change):
        change = change * 100 if -1 <= change <= 1 else change
        return -change
    suffix = "km" if metric == "vmt" else "kwh" if metric == "energy" else "kg"
    total = number(comparison.get(f"system_total_{metric}_{suffix}"), metrics.get(f"system_total_{metric}_{suffix}"))
    baseline_total = number(baseline.get(f"baseline_total_{metric}_{suffix}"), baseline.get(f"total_{metric}_{suffix}"))
    if math.isnan(total) or math.isnan(baseline_total) or baseline_total == 0:
        return float("nan")
    return 100 * (baseline_total - total) / baseline_total


def extract_run(metrics_path: Path) -> dict[str, Any]:
    run_dir = metrics_path.parent
    metrics = read_json(metrics_path)
    comparison = read_json(run_dir / "comparison.json")
    baseline = read_json(run_dir / "baseline.json")
    config = read_json(run_dir / "config.json")
    metadata = config.get("pilot_fleet_metadata", {})
    if not metadata:
        raise ValueError(f"Missing pilot_fleet_metadata in {run_dir / 'config.json'}")

    served = number(comparison.get("served_commuters"), metrics.get("served_commuters"))
    total = number(metadata.get("actual_demand_count"), comparison.get("total_commuters"), metrics.get("total_commuters"))
    service_rate = number(comparison.get("service_rate_pct"), comparison.get("service_rate"), metrics.get("service_rate"))
    if math.isnan(service_rate) and not math.isnan(served) and total > 0:
        service_rate = 100 * served / total
    if not math.isnan(service_rate) and -1 <= service_rate <= 1:
        service_rate *= 100

    row = {
        **metadata,
        "seed": run_dir.name.replace("seed_", ""),
        "service_rate": service_rate,
        "fallback_private_cars": number(
            comparison.get("fallback_private_cars"), metrics.get("fallback_private_cars"),
            total - served if not math.isnan(total) and not math.isnan(served) else None,
        ),
        "system_vmt_reduction_pct": reduction_pct("vmt", metrics, comparison, baseline),
        "system_energy_reduction_pct": reduction_pct("energy", metrics, comparison, baseline),
        "system_co2_reduction_pct": reduction_pct("co2", metrics, comparison, baseline),
        "avg_passengers_per_trip": number(comparison.get("avg_passengers_per_trip"), metrics.get("avg_passengers_per_trip")),
    }
    for metric in OPTIONAL_METRICS:
        row[metric] = number(comparison.get(metric), metrics.get(metric), baseline.get(metric))
    return row


def collect(results_dir: Path) -> pd.DataFrame:
    paths = sorted(results_dir.glob("**/metrics.json"))
    if not paths:
        raise RuntimeError(f"No metrics.json files found under {results_dir}")
    return pd.DataFrame(extract_run(path) for path in paths)


def summarize(runs: pd.DataFrame) -> pd.DataFrame:
    group_columns = [
        "pilot_fleet_name",
        "demand_fraction",
        "requested_demand_count",
        "actual_demand_count",
        "actual_total_seats",
        *COUNT_COLUMNS,
        *SHARE_COLUMNS,
    ]
    metrics = REQUIRED_METRICS + [metric for metric in OPTIONAL_METRICS if runs[metric].notna().any()]
    rows = []
    for keys, group in runs.groupby(group_columns, dropna=False, sort=False):
        row = dict(zip(group_columns, keys))
        row["runs"] = len(group)
        for metric in metrics:
            row[f"{metric}_mean"] = group[metric].mean()
            row[f"{metric}_std"] = group[metric].std()
        rows.append(row)
    result = pd.DataFrame(rows)
    ranks = {name: index for index, name in enumerate(FLEET_ORDER)}
    result["_rank"] = result["pilot_fleet_name"].map(ranks)
    return result.sort_values(["_rank", "demand_fraction"]).drop(columns="_rank")


def plot(summary: pd.DataFrame, out_dir: Path) -> list[Path]:
    setup_pub_style()
    panels = [
        ("service_rate", "Service rate (%)"),
        ("fallback_private_cars", "Fallback private cars"),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.3), sharex=True)
    for ax, (metric, ylabel) in zip(axes, panels):
        for fleet in FLEET_ORDER:
            part = summary[summary["pilot_fleet_name"] == fleet].sort_values("actual_demand_count")
            if part.empty or part[f"{metric}_mean"].isna().all():
                continue
            ax.errorbar(
                part["actual_demand_count"], part[f"{metric}_mean"],
                yerr=part[f"{metric}_std"], color=COLORS[fleet], marker=MARKERS[fleet],
                capsize=3, label=FLEET_LABELS[fleet],
            )
        ax.set_xlabel("Actual Footscray demand count")
        ax.set_ylabel(ylabel)
        ax.set_xticks([147, 293, 440, 586])
        ax.grid(True, linestyle=":", linewidth=0.7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=2, frameon=False)
    fig.subplots_adjust(bottom=0.35, wspace=0.32)
    paths = [
        out_dir / "pilot_fleet_demand_sensitivity_service_fallback.pdf",
        out_dir / "pilot_fleet_demand_sensitivity_service_fallback.png",
    ]
    fig.savefig(paths[0], bbox_inches="tight")
    fig.savefig(paths[1], bbox_inches="tight", dpi=300)
    plt.close(fig)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", "--results_dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", "--output-dir", "--output_dir", type=Path)
    args = parser.parse_args()
    out_dir = args.out or args.results_dir / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)

    runs = collect(args.results_dir)
    summary = summarize(runs)
    runs_path = out_dir / "pilot_fleet_demand_sensitivity_runs.csv"
    summary_path = out_dir / "pilot_fleet_demand_sensitivity_summary.csv"
    runs.to_csv(runs_path, index=False)
    summary.to_csv(summary_path, index=False)
    figures = plot(summary, out_dir)
    print(f"Footscray runs: {len(runs)}")
    print(f"Wrote {summary_path}")
    for path in figures:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
