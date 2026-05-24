#!/usr/bin/env python3
"""
plot_penalty_fleet_interaction.py
──────────────────────────────────
Aggregates and plots the penalty mode × fleet scale grid.

Produces:
  fig_penalty_fleet_interaction.pdf/.png        — combined 3-panel figure
  fig_penalty_fleet_effective_service.pdf/.png  — effective on-time service only
  fig_penalty_fleet_vmt.pdf/.png                — VMT reduction only
  fig_penalty_fleet_pooling.pdf/.png            — pooling efficiency only
  penalty_fleet_interaction_summary.csv

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_penalty_fleet_interaction.py
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

MODES  = ["none", "multiplicative"]
SCALES = ["x0.90", "x1.00", "x1.10", "x1.25"]
SCALE_SEATS = {"x0.90": 200, "x1.00": 224, "x1.10": 247, "x1.25": 280}
SCALE_VEHS  = {"x0.90": 94,  "x1.00": 105, "x1.10": 115, "x1.25": 131}
X_VALS      = [0.90, 1.00, 1.10, 1.25]
FULL_SERVICE_THRESHOLD = 99.9

MODE_COLORS = {
    "multiplicative": "#2196F3",
    "none":           "#FF9800",
}
MODE_LABELS = {
    "multiplicative": "Multiplicative penalty",
    "none":           "No penalty",
}

XLABS = [f"×{v:.2f}\n({SCALE_SEATS[s]} seats)" for v, s in zip(X_VALS, SCALES)]


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


# ── Aggregation ───────────────────────────────────────────────────────────────

def load_cell(cond_dir):
    if not os.path.isdir(cond_dir):
        return None
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

        vmt_red = (baseline_vmt - vmt) / baseline_vmt * 100 if baseline_vmt else 0.0
        co2_red = (baseline_co2 - co2) / baseline_co2 * 100 if baseline_co2 else 0.0

        # Effective on-time service: prefer simulator field, else compute fallback
        eff_ot = m.get("effective_on_time_service_rate")
        if eff_ot is None:
            eff_ot = max(0.0, (served - late) / max(1, total) * 100.0)

        run_metrics.append({
            "service_rate": served / total * 100,
            "effective_on_time_service_rate": eff_ot,
            "late":         late,
            "vmt_red":      vmt_red,
            "co2_red":      co2_red,
            "avg_pax":      avg_pax,
        })

    if not run_metrics:
        return None

    n    = len(run_metrics)
    keys = list(run_metrics[0].keys())
    arr  = {k: np.array([r[k] for r in run_metrics]) for k in keys}
    result = {"n_runs": n}
    for k, vals in arr.items():
        result[f"{k}_mean"] = np.mean(vals)
        result[f"{k}_std"]  = np.std(vals, ddof=1) if n > 1 else float("nan")
    return result


def aggregate(results_dir):
    rows = []
    for mode in MODES:
        for scale in SCALES:
            label    = f"{mode}_{scale}"
            cond_dir = os.path.join(results_dir, label)
            data     = load_cell(cond_dir)
            if data is None:
                print(f"  WARNING: missing {label}")
                continue
            data["mode"]     = mode
            data["scale"]    = scale
            data["seats"]    = SCALE_SEATS[scale]
            data["vehicles"] = SCALE_VEHS[scale]
            rows.append(data)
            print(f"  {label:<25}: {data['n_runs']:>2} runs  "
                  f"served={data['service_rate_mean']:.1f}%  "
                  f"effectiveOT={data.get('effective_on_time_service_rate_mean', 0.0):.1f}%  "
                  f"late={data['late_mean']:.1f}  "
                  f"vmt_red={data['vmt_red_mean']:.1f}%  "
                  f"pax/trip={data['avg_pax_mean']:.2f}")
    return pd.DataFrame(rows)


# ── Core panel drawing ────────────────────────────────────────────────────────

def draw_panel(ax, df, y_mean, y_std, ylabel, title,
               legend=False, hline=None):
    x = np.array(X_VALS)
    for mode in MODES:
        sub   = df[df["mode"] == mode].set_index("scale").reindex(SCALES)
        means = sub[y_mean].to_numpy().astype(float)
        stds  = sub[y_std].fillna(0).to_numpy().astype(float)
        svc   = sub["service_rate_mean"].to_numpy().astype(float)
        color = MODE_COLORS[mode]

        # Line connecting means
        ax.plot(x, means, marker=None, lw=1.6, color=color, zorder=2)

        # Per-point markers -- gray/hatch for partial-service points
        for xi, mu, si, sv in zip(x, means, stds, svc):
            if sv < FULL_SERVICE_THRESHOLD:
                mcolor = "#d0d0d0"
                mec = "black"
            else:
                mcolor = color
                mec = color
            ax.errorbar([xi], [mu], yerr=[si], fmt="o", ms=6,
                        color=mcolor, markeredgecolor=mec, capsize=3, zorder=3,
                        label=MODE_LABELS[mode] if xi == x[0] else "")

    if hline is not None:
        ax.axhline(hline, color="grey", ls="--", lw=0.8, alpha=0.5)

    ax.set_xlabel("Fleet scale")
    ax.set_ylabel(ylabel)
    ax.set_title(title, pad=6)
    ax.set_xticks(x)
    ax.set_xticklabels(XLABS, fontsize=9)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.grid(axis="x", ls=":", alpha=0.2)
    if legend:
        ax.legend(fontsize=9, frameon=False, loc="best")


SUPTITLE = (
    "Distance-Band Penalty Ablation Across Fleet Scales (224-seat baseline)\n"
    "Melton Station · 1465 Myki Commuters · 15 Seeds"
)

PANELS = [
    ("effective_on_time_service_rate_mean", "effective_on_time_service_rate_std", "Effective on-time service (%)", "(a) Effective service"),
    ("vmt_red_mean", "vmt_red_std", "VMT reduction vs private (%)", "(b) VMT reduction"),
    ("avg_pax_mean", "avg_pax_std", "Avg passengers per trip", "(c) Avg pax / trip"),
]


# ── Combined 3-panel figure ───────────────────────────────────────────────────

def fig_combined(df, out_dir):
    fig = plt.figure(figsize=(14, 5))
    gs  = gridspec.GridSpec(1, 3, figure=fig, wspace=0.38)
    for col, (y_mean, y_std, ylabel, title) in enumerate(PANELS):
        ax = fig.add_subplot(gs[0, col])
        draw_panel(ax, df, y_mean, y_std, ylabel, title,
                   legend=(col == 0))
    fig.suptitle(SUPTITLE, fontsize=11, y=1.02)
    savefig(fig, os.path.join(out_dir, "fig_penalty_fleet_interaction"))


# ── Individual panel figures ──────────────────────────────────────────────────

INDIVIDUAL = [
    ("effective_on_time_service_rate_mean", "effective_on_time_service_rate_std", "Effective on-time service (%)",
     "Effective on-time service — Penalty Ablation (224-seat baseline)",
     "fig_penalty_fleet_effective_service"),
    ("vmt_red_mean", "vmt_red_std", "VMT reduction vs private (%)",
     "VMT reduction — Penalty Ablation (224-seat baseline)",
     "fig_penalty_fleet_vmt"),
    ("avg_pax_mean", "avg_pax_std", "Avg passengers per trip",
     "Avg passengers per trip — Penalty Ablation (224-seat baseline)",
     "fig_penalty_fleet_pooling"),
]


def fig_individual(df, out_dir):
    for y_mean, y_std, ylabel, title, fname in INDIVIDUAL:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        draw_panel(ax, df, y_mean, y_std, ylabel, title, legend=True)
        fig.tight_layout()
        savefig(fig, os.path.join(out_dir, fname))


# ── Console summary ───────────────────────────────────────────────────────────

def print_summary(df):
    print(f"\n  {'Condition':<25}  {'Runs':>4}  {'Served%':>7}  {'EffOT%':>7}  {'Late':>6}  {'VMT red%':>9}  {'CO2 red%':>9}  {'Pax/trip':>8}")
    print(f"  {'-'*100}")
    for mode in MODES:
        for scale in SCALES:
            r = df[(df["mode"] == mode) & (df["scale"] == scale)]
            name = mode + '_' + scale
            if r.empty:
                print(f"  {name:<25}  (missing)")
                continue
            r = r.iloc[0]
            tag = "  ← reference" if scale == "x1.00" else ""
            print(f"  {name:<25}  "
                  f"{int(r['n_runs']):>4}  "
                  f"{r['service_rate_mean']:>7.1f}%  "
                  f"{r.get('effective_on_time_service_rate_mean', 0.0):>7.1f}%  "
                  f"{r['late_mean']:>6.1f}  "
                  f"{r['vmt_red_mean']:>8.1f}%  "
                  f"{r['co2_red_mean']:>8.1f}%  "
                  f"{r['avg_pax_mean']:>8.2f}"
                  f"{tag}")
            if r['service_rate_mean'] < FULL_SERVICE_THRESHOLD:
                print(f"    WARNING: {name} has partial service (<{FULL_SERVICE_THRESHOLD}%). VMT/CO2 reductions not directly comparable.")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir",
                   default="experiments/results/penalty_fleet_interaction_224seats")
    p.add_argument("--out",
                   default="experiments/results/penalty_fleet_interaction_224seats/plots")
    args = p.parse_args()

    setup_pub_style()
    print("Aggregating penalty × fleet interaction results...")
    df = aggregate(args.results_dir)

    if df.empty:
        print("ERROR: no data found.")
        return

    csv_path = os.path.join(args.results_dir,
                            "penalty_fleet_interaction_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df)

    print(f"\nGenerating plots -> {args.out}")
    fig_combined(df, args.out)
    fig_individual(df, args.out)
    print("\nDone — 4 figures (1 combined + 3 individual).")


if __name__ == "__main__":
    main()