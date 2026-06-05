#!/usr/bin/env python3
"""
plot_tw_mode_comparison_2x2.py
Aggregates and plots results for the time-window mode comparison experiment.

Produces one compact 2x2 publication figure:
  fig_tw_mode_comparison.pdf/.png

Usage from hub_label root:
  python3 experiments/scripts/plot_tw_mode_comparison_2x2.py

Optional:
  python3 experiments/scripts/plot_tw_mode_comparison_2x2.py \
      --results-dir experiments/results/tw_mode_comparison_224seats \
      --out experiments/results/tw_mode_comparison_224seats/plots
"""

import argparse
import json
import os
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from matplotlib.ticker import AutoMinorLocator
import numpy as np
import pandas as pd
from plot_pub_style import setup_pub_style as apply_pub_style

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

ORDERED_LABELS = [
    "individual",
    "fixed_5min",
    "fixed_10min",
    "fixed_15min",
    "fixed_20min",
    "fixed_30min",
    "fixed_60min",
]

DISPLAY_LABELS = {
    "individual": "Individual",
    "fixed_5min": "5 min",
    "fixed_10min": "10 min",
    "fixed_15min": "15 min",
    "fixed_20min": "20 min",
    "fixed_30min": "30 min",
    "fixed_60min": "60 min",
}

def setup_pub_style():
    apply_pub_style()


def safe_mean(values):
    return float(np.mean(values)) if len(values) else np.nan


def safe_std(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0


def system_reduction(change_pct, system_total, baseline_total, run_path, metric_label):
    if change_pct is not None:
        return float(change_pct), -float(change_pct)
    if system_total is not None and baseline_total:
        reduction = (float(baseline_total) - float(system_total)) / float(baseline_total) * 100.0
        return -reduction, reduction
    print(
        f"  WARNING: missing system {metric_label} fields for {run_path}; "
        "setting system reduction to NaN"
    )
    return float("nan"), float("nan")


def load_condition(cond_dir):
    cond_dir = Path(cond_dir)
    if not cond_dir.is_dir():
        return None

    rows = []
    for run_dir in sorted(cond_dir.iterdir()):
        if not run_dir.is_dir():
            continue

        metrics_path = run_dir / "metrics.json"
        baseline_path = run_dir / "baseline.json"
        comparison_path = run_dir / "comparison.json"
        if not metrics_path.is_file():
            continue

        with metrics_path.open() as f:
            m = json.load(f)
        c = {}
        if comparison_path.is_file():
            with comparison_path.open() as f:
                c = json.load(f)

        baseline_vmt = 0.0
        baseline_energy = 0.0
        baseline_co2 = 0.0
        if baseline_path.is_file():
            with baseline_path.open() as f:
                b = json.load(f)
            baseline_vmt = float(
                b.get("baseline_total_vmt_km", b.get("total_vmt_km", 0.0)) or 0.0
            )
            baseline_energy = float(
                b.get("baseline_total_energy_kwh", b.get("total_energy_kwh", 0.0)) or 0.0
            )
            baseline_co2 = float(
                b.get("baseline_total_co2_kg", b.get("total_co2_kg", 0.0)) or 0.0
            )

        total = float(m.get("total_commuters", 0) or 0)
        served = float(m.get("served_commuters", 0) or 0)
        late = float(m.get("late_deliveries", 0) or 0)

        service_rate = float(
            c.get("service_rate_pct", m.get("service_rate", served / total * 100.0 if total else 0.0))
            or 0.0
        )
        eff_ot = service_rate
        on_time_rate = float(c.get("on_time_rate_pct", m.get("on_time_rate", service_rate)) or 0.0)
        fallback_private_cars = float(
            c.get("fallback_private_cars", m.get("fallback_private_cars", late + m.get("unserved_commuters", 0)))
            or 0.0
        )

        system_vmt = m.get("system_total_vmt_km")
        system_energy = m.get("system_total_energy_kwh")
        system_co2 = m.get("system_total_co2_kg")
        system_vmt_change_pct = c.get("system_vmt_change_pct", m.get("system_vmt_change_pct"))
        system_energy_change_pct = c.get(
            "system_energy_change_pct",
            m.get("system_energy_change_pct"),
        )
        system_co2_change_pct = c.get("system_co2_change_pct", m.get("system_co2_change_pct"))

        system_vmt_change_pct, vmt_red = system_reduction(
            system_vmt_change_pct, system_vmt, baseline_vmt, run_dir, "VMT"
        )
        system_energy_change_pct, energy_red = system_reduction(
            system_energy_change_pct, system_energy, baseline_energy, run_dir, "energy"
        )
        system_co2_change_pct, co2_red = system_reduction(
            system_co2_change_pct, system_co2, baseline_co2, run_dir, "CO2"
        )

        rows.append({
            "service_rate": service_rate,
            "effective_on_time_rate": eff_ot,
            "fallback_private_cars": fallback_private_cars,
            "late": late,
            "on_time_rate": on_time_rate,
            "system_vmt_change_pct": system_vmt_change_pct,
            "system_energy_change_pct": system_energy_change_pct,
            "system_co2_change_pct": system_co2_change_pct,
            "vmt_red": vmt_red,
            "energy_red": energy_red,
            "co2_red": co2_red,
            "avg_pax": float(m.get("avg_passengers_per_trip", 0.0) or 0.0),
            "empty_ratio": float(m.get("empty_vmt_ratio", 0.0) or 0.0) * 100.0,
            "detour": float(m.get("avg_detour_ratio", 0.0) or 0.0),
        })

    if not rows:
        return None

    out = {"n_runs": len(rows)}
    for key in rows[0].keys():
        vals = np.array([r[key] for r in rows], dtype=float)
        out[f"{key}_mean"] = safe_mean(vals)
        out[f"{key}_std"] = safe_std(vals)
    return out


def aggregate(results_dir):
    rows = []
    for label in ORDERED_LABELS:
        data = load_condition(Path(results_dir) / label)
        if data is None:
            print(f"  WARNING: no data for {label}")
            continue
        data["label"] = label
        data["display_label"] = DISPLAY_LABELS.get(label, label)
        data["is_individual"] = label == "individual"
        data["interval_min"] = None if label == "individual" else int(
            label.replace("fixed_", "").replace("min", "")
        )
        rows.append(data)

        print(
            f"  {label:<15}: {data['n_runs']:>2} runs, "
            f"service={data['service_rate_mean']:.1f}%, "
            f"fallback={data['fallback_private_cars_mean']:.1f}, "
            f"system VMT red={data['vmt_red_mean']:.1f}%, "
            f"system CO2 red={data['co2_red_mean']:.1f}%"
        )

    return pd.DataFrame(rows)


def padded_ylim(values, errors=None, lower_bound=None, upper_bound=None, pad_frac=0.18):
    values = np.asarray(values, dtype=float)
    if errors is None:
        errors = np.zeros_like(values)
    else:
        errors = np.asarray(errors, dtype=float)

    lo = float(np.nanmin(values - errors))
    hi = float(np.nanmax(values + errors))
    span = max(hi - lo, 1.0)
    lo -= span * pad_frac
    hi += span * pad_frac

    if lower_bound is not None:
        lo = max(lo, lower_bound)
    if upper_bound is not None:
        hi = min(hi, upper_bound)
    return lo, hi


def mark_selected_bar(ax, selected_index):
    if selected_index is None:
        return
    ax.axvline(selected_index, linestyle=":", linewidth=1.0, color="0.35", zorder=0)
    ylo, yhi = ax.get_ylim()
    ax.text(
        selected_index + 0.08,
        yhi - 0.08 * (yhi - ylo),
        "selected\n20 min",
        fontsize=7.5,
        color="0.25",
        va="top",
        ha="left",
        bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="0.85", alpha=0.85),
    )


def bar_panel(
    ax,
    x,
    means,
    stds,
    title,
    ylabel,
    selected_index,
    labels,
    color="#1f77b4",
    lower_bound=None,
    upper_bound=None,
    zero_reference=False,
):
    colors = [color] * len(x)

    for xi, mean, std, bar_color in zip(x, means, stds, colors):
        ax.bar(xi, mean, yerr=std, capsize=3, width=0.72, 
               color=bar_color, edgecolor="0.2", linewidth=0.8, alpha=0.85)

    ax.set_title(title, pad=6, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    ax.set_ylim(*padded_ylim(means, stds, lower_bound=lower_bound, upper_bound=upper_bound))
    ylo, yhi = ax.get_ylim()
    if zero_reference and ylo < 0 < yhi:
        ax.axhline(0, color="0.35", linewidth=0.9, linestyle="-", alpha=0.7, zorder=0)
    mark_selected_bar(ax, selected_index)


def fig_tw_mode_comparison(df, out_dir):
    labels = df["display_label"].tolist()
    x = np.arange(len(df))
    selected_index = labels.index("20 min") if "20 min" in labels else None

    service_m = df["service_rate_mean"].to_numpy(dtype=float)
    service_s = df["service_rate_std"].fillna(0).to_numpy(dtype=float)
    fallback_m = df["fallback_private_cars_mean"].to_numpy(dtype=float)
    fallback_s = df["fallback_private_cars_std"].fillna(0).to_numpy(dtype=float)
    vmt_m = df["vmt_red_mean"].to_numpy(dtype=float)
    vmt_s = df["vmt_red_std"].fillna(0).to_numpy(dtype=float)
    co2_m = df["co2_red_mean"].to_numpy(dtype=float)
    co2_s = df["co2_red_std"].fillna(0).to_numpy(dtype=float)

    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2), sharex=False)
    axes = axes.ravel()

    bar_panel(
        axes[0], x, service_m, service_s,
        "(a) Service Rate", "Service rate (%)", selected_index, labels,
        color="#1f77b4",
        lower_bound=0,
        upper_bound=105,
    )
    bar_panel(
        axes[1], x, fallback_m, fallback_s,
        "(b) Fallback Private Cars", "Fallback private cars", selected_index, labels,
        color="#2ca02c",
        lower_bound=0,
    )
    bar_panel(
        axes[2], x, vmt_m, vmt_s,
        "(c) System VMT Reduction", "System VMT reduction (%)", selected_index, labels,
        color="#ff7f0e",
        zero_reference=True,
    )
    bar_panel(
        axes[3], x, co2_m, co2_s,
        r"(d) System CO$_2$ Reduction", r"System CO$_2$ reduction (%)", selected_index, labels,
        color="#d62728",
        zero_reference=True,
    )

    for ax in axes:
        ax.set_xlabel("Time-window representation")

    fig.tight_layout(w_pad=1.2, h_pad=1.4)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / "fig_tw_mode_comparison"
    fig.savefig(str(base) + ".pdf", bbox_inches="tight")
    fig.savefig(str(base) + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base}.pdf")
    print(f"  Saved: {base}.png")


def print_summary(df):
    print(
        f"\n  {'Condition':<15}  {'Runs':>4}  {'Service%':>9}  {'Fallback':>8}  "
        f"{'Sys VMT%':>9}  {'Sys kWh%':>9}  {'Sys CO2%':>9}  {'Pax/trip':>8}"
    )
    print(f"  {'-' * 96}")
    for _, r in df.iterrows():
        tag = " <- selected" if r["label"] == "fixed_20min" else ""
        print(
            f"  {r['label']:<15}  {int(r['n_runs']):>4}  "
            f"{r['service_rate_mean']:>8.1f}%  "
            f"{r['fallback_private_cars_mean']:>8.1f}  "
            f"{r['vmt_red_mean']:>8.1f}%  "
            f"{r['energy_red_mean']:>8.1f}%  "
            f"{r['co2_red_mean']:>8.1f}%  "
            f"{r['avg_pax_mean']:>8.2f}{tag}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="experiments/results/tw_mode_comparison_224seats")
    parser.add_argument("--out", default="experiments/results/tw_mode_comparison_224seats/plots")
    args = parser.parse_args()

    setup_pub_style()
    print("Aggregating time-window mode comparison results...")
    df = aggregate(args.results_dir)

    if df.empty:
        print("ERROR: no data found. Check --results-dir path.")
        return

    csv_path = Path(args.results_dir) / "tw_mode_comparison_summary.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df)

    print(f"\nGenerating plot -> {args.out}")
    fig_tw_mode_comparison(df, args.out)
    print("\nDone.")


if __name__ == "__main__":
    main()
