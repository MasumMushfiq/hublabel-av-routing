#!/usr/bin/env python3
"""
plot_buffer_sweep.py
────────────────────
Aggregates and plots results for the pre-departure margin sweep.

Key question: what buffer minimises late arrivals without hurting service rate?

Produces:
  fig_buffer_sweep.pdf / .png   — dual-axis line plot (paper figure)
  buffer_sweep_summary.csv

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_buffer_sweep.py
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from plot_pub_style import setup_pub_style as apply_pub_style
from matplotlib.ticker import AutoMinorLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"]  = 42

BUFFER_VALUES = [0, 1, 2, 3, 4, 5]   # minutes


# ── Style ────────────────────────────────────────────────────────────────────

def setup_pub_style():
    apply_pub_style()
    return

    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family":    "serif",
        "font.serif":     ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi":     150,
        "savefig.dpi":    300,
        "axes.linewidth": 1.2,
        "grid.alpha":     0.3,
        "grid.linewidth": 0.8,
        "font.size":      10,
        "axes.labelsize": 11,
        "axes.titlesize": 12,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "pdf.fonttype":   42,
        "ps.fonttype":    42,
    })


def savefig(fig, base_path):
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    fig.savefig(base_path + ".pdf", bbox_inches="tight")
    fig.savefig(base_path + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base_path}.pdf")
    print(f"  Saved: {base_path}.png")


# ── Aggregation ──────────────────────────────────────────────────────────────

def aggregate(results_dir):
    rows = []
    for buf in BUFFER_VALUES:
        cond_dir = os.path.join(results_dir, f"buf_{buf}min")
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

            served   = m.get("served_commuters", 0)
            total    = m.get("total_commuters", 1)
            vmt      = m.get("total_vmt_km", 0.0)
            co2      = m.get("total_co2_kg", 0.0)
            late     = m.get("late_deliveries", 0)
            avg_pax  = m.get("avg_passengers_per_trip", 0.0)
            v_used   = m.get("vehicles_used", 1)
            v_trips  = m.get("vehicle_trips", 1)

            vmt_red = (baseline_vmt - vmt) / baseline_vmt * 100 if baseline_vmt else 0.0
            co2_red = (baseline_co2 - co2) / baseline_co2 * 100 if baseline_co2 else 0.0
            service_rate = m.get("service_rate", served / total * 100 if total else 0.0)
            effective_on_time = m.get(
                "effective_on_time_service_rate",
                max(0, served - late) / total * 100 if total else 0.0,
            )

            run_metrics.append({
                "service_rate":    service_rate,
                "effective_on_time_service_rate": effective_on_time,
                "late":            late,
                "vmt":             vmt,
                "vmt_red":         vmt_red,
                "co2":             co2,
                "co2_red":         co2_red,
                "avg_pax":         avg_pax,
                "vehicles_used":   v_used,
                "vehicle_trips":   v_trips,
                "utilisation":     v_trips / v_used if v_used else 0.0,
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

        row = {"buffer_min": buf, "n_runs": n}
        for k, vals in arr.items():
            row[f"{k}_mean"] = np.mean(vals)
            row[f"{k}_std"]  = np.std(vals, ddof=1) if n > 1 else float("nan")
        rows.append(row)

    return pd.DataFrame(rows)


# ── Knee detection ────────────────────────────────────────────────────────────

def find_knee(buf_vals, late_means, service_means, late_tol=5.0):
    """
    Return the buffer value where late arrivals first drop within `late_tol`
    of their minimum AND service rate is still within 1 pp of its maximum.
    Falls back to the buffer with minimum late arrivals if no clean knee.
    """
    min_late    = np.min(late_means)
    max_service = np.max(service_means)
    for buf, late, svc in zip(buf_vals, late_means, service_means):
        if late <= min_late + late_tol and svc >= max_service - 1.0:
            return buf
    # fallback
    return buf_vals[np.argmin(late_means)]


# ── Figure ────────────────────────────────────────────────────────────────────

def fig_buffer_sweep(df, out_dir):
    """
    Dual-axis line plot:
      Left  (blue)  : late arrivals (mean ± 1σ)
      Right (green) : service rate  (mean ± 1σ)
    Vertical dashed line at the recommended knee.
    """
    C_LATE = "#2196F3"
    C_SVC  = "#4CAF50"

    x         = df["buffer_min"].to_numpy()
    late_m    = df["late_mean"].to_numpy()
    late_s    = df["late_std"].fillna(0).to_numpy()
    svc_m     = df["service_rate_mean"].to_numpy()
    svc_s     = df["service_rate_std"].fillna(0).to_numpy()

    knee = find_knee(x, late_m, svc_m)

    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax2 = ax1.twinx()

    # Late arrivals — left axis
    ax1.plot(x, late_m, marker="o", ms=5, lw=1.8,
             color=C_LATE, label="Late arrivals", zorder=3)
    ax1.fill_between(x, late_m - late_s, late_m + late_s,
                     alpha=0.18, color=C_LATE)
    ax1.set_xlabel("Pre-departure margin (minutes)")
    ax1.set_ylabel("Late arrivals (count)", color=C_LATE)
    ax1.tick_params(axis="y", colors=C_LATE)
    ax1.set_xticks(x)
    ax1.yaxis.set_minor_locator(AutoMinorLocator())

    # Service rate — right axis
    ax2.plot(x, svc_m, marker="s", ms=5, lw=1.8,
             color=C_SVC, ls="--", label="Service rate", zorder=3)
    ax2.fill_between(x, svc_m - svc_s, svc_m + svc_s,
                     alpha=0.15, color=C_SVC)
    ax2.set_ylabel("Service rate (%)", color=C_SVC)
    ax2.tick_params(axis="y", colors=C_SVC)
    ax2.yaxis.set_minor_locator(AutoMinorLocator())

    # Knee annotation
    ax1.axvline(knee, color="#d62728", ls="--", lw=1.2,
                alpha=0.75, zorder=4)
    ylo, yhi = ax1.get_ylim()
    ax1.text(knee + 0.08, ylo + 0.75 * (yhi - ylo),
             f"Recommended\n{knee} min",
             color="#d62728", fontsize=8.5, va="top",
             bbox=dict(boxstyle="round,pad=0.25", fc="white",
                       ec="#d62728", alpha=0.9, lw=0.8))

    # Grid on left axis only to avoid clutter
    ax1.grid(axis="y", ls="--", alpha=0.4)
    ax1.grid(axis="x", ls=":", alpha=0.25)

    # Combined legend
    lines1, labs1 = ax1.get_legend_handles_labels()
    lines2, labs2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labs1 + labs2,
               frameon=False, fontsize=9, loc="center right")

    ax1.set_title(
        "Pre-Departure Margin Sweep",
        fontsize=10, pad=8,
    )

    fig.tight_layout()
    base = os.path.join(out_dir, "fig_buffer_sweep")
    savefig(fig, base)
    return knee


# ── Console summary ──────────────────────────────────────────────────────────

def print_summary(df):
    print(f"\n  {'Buf(min)':>8}  {'Runs':>4}  {'Served%':>8}  "
          f"{'Late':>6}  {'EffOT%':>8}  {'VMT red%':>9}  "
          f"{'CO2 red%':>9}  {'Pax/trip':>8}")
    print(f"  {'-'*75}")
    for _, r in df.iterrows():
        print(f"  {int(r['buffer_min']):>8}  "
              f"{int(r['n_runs']):>4}  "
              f"{r['service_rate_mean']:>7.1f}%  "
              f"{r['late_mean']:>6.1f}  "
              f"{r['effective_on_time_service_rate_mean']:>7.1f}%  "
              f"{r['vmt_red_mean']:>8.1f}%  "
              f"{r['co2_red_mean']:>8.1f}%  "
              f"{r['avg_pax_mean']:>8.2f}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir",
                   default="experiments/results/buffer_sweep_224seats")
    p.add_argument("--out",
                   default="experiments/results/buffer_sweep_224seats/plots")
    args = p.parse_args()

    setup_pub_style()
    print("Aggregating pre-departure margin sweep results...")
    df = aggregate(args.results_dir)

    if df.empty:
        print("ERROR: no data found. Check --results-dir path.")
        return

    csv_path = os.path.join(args.results_dir, "buffer_sweep_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df)

    print(f"\nGenerating plot -> {args.out}")
    knee = fig_buffer_sweep(df, args.out)
    print(f"\n  Recommended pre-departure margin: {knee} min")
    print("\nDone.")


if __name__ == "__main__":
    main()
