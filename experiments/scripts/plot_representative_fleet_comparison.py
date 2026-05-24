#!/usr/bin/env python3
"""
plot_representative_fleet_comparison.py
Aggregates and plots the representative fleet comparison experiment.

Notes:
- Hatched bars indicate partial-service fleets. Their efficiency metrics are
    shown for completeness but are not directly comparable to full-service
    fleets. All-scooter is kept as a diagnostic homogeneous baseline and is
    hatched to highlight its partial-service limitation.
"""

import argparse
import json
import os
import textwrap
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from plot_pub_style import setup_pub_style as apply_pub_style
import numpy as np
import pandas as pd

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

FULL_SERVICE_THRESHOLD = 99.9

ORDER = ["balanced", "vmt_oriented", "co2_oriented", "all_moped", "all_car", "all_minibus", "all_scooter"]
DISPLAY = {
    "balanced": "Balanced\nheterogeneous",
    "vmt_oriented": "VMT-oriented\nheterogeneous",
    "co2_oriented": "Emissions-oriented\nheterogeneous",
    "all_moped": "All\nmoped",
    "all_car": "All\ncar",
    "all_minibus": "All\nminibus",
    "all_scooter": "All\nscooter",
}
SHORT = {
    "balanced": "Balanced",
    "vmt_oriented": "VMT-oriented",
    "co2_oriented": "Emissions-oriented",
    "all_moped": "All moped",
    "all_car": "All car",
    "all_minibus": "All minibus",
    "all_scooter": "All scooter",
}
HET = {"balanced", "vmt_oriented", "co2_oriented"}


def setup_style():
    apply_pub_style()
    return

    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "font.size": 15,
        "axes.labelsize": 16,
        "axes.titlesize": 16,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
        "axes.linewidth": 1.1,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.8,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def read_json(path):
    with open(path) as f:
        return json.load(f)


def load_condition(cond_dir):
    runs = []
    cfg_path = Path(cond_dir) / "run_1" / "config.json"
    cfg = read_json(cfg_path) if cfg_path.exists() else {}
    meta = cfg.get("fleet_metadata", {})

    for run_dir in sorted(Path(cond_dir).glob("run_*")):
        mpath = run_dir / "metrics.json"
        bpath = run_dir / "baseline.json"
        if not mpath.exists():
            continue
        m = read_json(mpath)
        b = read_json(bpath) if bpath.exists() else {}
        baseline_vmt = b.get("total_vmt_km", 0.0)
        baseline_co2 = b.get("total_co2_kg", 0.0)
        served = m.get("served_commuters", 0)
        total = m.get("total_commuters", 1)
        late = m.get("late_deliveries", 0)
        eff = m.get("effective_on_time_service_rate")
        if eff is None:
            eff = max(0.0, (served - late) / max(1, total) * 100.0)
        vmt = m.get("total_vmt_km", 0.0)
        co2 = m.get("total_co2_kg", 0.0)
        fuel = m.get("total_fuel_liters", 0.0)
        solo_trips = m.get("solo_trips", 0)
        shared_trips = m.get("shared_trips", 0)
        per_vt = m.get("per_vehicle_type", {})
        runs.append({
            "service_rate": served / max(1, total) * 100.0,
            "effective_on_time_service_rate": eff,
            "late_deliveries": late,
            "vmt_reduction_percent": (baseline_vmt - vmt) / baseline_vmt * 100.0 if baseline_vmt else np.nan,
            "co2_reduction_percent": (baseline_co2 - co2) / baseline_co2 * 100.0 if baseline_co2 else np.nan,
            "avg_passengers_per_trip": m.get("avg_passengers_per_trip", np.nan),
            "empty_vmt_ratio": m.get("empty_vmt_ratio", np.nan) * 100.0 if m.get("empty_vmt_ratio") is not None else np.nan,
            "avg_detour_ratio": m.get("avg_detour_ratio", np.nan),
            "avg_in_vehicle_time_min": m.get("avg_in_vehicle_time_min", np.nan),
            "vehicles_used": m.get("vehicles_used", np.nan),
            "vehicle_trips": m.get("vehicle_trips", np.nan),
            "total_vmt_km": vmt,
            "total_co2_kg": co2,
            "total_fuel_liters": fuel,
            "solo_trips": solo_trips,
            "shared_trips": shared_trips,
            "per_vehicle_type": per_vt,
        })
    if not runs:
        return None

    df = pd.DataFrame(runs)
    out = {"n_runs": len(df), **meta}
    # Aggregate scalar columns (avoid per_vehicle_type for now)
    scalar_cols = [c for c in df.columns if c != "per_vehicle_type"]
    for col in scalar_cols:
        out[f"{col}_mean"] = df[col].mean()
        out[f"{col}_std"] = df[col].std(ddof=1) if len(df) > 1 else np.nan
    
    # Aggregate per-vehicle-type metrics if available
    if any(df["per_vehicle_type"].apply(len) > 0):
        for vtype in ["Scooter", "Moped", "Car", "Minibus"]:
            vt_list = []
            for row in df["per_vehicle_type"]:
                if vtype in row:
                    vt_list.append(row[vtype])
            if vt_list:
                vt_df = pd.DataFrame(vt_list)
                for vcol in vt_df.columns:
                    out[f"{vtype.lower()}_{vcol}_mean"] = vt_df[vcol].mean()
                    out[f"{vtype.lower()}_{vcol}_std"] = vt_df[vcol].std(ddof=1) if len(vt_df) > 1 else np.nan
    
    # Store raw runs for per-vehicle-type CSV generation
    out["_runs_df"] = df
    return out


def aggregate(results_dir):
    rows = []
    for label in ORDER:
        cond_dir = Path(results_dir) / label
        if not cond_dir.exists():
            continue
        data = load_condition(cond_dir)
        if data is None:
            continue
        data["label"] = label
        data["display_label"] = DISPLAY.get(label, label)
        data["short_label"] = SHORT.get(label, label)
        data["is_heterogeneous"] = label in HET
        rows.append(data)
    return pd.DataFrame(rows)


def bar_panel(ax, df, metric, err, ylabel, title, ylim=None, higher_better=True):
    x = np.arange(len(df))
    vals = df[metric].to_numpy(float)
    yerr = df[err].fillna(0).to_numpy(float) if err in df else None
    colors = ["#4C78A8" if h else "#D0D0D0" for h in df["is_heterogeneous"]]
    edges = ["#2F4B7C" if h else "black" for h in df["is_heterogeneous"]]
    bars = ax.bar(x, vals, yerr=yerr, capsize=3, color=colors, edgecolor=edges, linewidth=1.0)
    for i, (bar, svc) in enumerate(zip(bars, df["service_rate_mean"])):
        label = df["label"].iloc[i]
        # Mark partial-service fleets (including all_scooter) with a consistent
        # hatch so they are visually flagged across all panels.
        if svc < FULL_SERVICE_THRESHOLD or label == "all_scooter":
            bar.set_hatch("//")
            bar.set_alpha(0.65)
    ax.set_title(title, loc="left")
    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    # Use short, single-line labels for readability in the manuscript figure.
    ax.set_xticklabels(df["short_label"], rotation=30, ha="right")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    if ylim:
        ax.set_ylim(*ylim)
    if not higher_better:
        ax.invert_yaxis()
    # Improve tick label readability
    ax.tick_params(axis="x", labelsize=11)
    ax.tick_params(axis="y", labelsize=12)


def make_main_figure(df, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2))
    axes = axes.ravel()
    bar_panel(axes[0], df, "effective_on_time_service_rate_mean", "effective_on_time_service_rate_std",
              "Effective on-time service (%)", "(a) Effective on-time service", ylim=(60, 100))
    bar_panel(axes[1], df, "vmt_reduction_percent_mean", "vmt_reduction_percent_std",
              "VMT reduction (%)", "(b) VMT reduction")
    bar_panel(axes[2], df, "co2_reduction_percent_mean", "co2_reduction_percent_std",
              r"CO$_2$ reduction (%)", r"(c) CO$_2$ reduction")
    # Panel (d): Average in-vehicle time (min). Keep avg_passengers_per_trip
    # in summary/table only (pooling intensity) but remove it from the main 2x2.
    bar_panel(axes[3], df, "avg_in_vehicle_time_min_mean", "avg_in_vehicle_time_min_std",
              "Average in-vehicle time (min)", "(d) Average in-vehicle time")

    # Add horizontal zero line for VMT reduction panel to make negative values clear
    axes[1].axhline(0, color="black", linewidth=0.8, linestyle="--")

    for ax in axes:
        ax.tick_params(axis="x", labelsize=11)

    handles = [
        plt.Rectangle((0,0),1,1, facecolor="#4C78A8", edgecolor="#2F4B7C", label="Heterogeneous fleet"),
        plt.Rectangle((0,0),1,1, facecolor="#D0D0D0", edgecolor="black", label="Homogeneous fleet"),
        plt.Rectangle((0,0),1,1, facecolor="#D0D0D0", edgecolor="black", hatch="//", alpha=0.65,
                      label=f"Partial service (<{FULL_SERVICE_THRESHOLD}%)"),
    ]
    # Place a compact legend just above the axes and reduce the gap to the
    # image so it isn't too far from the panels.
    fig.legend(handles=handles, loc="upper center", ncol=3, frameon=False, bbox_to_anchor=(0.5, 1.02))
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    path = Path(out_dir) / "fig_representative_fleet_comparison"
    fig.savefig(str(path) + ".pdf", bbox_inches="tight")
    fig.savefig(str(path) + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {path}.pdf / .png")


def print_summary(df):
    print("\n  ─ Representative Fleet Comparison ─")
    print(f"  {'Fleet':<18} {'Runs':>4} {'Svc%':>7} {'EffOT%':>8} {'Late':>7} {'VMT%':>8} {'CO2%':>8} {'Pax (pooling)':>13} {'Empty%':>7}")
    print("  " + "-" * 86)
    partial_count = 0
    for _, r in df.iterrows():
        is_partial = r["service_rate_mean"] < FULL_SERVICE_THRESHOLD
        warn = " ⚠ partial" if is_partial else ""
        if is_partial:
            partial_count += 1
        print(f"  {r['short_label']:<18} {int(r['n_runs']):>4} "
              f"{r['service_rate_mean']:>6.1f}% {r['effective_on_time_service_rate_mean']:>7.1f}% "
              f"{r['late_deliveries_mean']:>7.1f} {r['vmt_reduction_percent_mean']:>7.1f}% "
              f"{r['co2_reduction_percent_mean']:>7.1f}% {r['avg_passengers_per_trip_mean']:>10.2f} "
              f"{r['empty_vmt_ratio_mean']:>6.1f}%{warn}")
    
    if partial_count > 0:
        print(f"\n  ⚠ WARNING: {partial_count} fleet(s) with service_rate_mean < {FULL_SERVICE_THRESHOLD}%")
        print(f"    Hatched/gray bars indicate partial-service conditions.")
        print(f"    Efficiency metrics (VMT, CO₂ reduction) are NOT directly comparable for these.")
        print(f"    Note: 'Pax (pooling)' reports average passengers per trip as a pooling")
        print(f"          intensity metric and is included in the summary/table only.")
    
    print("\n  Note: VMT/CO₂ reductions are computed against the private-car baseline in baseline.json.")
    print(f"        Partial-service conditions are flagged because these reductions may not be")
    print(f"        directly comparable to full-service fleets.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", default="experiments/results/representative_fleet_comparison")
    parser.add_argument("--out", default="experiments/results/representative_fleet_comparison/plots")
    args = parser.parse_args()
    setup_style()
    print("Aggregating representative fleet comparison results...")
    df = aggregate(args.results_dir)
    if df.empty:
        print("ERROR: no completed results found.")
        return
    # Preserve configured order but only for present labels.
    df["order"] = df["label"].map({label: i for i, label in enumerate(ORDER)})
    df = df.sort_values("order")
    
    # Generate summary CSV with system-level metrics
    csv_path = Path(args.results_dir) / "representative_fleet_comparison_summary.csv"
    df_summary = df.copy()
    df_summary = df_summary.drop(columns=["_runs_df"], errors="ignore")
    df_summary.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")
    
    # Generate per-vehicle-type summary CSV
    vt_rows = []
    for _, row in df.iterrows():
        label = row["label"]
        if "_runs_df" in row and row["_runs_df"] is not None:
            for run_idx, run_row in row["_runs_df"].iterrows():
                per_vt = run_row.get("per_vehicle_type", {})
                for vtype in ["Scooter", "Moped", "Car", "Minibus"]:
                    if vtype in per_vt:
                        vt_data = per_vt[vtype]
                        vt_rows.append({
                            "condition": label,
                            "vehicle_type": vtype,
                            "run": run_idx + 1,
                            "vehicles_used": vt_data.get("vehicles_used", np.nan),
                            "vehicle_trips": vt_data.get("vehicle_trips", np.nan),
                            "served_commuters": vt_data.get("served_commuters", np.nan),
                            "vmt_km": vt_data.get("vmt_km", np.nan),
                            "empty_km": vt_data.get("empty_km", np.nan),
                        })
    if vt_rows:
        vt_df = pd.DataFrame(vt_rows)
        vt_summary_path = Path(args.results_dir) / "representative_fleet_vehicle_type_summary.csv"
        vt_df.to_csv(vt_summary_path, index=False)
        print(f"  Vehicle-type CSV: {vt_summary_path}")
    
    print_summary(df)
    print(f"\nGenerating plots -> {args.out}")
    make_main_figure(df, args.out)
    print("\nDone.")


if __name__ == "__main__":
    main()
