#!/usr/bin/env python3
"""
plot_seed_convergence.py
────────────────────────
Plots seed convergence for PyVRP/HGS at the selected solver time limit (default: 300 s), mirroring Figure 2.1
(VMT convergence) from the confirmation report.

For each metric, shows:
  - Running mean as seeds accumulate (solid line)
  - ±1σ running band (shaded)
  - Final mean (dashed)
  - ±1% tolerance band (grey dotted)
  - Convergence point annotation (first seed where running mean
    stays within ±1% of the final mean for all subsequent seeds)

Produces:
  fig_seed_convergence.pdf   — publication figure (4-panel)
  fig_seed_convergence.png   — 300 dpi raster
    fig_seed_convergence_vmt.pdf — standalone VMT reduction figure
    fig_seed_convergence_vmt.png — standalone VMT reduction figure

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_seed_convergence.py
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
from matplotlib.ticker import AutoMinorLocator, MultipleLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"]  = 42


# ── Style ────────────────────────────────────────────────────────────────────

def setup_pub_style():
    apply_pub_style()


def system_reduction(change_pct, system_total, baseline_total, run_path, metric_label):
    if change_pct is not None:
        return float(change_pct), -float(change_pct)
    if system_total is not None and baseline_total:
        reduction = (float(baseline_total) - float(system_total)) / float(baseline_total) * 100
        return -reduction, reduction
    print(
        f"  WARNING: missing system {metric_label} fields for {run_path}; "
        "setting system reduction to NaN"
    )
    return float("nan"), float("nan")


def savefig(fig, base_path):
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    fig.savefig(base_path + ".pdf", bbox_inches="tight")
    fig.savefig(base_path + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base_path}.pdf")
    print(f"  Saved: {base_path}.png")


# ── Load results ─────────────────────────────────────────────────────────────

def load_series(results_dir):
    """
    Load metrics from run_1 … run_N in seed order.
    Returns a dict of metric_name -> np.array of values (one per seed).
    """
    records = []
    seed = 1
    while True:
        mpath = os.path.join(results_dir, f"run_{seed}", "metrics.json")
        bpath = os.path.join(results_dir, f"run_{seed}", "baseline.json")
        cpath = os.path.join(results_dir, f"run_{seed}", "comparison.json")
        if not os.path.isfile(mpath):
            break
        with open(mpath) as f:
            m = json.load(f)
        c = {}
        if os.path.isfile(cpath):
            with open(cpath) as f:
                c = json.load(f)

        baseline_vmt = baseline_energy = baseline_co2 = 0.0
        if os.path.isfile(bpath):
            with open(bpath) as f:
                b = json.load(f)
            baseline_vmt = b.get("baseline_total_vmt_km", b.get("total_vmt_km", 0.0))
            baseline_energy = b.get(
                "baseline_total_energy_kwh",
                b.get("total_energy_kwh", 0.0),
            )
            baseline_co2 = b.get("baseline_total_co2_kg", b.get("total_co2_kg", 0.0))

        served  = m.get("served_commuters", 0)
        total   = m.get("total_commuters", 1)
        late    = m.get("late_deliveries", 0)
        avg_pax = m.get("avg_passengers_per_trip", 0.0)
        fallback_private_cars = c.get(
            "fallback_private_cars",
            m.get("fallback_private_cars", late + m.get("unserved_commuters", 0)),
        )

        service_rate = c.get(
            "service_rate_pct",
            m.get("service_rate", served / total * 100 if total else 0.0),
        )
        on_time_rate = c.get("on_time_rate_pct", m.get("on_time_rate", service_rate))
        effective_on_time = service_rate

        system_vmt = m.get("system_total_vmt_km")
        system_energy = m.get("system_total_energy_kwh")
        system_co2 = m.get("system_total_co2_kg")

        system_vmt_change_pct = c.get("system_vmt_change_pct", m.get("system_vmt_change_pct"))
        system_energy_change_pct = c.get(
            "system_energy_change_pct",
            m.get("system_energy_change_pct"),
        )
        system_co2_change_pct = c.get("system_co2_change_pct", m.get("system_co2_change_pct"))

        run_path = os.path.join(results_dir, f"run_{seed}")
        system_vmt_change_pct, vmt_red = system_reduction(
            system_vmt_change_pct, system_vmt, baseline_vmt, run_path, "VMT"
        )
        system_energy_change_pct, energy_red = system_reduction(
            system_energy_change_pct, system_energy, baseline_energy, run_path, "energy"
        )
        system_co2_change_pct, co2_red = system_reduction(
            system_co2_change_pct, system_co2, baseline_co2, run_path, "CO2"
        )

        records.append({
            "service_rate": service_rate,
            "on_time_rate": on_time_rate,
            "effective_on_time_service_rate": effective_on_time,
            "system_vmt_change_pct": system_vmt_change_pct,
            "system_energy_change_pct": system_energy_change_pct,
            "system_co2_change_pct": system_co2_change_pct,
            "vmt_red":      vmt_red,
            "energy_red":   energy_red,
            "co2_red":      co2_red,
            "avg_pax":      avg_pax,
            "late":         late,
            "fallback_private_cars": fallback_private_cars,
        })
        seed += 1

    if not records:
        return None, 0

    n = len(records)
    series = {k: np.array([r[k] for r in records]) for k in records[0]}
    print(f"  Loaded {n} seeds from {results_dir}")
    return series, n


# ── Convergence helper ────────────────────────────────────────────────────────

def find_convergence(running_means, final_mean, tol=0.01):
    """
    First index i where the running mean stays within tol of final_mean
    for all j >= i.  Returns (seed_number, index) or (None, None).
    """
    if final_mean == 0:
        return None, None
    for i, rm in enumerate(running_means):
        if all(abs(running_means[j] - final_mean) / abs(final_mean) <= tol
               for j in range(i, len(running_means))):
            return i + 1, i   # seed number is 1-indexed
    return None, None


# ── Panel drawing ─────────────────────────────────────────────────────────────

def draw_convergence_panel(
    ax,
    values,
    ylabel,
    title,
    color,
    tol=0.01,
    line_width=1.8,
    marker_size=None,
    label_size=None,
    title_size=None,
    tick_size=None,
    legend_size=8,
    legend_labels=None,
):
    """
    Mirrors the style of Figure 2.1 in the confirmation report:
      - Running mean (solid)
      - ±1σ running band (shaded)
      - Final mean (dashed)
      - ±1% tolerance band (dotted grey)
      - Convergence point (vertical dotted line + annotation)
    """
    n = len(values)
    seeds = np.arange(1, n + 1)

    # Running mean and std
    running_mean = np.array([np.mean(values[:i+1]) for i in range(n)])
    running_std  = np.array([np.std(values[:i+1], ddof=min(i, 1))
                             for i in range(n)])

    final_mean = running_mean[-1]
    tol_hi = final_mean * (1 + tol)
    tol_lo = final_mean * (1 - tol)

    # ±1σ band
    ax.fill_between(seeds,
                    running_mean - running_std,
                    running_mean + running_std,
                    alpha=0.18, color=color,
                    label=(legend_labels or {}).get("running_sd", r"$\pm1\sigma$ (running)"))

    # Running mean
    ax.plot(seeds, running_mean, color=color, lw=line_width,
            marker="o" if marker_size else None, ms=marker_size,
            label=(legend_labels or {}).get("running_mean", "Running mean"),
            zorder=3)

    # Final mean dashed
    ax.axhline(final_mean, color=color, ls="--", lw=max(1.2, line_width - 0.8),
               alpha=0.7,
               label=(legend_labels or {}).get("final_mean", f"Final mean ({final_mean:.2f})"))

    # ±1% tolerance band
    ax.axhline(tol_hi, color="grey", ls=":", lw=1.0, alpha=0.7)
    ax.axhline(tol_lo, color="grey", ls=":", lw=1.0, alpha=0.7,
               label=(legend_labels or {}).get("tolerance", r"$\pm$1% tolerance"))

    # Convergence annotation
    conv_seed, conv_idx = find_convergence(running_mean, final_mean, tol=tol)
    # if conv_seed is not None:
    #     ax.axvline(conv_seed, color="#d62728", ls=":", lw=1.4,
    #                alpha=0.8, zorder=4,
    #                label=f"Stabilises @ {conv_seed} runs")
    #     ylo, yhi = ax.get_ylim()
    #     # Place label in upper quarter, slightly right of line
    #     ax.text(conv_seed + 0.8,
    #             ylo + 0.82 * (yhi - ylo),
    #             f"Stabilises\n@ {conv_seed} runs",
    #             color="#d62728", fontsize=8, va="top",
    #             bbox=dict(boxstyle="round,pad=0.2", fc="white",
    #                       ec="#d62728", alpha=0.85, lw=0.7))

    ax.set_xlabel("Number of runs", fontsize=label_size)
    ax.set_ylabel(ylabel, fontsize=label_size)
    ax.set_title(title, pad=6, fontsize=title_size)
    if tick_size is not None:
        ax.tick_params(axis="both", labelsize=tick_size)
    ax.set_xlim(1, n)
    ax.xaxis.set_major_locator(MultipleLocator(5))
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.grid(axis="y", ls="--")
    ax.legend(fontsize=legend_size, frameon=False, loc="upper right")


# ── Combined 4-panel figure ───────────────────────────────────────────────────

def fig_combined(series, n, out_dir):
    COLORS = {
        "service_rate": "#2196F3",
        "vmt_red":      "#4CAF50",
        "co2_red":      "#FF9800",
        "avg_pax":      "#9C27B0",
    }

    PANELS = [
        ("vmt_red",      "System VMT reduction vs private (%)",
         "(a) System VMT Reduction"),
        ("service_rate", "Service rate (%)",
         "(b) Service Rate"),
        (r"co2_red",     r"System CO$_2$ reduction vs private (%)",
         r"(c) System CO$_2$ Reduction"),
        ("avg_pax",      "Avg passengers per trip",
         "(d) Pooling Efficiency"),
    ]

    fig = plt.figure(figsize=(7.1, 5.2))
    gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.55, wspace=0.32)
    axes = [fig.add_subplot(gs[r, c]) for r in range(2) for c in range(2)]

    for ax, (key, ylabel, title) in zip(axes, PANELS):
        draw_convergence_panel(
            ax, series[key], ylabel, title,
            color=COLORS[key], tol=0.01
        )

    fig.suptitle(
        "Seed Convergence Analysis — PyVRP / HGS, Selected Time Limit\n"
        "Melton Station · 1465 Myki Commuters · 224 Seats (Balanced Mix)",
        fontsize=11, y=1.02,
    )

    base = os.path.join(out_dir, "fig_seed_convergence")
    savefig(fig, base)


def fig_vmt_reduction(series, n, out_dir):
    """Standalone VMT reduction convergence figure for manuscript reuse."""
    fig, ax = plt.subplots(figsize=(4.2, 3.2))
    draw_convergence_panel(
        ax,
        series["vmt_red"],
        "System VMT reduction (%)",
        "",
        color="#4CAF50",
        tol=0.01,
        line_width=2.3,
        marker_size=5.5,
        label_size=13,
        title_size=14,
        tick_size=11,
        legend_size=10,
        legend_labels={
            "running_sd": r"$\pm$1 SD",
            "running_mean": "Running mean",
            "final_mean": "Final mean",
            "tolerance": r"$\pm$1% band",
        },
    )
    
    # Broaden y-axis range to reduce visual dominance of shaded area
    ylo, yhi = ax.get_ylim()
    y_range = yhi - ylo
    ax.set_ylim(ylo - 1.0 * y_range, yhi + 1.0 * y_range)

    base = os.path.join(out_dir, "fig_seed_convergence_vmt")
    savefig(fig, base)


# ── Console summary ──────────────────────────────────────────────────────────

def print_summary(series, n):
    print(f"\n  Seeds loaded: {n}")
    print(f"\n  {'Metric':<25}  {'Mean':>8}  {'Std':>7}  {'Min':>8}  {'Max':>8}  {'Converges'}") 
    print(f"  {'-'*72}")
    labels = {
        "service_rate": "Service rate (%)",
        "vmt_red":      "System VMT red. (%)",
        "energy_red":   "System kWh red. (%)",
        "co2_red":      "System CO2 red. (%)",
        "avg_pax":      "Avg pax/trip",
        "fallback_private_cars": "Fallback cars",
    }
    for key, label in labels.items():
        vals = series[key]
        running_mean = np.array([np.mean(vals[:i+1]) for i in range(n)])
        final = running_mean[-1]
        conv_seed, _ = find_convergence(running_mean, final, tol=0.01)
        conv_str = f"{conv_seed} runs" if conv_seed else "not converged"
        print(f"  {label:<25}  "
              f"{np.mean(vals):>8.2f}  "
              f"{np.std(vals, ddof=1):>7.3f}  "
              f"{np.min(vals):>8.2f}  "
              f"{np.max(vals):>8.2f}  "
              f"{conv_str}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir",
                   default="experiments/results/seed_convergence_224seats")
    p.add_argument("--out",
                   default="experiments/results/seed_convergence_224seats/plots")
    args = p.parse_args()

    setup_pub_style()
    print("Loading seed convergence results...")
    series, n = load_series(args.results_dir)

    if series is None or n == 0:
        print("ERROR: no data found. Check --results-dir path.")
        return

    print_summary(series, n)

    print(f"\nGenerating plots -> {args.out}")
    fig_vmt_reduction(series, n, args.out)
    fig_combined(series, n, args.out)
    print("\nDone.")


if __name__ == "__main__":
    main()
