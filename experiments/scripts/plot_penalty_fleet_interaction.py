#!/usr/bin/env python3
"""
plot_penalty_fleet_interaction.py
──────────────────────────────────
Aggregates and plots the penalty mode × fleet scale grid.

Produces:
  fig_penalty_fleet_interaction.pdf/.png        — combined 3-panel figure
  fig_penalty_fleet_service_rate.pdf/.png       — service rate only
  fig_penalty_fleet_vmt.pdf/.png                — system VMT reduction only
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


# ── Aggregation ───────────────────────────────────────────────────────────────

def load_cell(cond_dir):
    if not os.path.isdir(cond_dir):
        return None
    run_metrics = []
    for run_dir in sorted(os.listdir(cond_dir)):
        mpath = os.path.join(cond_dir, run_dir, "metrics.json")
        bpath = os.path.join(cond_dir, run_dir, "baseline.json")
        cpath = os.path.join(cond_dir, run_dir, "comparison.json")
        if not os.path.isfile(mpath):
            continue
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
        effective_service = service_rate

        system_vmt = m.get("system_total_vmt_km")
        system_energy = m.get("system_total_energy_kwh")
        system_co2 = m.get("system_total_co2_kg")
        system_vmt_change_pct = c.get("system_vmt_change_pct", m.get("system_vmt_change_pct"))
        system_energy_change_pct = c.get(
            "system_energy_change_pct",
            m.get("system_energy_change_pct"),
        )
        system_co2_change_pct = c.get("system_co2_change_pct", m.get("system_co2_change_pct"))

        run_path = os.path.join(cond_dir, run_dir)
        system_vmt_change_pct, vmt_red = system_reduction(
            system_vmt_change_pct, system_vmt, baseline_vmt, run_path, "VMT"
        )
        system_energy_change_pct, energy_red = system_reduction(
            system_energy_change_pct, system_energy, baseline_energy, run_path, "energy"
        )
        system_co2_change_pct, co2_red = system_reduction(
            system_co2_change_pct, system_co2, baseline_co2, run_path, "CO2"
        )

        run_metrics.append({
            "service_rate": service_rate,
            "on_time_rate": on_time_rate,
            "effective_on_time_service_rate": effective_service,
            "late":         late,
            "fallback_private_cars": fallback_private_cars,
            "system_vmt_change_pct": system_vmt_change_pct,
            "system_energy_change_pct": system_energy_change_pct,
            "system_co2_change_pct": system_co2_change_pct,
            "vmt_red":      vmt_red,
            "energy_red":   energy_red,
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
                  f"service={data['service_rate_mean']:.1f}%  "
                  f"fallback={data['fallback_private_cars_mean']:.1f}  "
                  f"system_vmt_red={data['vmt_red_mean']:.1f}%  "
                  f"system_co2_red={data['co2_red_mean']:.1f}%  "
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
    ("service_rate_mean", "service_rate_std", "Service rate (%)", "(a) Service rate"),
    ("vmt_red_mean", "vmt_red_std", "System VMT reduction vs private (%)", "(b) System VMT reduction"),
    ("co2_red_mean", "co2_red_std", r"System CO$_2$ reduction vs private (%)", r"(c) System CO$_2$ reduction"),
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
    ("service_rate_mean", "service_rate_std", "Service rate (%)",
     "Service rate — Penalty Ablation (224-seat baseline)",
     "fig_penalty_fleet_service_rate"),
    ("vmt_red_mean", "vmt_red_std", "System VMT reduction vs private (%)",
     "System VMT reduction — Penalty Ablation (224-seat baseline)",
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
    print(f"\n  {'Condition':<25}  {'Runs':>4}  {'Service%':>9}  {'Fallback':>8}  {'Sys VMT%':>9}  {'Sys kWh%':>9}  {'Sys CO2%':>9}  {'Pax/trip':>8}")
    print(f"  {'-'*112}")
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
                  f"{r['service_rate_mean']:>8.1f}%  "
                  f"{r['fallback_private_cars_mean']:>8.1f}  "
                  f"{r['vmt_red_mean']:>8.1f}%  "
                  f"{r['energy_red_mean']:>8.1f}%  "
                  f"{r['co2_red_mean']:>8.1f}%  "
                  f"{r['avg_pax_mean']:>8.2f}"
                  f"{tag}")
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
