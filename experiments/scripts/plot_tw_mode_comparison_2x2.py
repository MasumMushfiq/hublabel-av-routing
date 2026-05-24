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

FULL_SERVICE_THRESHOLD = 99.9


def setup_pub_style():
    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "axes.linewidth": 1.0,
        "grid.alpha": 0.30,
        "grid.linewidth": 0.7,
        "font.size": 10,
        "axes.labelsize": 11.5,
        "axes.titlesize": 11.5,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def safe_mean(values):
    return float(np.mean(values)) if len(values) else np.nan


def safe_std(values):
    return float(np.std(values, ddof=1)) if len(values) > 1 else 0.0


def effective_on_time_rate(metrics):
    """Return effective on-time service rate over total original demand."""
    if "effective_on_time_service_rate" in metrics:
        return float(metrics.get("effective_on_time_service_rate", 0.0))

    total = float(metrics.get("total_commuters", 0) or 0)
    served = float(metrics.get("served_commuters", 0) or 0)
    late = float(metrics.get("late_deliveries", 0) or 0)
    if total <= 0:
        return 0.0
    return max(0.0, served - late) / total * 100.0


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
        if not metrics_path.is_file():
            continue

        with metrics_path.open() as f:
            m = json.load(f)

        baseline_vmt = 0.0
        baseline_co2 = 0.0
        if baseline_path.is_file():
            with baseline_path.open() as f:
                b = json.load(f)
            baseline_vmt = float(b.get("total_vmt_km", 0.0) or 0.0)
            baseline_co2 = float(b.get("total_co2_kg", 0.0) or 0.0)

        total = float(m.get("total_commuters", 0) or 0)
        served = float(m.get("served_commuters", 0) or 0)
        late = float(m.get("late_deliveries", 0) or 0)
        total_vmt = float(m.get("total_vmt_km", 0.0) or 0.0)
        total_co2 = float(m.get("total_co2_kg", 0.0) or 0.0)

        service_rate = served / total * 100.0 if total else 0.0
        eff_ot = effective_on_time_rate(m)
        on_time_rate = float(m.get("on_time_rate", 0.0) or 0.0)  # among served, if present
        vmt_red = (baseline_vmt - total_vmt) / baseline_vmt * 100.0 if baseline_vmt else 0.0
        co2_red = (baseline_co2 - total_co2) / baseline_co2 * 100.0 if baseline_co2 else 0.0

        rows.append({
            "service_rate": service_rate,
            "effective_on_time_rate": eff_ot,
            "late": late,
            "on_time_rate": on_time_rate,
            "vmt_red": vmt_red,
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
            f"served={data['service_rate_mean']:.1f}%, "
            f"EffOT={data['effective_on_time_rate_mean']:.1f}%, "
            f"late={data['late_mean']:.1f}, "
            f"VMT red={data['vmt_red_mean']:.1f}%, "
            f"CO2 red={data['co2_red_mean']:.1f}%"
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


def get_bar_colors_and_hatches(service_rates, base_color="#1f77b4"):
    """
    Return arrays of colors and hatch patterns based on service rates.
    Modes with service_rate < FULL_SERVICE_THRESHOLD get gray fill with hatching to flag partial service.
    """
    colors = []
    hatches = []
    for sr in service_rates:
        if sr < FULL_SERVICE_THRESHOLD:
            colors.append("#d0d0d0")  # light gray
            hatches.append("//")
        else:
            colors.append(base_color)
            hatches.append("")
    return colors, hatches


def mark_selected_bar(ax, selected_index):
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


def bar_panel(ax, x, means, stds, title, ylabel, selected_index, labels, ylim=None, 
              colors=None, hatches=None):
    if colors is None:
        colors = ["#1f77b4"] * len(x)
    if hatches is None:
        hatches = [""] * len(x)
    
    for i, (xi, mean, std, color, hatch) in enumerate(zip(x, means, stds, colors, hatches)):
        ax.bar(xi, mean, yerr=std, capsize=3, width=0.72, 
               color=color, hatch=hatch, edgecolor="0.2", linewidth=0.8, alpha=0.85)
    
    ax.set_title(title, pad=6, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)
    if ylim is not None:
        ax.set_ylim(*ylim)
    mark_selected_bar(ax, selected_index)


def fig_tw_mode_comparison(df, out_dir):
    labels = df["display_label"].tolist()
    x = np.arange(len(df))
    selected_index = labels.index("20 min") if "20 min" in labels else None

    service_m = df["service_rate_mean"].to_numpy(dtype=float)
    service_s = df["service_rate_std"].fillna(0).to_numpy(dtype=float)
    eff_m = df["effective_on_time_rate_mean"].to_numpy(dtype=float)
    eff_s = df["effective_on_time_rate_std"].fillna(0).to_numpy(dtype=float)
    vmt_m = df["vmt_red_mean"].to_numpy(dtype=float)
    vmt_s = df["vmt_red_std"].fillna(0).to_numpy(dtype=float)
    co2_m = df["co2_red_mean"].to_numpy(dtype=float)
    co2_s = df["co2_red_std"].fillna(0).to_numpy(dtype=float)

    # Get hatch patterns for all bars based on service coverage
    service_colors, service_hatches = get_bar_colors_and_hatches(service_m, "#1f77b4")
    eff_colors, eff_hatches = get_bar_colors_and_hatches(service_m, "#2ca02c")
    vmt_colors, vmt_hatches = get_bar_colors_and_hatches(service_m, "#ff7f0e")
    co2_colors, co2_hatches = get_bar_colors_and_hatches(service_m, "#d62728")

    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2), sharex=False)
    axes = axes.ravel()

    bar_panel(
        axes[0], x, service_m, service_s,
        "(a) Service coverage", "Service rate (%)", selected_index, labels,
        ylim=(50, 105),
        colors=service_colors, hatches=service_hatches,
    )
    bar_panel(
        axes[1], x, eff_m, eff_s,
        "(b) Effective on-time service", "Eff. on-time (%)", selected_index, labels,
        ylim=(50, 105),
        colors=eff_colors, hatches=eff_hatches,
    )
    bar_panel(
        axes[2], x, vmt_m, vmt_s,
        "(c) VMT reduction", "VMT reduction (%)", selected_index, labels,
        ylim=(25, 45),
        colors=vmt_colors, hatches=vmt_hatches,
    )
    bar_panel(
        axes[3], x, co2_m, co2_s,
        r"(d) CO$_2$ reduction", r"CO$_2$ reduction (%)", selected_index, labels,
        ylim=(40, 52),
        colors=co2_colors, hatches=co2_hatches,
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
        f"\n  {'Condition':<15}  {'Runs':>4}  {'Served%':>8}  {'EffOT%':>8}  "
        f"{'Late':>6}  {'VMT red%':>9}  {'CO2 red%':>9}  {'Pax/trip':>8}"
    )
    print(f"  {'-' * 86}")
    for _, r in df.iterrows():
        tag = " <- selected" if r["label"] == "fixed_20min" else ""
        print(
            f"  {r['label']:<15}  {int(r['n_runs']):>4}  "
            f"{r['service_rate_mean']:>7.1f}%  "
            f"{r['effective_on_time_rate_mean']:>7.1f}%  "
            f"{r['late_mean']:>6.1f}  "
            f"{r['vmt_red_mean']:>8.1f}%  "
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
