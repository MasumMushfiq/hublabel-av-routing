#!/usr/bin/env python3
"""
plot_time_limit_calibration.py
──────────────────────────────
Aggregates and plots results for the solver time-limit calibration experiment.

Produces:
  fig_time_limit_calibration.pdf   — publication-ready manuscript figure (compact, dual-axis)
  fig_time_limit_calibration.png   — raster copy (300 dpi)
  fig_time_limit_calibration_extended.pdf   — extended 4-panel analysis figure (with --extended flag)
  time_limit_calibration_summary.csv

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_time_limit_calibration.py              # Default: manuscript figure
  python3 experiments/scripts/plot_time_limit_calibration.py --extended   # Include extended 4-panel figure
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from plot_pub_style import setup_pub_style as apply_pub_style
import matplotlib.gridspec as gridspec
from matplotlib.ticker import AutoMinorLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"]  = 42

TIME_LIMITS = [10, 20, 30, 60, 120, 180, 240, 300, 450, 600]
X_LABELS    = ["10", "20", "30", "60", "120", "180", "240", "300", "450", "600"]


def setup_pub_style():
    apply_pub_style()
    return

    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family":       "serif",
        "font.serif":        ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi":        150,
        "savefig.dpi":       300,
        "axes.linewidth":    1.2,
        "grid.alpha":        0.35,
        "grid.linewidth":    0.8,
        "font.size":         10,
        "axes.labelsize":    11,
        "axes.titlesize":    12,
        "legend.fontsize":   9,
        "xtick.labelsize":   8.5,
        "ytick.labelsize":   9,
        "pdf.fonttype":      42,
        "ps.fonttype":       42,
    })


def minor_y(ax):
    ax.yaxis.set_minor_locator(AutoMinorLocator())


def savefig(fig, base_path):
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    fig.savefig(base_path + ".pdf", bbox_inches="tight")
    fig.savefig(base_path + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base_path}.pdf")
    print(f"  Saved: {base_path}.png")


def aggregate(results_dir):
    rows = []
    for tl in TIME_LIMITS:
        cond_dir = os.path.join(results_dir, f"tl_{tl}s")
        if not os.path.isdir(cond_dir):
            print(f"  WARNING: missing {cond_dir}")
            continue

        run_metrics = []
        for run_dir in sorted(os.listdir(cond_dir)):
            mpath = os.path.join(cond_dir, run_dir, "metrics.json")
            bpath = os.path.join(cond_dir, run_dir, "baseline.json")
            if not os.path.isfile(mpath):
                continue
            with open(mpath) as f:
                m = json.load(f)
            baseline_vmt = baseline_co2 = 0.0
            if os.path.isfile(bpath):
                with open(bpath) as f:
                    b = json.load(f)
                baseline_vmt = b.get("total_vmt_km", 0.0)
                baseline_co2 = b.get("total_co2_kg", 0.0)

            served  = m.get("served_commuters", 0)
            total   = m.get("total_commuters", 1)
            vmt     = m.get("total_vmt_km", 0.0)
            co2     = m.get("total_co2_kg", 0.0)
            late    = m.get("late_deliveries", 0)
            avg_pax = m.get("avg_passengers_per_trip", 0.0)
            v_used  = m.get("vehicles_used", 1)
            v_trips = m.get("vehicle_trips", 0)

            service_rate = m.get("service_rate", served / total * 100 if total else 0.0)
            effective_on_time = m.get(
                "effective_on_time_service_rate",
                max(0, served - late) / total * 100 if total else 0.0,
            )
            vmt_red = (baseline_vmt - vmt) / baseline_vmt * 100 if baseline_vmt else 0.0
            co2_red = (baseline_co2 - co2) / baseline_co2 * 100 if baseline_co2 else 0.0

            run_metrics.append({
                "service_rate":  service_rate,
                "effective_on_time_service_rate": effective_on_time,
                "vmt_red":       vmt_red,
                "co2_red":       co2_red,
                "late":          late,
                "avg_pax":       avg_pax,
                "vehicles_used": v_used,
                "vehicle_trips": v_trips,
                "empty_vmt_ratio": m.get("empty_vmt_ratio", 0.0) * 100,
                "avg_detour_ratio": m.get("avg_detour_ratio", 0.0),
                "avg_in_vehicle_time_min": m.get("avg_in_vehicle_time_min", 0.0),
            })

        if not run_metrics:
            print(f"  WARNING: no completed runs in {cond_dir}")
            continue

        n    = len(run_metrics)
        keys = list(run_metrics[0].keys())
        arr  = {k: np.array([r[k] for r in run_metrics]) for k in keys}

        row = {"time_limit_s": tl, "n_runs": n}
        for k, vals in arr.items():
            row[f"{k}_mean"] = np.mean(vals)
            row[f"{k}_std"]  = np.std(vals, ddof=1) if n > 1 else float("nan")
            row[f"{k}_min"]  = np.min(vals)
            row[f"{k}_max"]  = np.max(vals)
        rows.append(row)

    return pd.DataFrame(rows)


def convergence_limit(tls, vals, tol=0.01):
    final = vals[-1]
    if final == 0:
        return None
    for i, tl in enumerate(tls):
        if all(abs(vals[j] - final) / abs(final) <= tol
               for j in range(i, len(vals))):
            return int(tl)
    return None


def draw_panel(ax, df, y_mean, y_std, ylabel, title, color,
               hline=None, tol=0.01, ylim=None):
    x     = df["time_limit_s"].to_numpy()
    means = df[y_mean].to_numpy()
    stds  = df[y_std].fillna(0).to_numpy()

    ax.plot(x, means, marker="o", ms=4.5, lw=1.8, color=color, zorder=3)
    ax.fill_between(x, means - stds, means + stds,
                    alpha=0.18, color=color, zorder=2)

    if hline is not None:
        ax.axhline(hline, color="grey", ls="--", lw=0.8, alpha=0.5)

    ax.set_xlabel("Solver time limit (s)")
    ax.set_ylabel(ylabel)
    ax.set_title(title, pad=6)
    ax.set_xticks(x)
    ax.set_xticklabels([str(int(ti)) for ti in x], rotation=45, ha="right", fontsize=8)
    ax.grid(axis="y", ls="--")
    ax.grid(axis="x", ls=":", alpha=0.2)
    minor_y(ax)
    if ylim:
        ax.set_ylim(ylim)

    conv_tl = convergence_limit(x, means, tol=tol)
    if conv_tl is not None:
        ylo, yhi = ax.get_ylim()
        span = yhi - ylo
        ax.axvline(conv_tl, color="#d62728", ls="--", lw=1.1,
                   alpha=0.75, zorder=4)
        ax.text(conv_tl + 15, ylo + 0.80 * span,
                f"{conv_tl} s",
                color="#d62728", fontsize=8, va="center",
                bbox=dict(boxstyle="round,pad=0.18", fc="white",
                          ec="#d62728", alpha=0.85, lw=0.7))


def fig_manuscript_compact(df, out_dir):
    """
    Compact figure for manuscript: Effect of Solver Time Limit on Solution Quality.
    
    Dual-axis plot showing:
    - Left y-axis: Service rate (%)
    - Right y-axis: VMT and CO₂ reduction (%)
    """
    COLORS = {
        "service": "#2196F3",
        "vmt":     "#4CAF50",
        "co2":     "#FF9800",
    }

    fig, ax1 = plt.subplots(figsize=(5.5, 3.5))
    
    x = df["time_limit_s"].to_numpy()
    
    # LEFT AXIS: Service rate
    service_mean = df["service_rate_mean"].to_numpy()
    service_std = df["service_rate_std"].fillna(0).to_numpy()
    
    line1 = ax1.plot(x, service_mean, marker="o", ms=4.5, lw=2.0,
                     color=COLORS["service"], label="Service rate",
                     zorder=3)
    ax1.fill_between(x, service_mean - service_std, service_mean + service_std,
                     alpha=0.15, color=COLORS["service"], zorder=2)
    
    ax1.set_xlabel("Solver time limit (s)", fontsize=11)
    ax1.set_ylabel("Service rate (%)", fontsize=11, color=COLORS["service"])
    ax1.tick_params(axis="y", labelcolor=COLORS["service"])
    ax1.set_ylim(max(0, min(service_mean) - 5), min(101, max(service_mean) + 1))
    ax1.set_xticks(x)
    ax1.set_xticklabels([str(int(ti)) for ti in x], rotation=90, fontsize=9)
    ax1.grid(axis="y", ls="--", alpha=0.3)
    ax1.grid(axis="x", ls=":", alpha=0.15)
    ax1.yaxis.set_minor_locator(AutoMinorLocator())
    
    # Add horizontal line at 100% for service rate
    ax1.axhline(100, color=COLORS["service"], ls="--", lw=0.8, alpha=0.3, zorder=1)
    
    # RIGHT AXIS: VMT and CO₂ reduction
    ax2 = ax1.twinx()
    
    vmt_mean = df["vmt_red_mean"].to_numpy()
    vmt_std = df["vmt_red_std"].fillna(0).to_numpy()
    
    co2_mean = df["co2_red_mean"].to_numpy()
    co2_std = df["co2_red_std"].fillna(0).to_numpy()
    
    line2 = ax2.plot(x, vmt_mean, marker="s", ms=4.0, lw=2.0,
                     color=COLORS["vmt"], label="VMT reduction",
                     zorder=3)
    ax2.fill_between(x, vmt_mean - vmt_std, vmt_mean + vmt_std,
                     alpha=0.15, color=COLORS["vmt"], zorder=2)
    
    line3 = ax2.plot(x, co2_mean, marker="^", ms=4.0, lw=2.0,
                     color=COLORS["co2"], label="CO$_2$ reduction",
                     zorder=3)
    ax2.fill_between(x, co2_mean - co2_std, co2_mean + co2_std,
                     alpha=0.15, color=COLORS["co2"], zorder=2)
    
    ax2.set_ylabel("VMT / CO$_2$ reduction (%)", fontsize=11)
    ax2.yaxis.set_minor_locator(AutoMinorLocator())
    ax2.grid(axis="y", ls="--", alpha=0.1)
    
    # Add horizontal line at 0 for reference
    ax2.axhline(0, color="grey", ls="--", lw=0.8, alpha=0.3, zorder=1)
    
    # Combined legend
    lines = line1 + line2 + line3
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc="lower right", fontsize=9,
              framealpha=0.95, edgecolor="grey", fancybox=False)
    
    plt.tight_layout()
    
    base = os.path.join(out_dir, "fig_time_limit_calibration")
    savefig(fig, base)


def fig_combined(df, out_dir):
    """
    Extended analysis figure (optional, for appendix or detailed analysis).
    """
    COLORS = {
        "service": "#2196F3",
        "vmt":     "#4CAF50",
        "co2":     "#FF9800",
        "pax":     "#9C27B0",
    }

    fig = plt.figure(figsize=(7.1, 5.2))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.68, wspace=0.32)
    axes = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(2)]

    draw_panel(axes[0], df,
               "service_rate_mean", "service_rate_std",
               "Service rate (%)", "(a) Service Rate",
               color=COLORS["service"],
               ylim=(65, 104), tol=0.01)

    draw_panel(axes[1], df,
               "vmt_red_mean", "vmt_red_std",
               "VMT reduction vs private (%)", "(b) VMT Reduction",
               color=COLORS["vmt"],
               hline=0, tol=0.01)

    draw_panel(axes[2], df,
               "co2_red_mean", "co2_red_std",
               r"CO$_2$ reduction vs private (%)",
               r"(c) CO$_2$ Reduction",
               color=COLORS["co2"],
               hline=0, tol=0.01)

    draw_panel(axes[3], df,
               "avg_pax_mean", "avg_pax_std",
               "Avg passengers per trip", "(d) Pooling Efficiency",
               color=COLORS["pax"],
               tol=0.01)

    fig.suptitle(
        "Solver Time-Limit Calibration — Heterogeneous AV First-Mile\n"
        "Melton Station · 1465 Myki Commuters · 224 Seats (Balanced Mix) · Seed average",
        fontsize=11, y=1.02,
    )

    base = os.path.join(out_dir, "fig_time_limit_calibration_extended")
    savefig(fig, base)

def print_summary(df):
    print(
        f"\n  {'TL(s)':>6}  {'Runs':>4}  {'Served%':>8}  "
        f"{'EffOT%':>8}  {'VMT red%':>9}  {'CO2 red%':>9}  "
        f"{'Pax/trip':>8}  {'Late':>6}"
    )
    print(f"  {'-'*77}")

    for _, r in df.iterrows():
        print(
            f"  {int(r['time_limit_s']):>6}  "
            f"{int(r['n_runs']):>4}  "
            f"{r['service_rate_mean']:>7.1f}%  "
            f"{r['effective_on_time_service_rate_mean']:>7.1f}%  "
            f"{r['vmt_red_mean']:>8.1f}%  "
            f"{r['co2_red_mean']:>8.1f}%  "
            f"{r['avg_pax_mean']:>8.2f}  "
            f"{r['late_mean']:>6.1f}"
        )

    x = df["time_limit_s"].to_numpy()
    print(f"\n  Convergence (within 1% of {int(x[-1])} s value):")

    for col, label in [
        ("service_rate_mean", "Service rate  "),
        ("effective_on_time_service_rate_mean", "Eff. on-time  "),
        ("vmt_red_mean", "VMT reduction "),
        ("co2_red_mean", "CO2 reduction "),
        ("avg_pax_mean", "Avg pax/trip  "),
    ]:
        vals = df[col].to_numpy()
        conv = convergence_limit(x, vals, tol=0.01)
        print(
            f"    {label}: {conv} s"
            if conv
            else f"    {label}: not converged within tested range"
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir",
                   default="experiments/results/time_limit_calibration_224seats")
    p.add_argument("--out",
                   default="experiments/results/time_limit_calibration_224seats/plots")
    p.add_argument("--extended", action="store_true",
                   help="Also generate extended 4-panel figure")
    args = p.parse_args()

    setup_pub_style()
    print("Aggregating time limit calibration results...")
    df = aggregate(args.results_dir)

    if df.empty:
        print("ERROR: no data found. Check --results-dir path.")
        return

    csv_path = os.path.join(args.results_dir,
                            "time_limit_calibration_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df)

    print(f"\nGenerating plots -> {args.out}")
    fig_manuscript_compact(df, args.out)
    
    if args.extended:
        fig_combined(df, args.out)
    
    print("\nDone.")


if __name__ == "__main__":
    main()