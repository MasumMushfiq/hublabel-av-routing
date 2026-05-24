#!/usr/bin/env python3
"""
plot_fleet_composition_grid.py
───────────────────────────────
Aggregates and plots results for the 224-seat fleet composition grid.
Reliability-first framing: effective on-time service rate is the primary
selection criterion, before VMT or CO2 reduction.

Produces:
  Combined figure:
    fig_fleet_composition_grid.pdf/.png     — compact 2×2 overview

  Individual figures:
    fig_fleet_composition_tradeoff.pdf/.png — on-time vs VMT scatter
    fig_fleet_composition_service.pdf/.png  — service & reliability bars
    fig_fleet_composition_vmt_co2.pdf/.png  — VMT vs CO2 scatter

  Data:
    fleet_composition_grid_summary.csv
    top_reliability_first.csv        — svc>=99.9%, on-time>=97%, sorted by on-time
    top_efficiency_full_service.csv  — svc>=99.9%, on-time>=97%, sorted by VMT

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_fleet_composition_grid.py
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
matplotlib.rcParams["ps.fonttype"] = 42

RESULTS_ROOT = "experiments/results/fleet_composition_grid_224seats"
CONFIGS_DIR = "experiments/results/fleet_composition_grid_224seats/configs"

SVC_FULL = 99.9
OT_PRACTICAL = 97.0


def setup_pub_style():
    apply_pub_style()
    return

    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "axes.linewidth": 1.2,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.8,
        # Manuscript-sized typography
        "font.size": 14,
        "axes.labelsize": 16,
        "axes.titlesize": 17,
        "legend.fontsize": 13,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })


def savefig(fig, base_path):
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    fig.savefig(base_path + ".pdf", bbox_inches="tight")
    fig.savefig(base_path + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base_path}.pdf / .png")


# ── Aggregation ──────────────────────────────────────────────────────────────

def load_metadata(configs_dir=None):
    meta_path = os.path.join(configs_dir or CONFIGS_DIR, "composition_metadata.csv")
    if os.path.isfile(meta_path):
        return pd.read_csv(meta_path).set_index("condition")
    return None


def aggregate(results_dir, configs_dir=None):
    meta = load_metadata(configs_dir)
    rows = []
    conditions = sorted(
        d for d in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, d)) and d.startswith("comp_")
    )
    print(f"  Found {len(conditions)} condition directories")
    missing_runs = []

    for cond in conditions:
        cond_dir = os.path.join(results_dir, cond)
        run_metrics = []

        for run_dir in sorted(os.listdir(cond_dir)):
            mpath = os.path.join(cond_dir, run_dir, "metrics.json")
            bpath = os.path.join(cond_dir, run_dir, "baseline.json")
            if not os.path.isfile(mpath):
                continue

            with open(mpath) as f:
                m = json.load(f)

            baseline_vmt = baseline_co2 = baseline_fuel = 0.0
            if os.path.isfile(bpath):
                with open(bpath) as f:
                    b = json.load(f)
                baseline_vmt = b.get("total_vmt_km", 0.0)
                baseline_co2 = b.get("total_co2_kg", 0.0)
                baseline_fuel = b.get("total_fuel_liters", 0.0)

            served = m.get("served_commuters", 0)
            total = m.get("total_commuters", 1)
            vmt = m.get("total_vmt_km", 0.0)
            co2 = m.get("total_co2_kg", 0.0)
            fuel = m.get("total_fuel_liters", 0.0)
            late = m.get("late_deliveries", 0)
            on_time = m.get("on_time_rate", 0.0)
            eff_ot = m.get("effective_on_time_service_rate", on_time)
            avg_pax = m.get("avg_passengers_per_trip", 0.0)
            loaded = m.get("loaded_vmt_km", vmt)
            empty = m.get("empty_vmt_km", 0.0)
            empty_r = m.get("empty_vmt_ratio", 0.0)
            v_used = m.get("vehicles_used", 0)
            v_trips = m.get("vehicle_trips", 0)
            avg_ivt = m.get("avg_in_vehicle_time_min", 0.0)
            max_ivt = m.get("max_in_vehicle_time_min", 0.0)
            avg_det = m.get("avg_detour_ratio", 0.0)
            max_det = m.get("max_detour_ratio", 0.0)
            solo = m.get("solo_trips", 0)
            shared = m.get("shared_trips", 0)
            pooling = shared / (solo + shared) * 100 if (solo + shared) > 0 else 0.0

            vmt_red = (baseline_vmt - vmt) / baseline_vmt * 100 if baseline_vmt else 0.0
            co2_red = (baseline_co2 - co2) / baseline_co2 * 100 if baseline_co2 else 0.0
            fuel_red = (baseline_fuel - fuel) / baseline_fuel * 100 if baseline_fuel else 0.0

            run_metrics.append({
                "service_rate": served / total * 100,
                "effective_on_time_service_rate": eff_ot,
                "on_time_rate": on_time,
                "late_deliveries": late,
                "total_vmt_km": vmt,
                "loaded_vmt_km": loaded,
                "empty_vmt_km": empty,
                "empty_vmt_ratio": empty_r,
                "vmt_reduction_pct": vmt_red,
                "total_co2_kg": co2,
                "co2_reduction_pct": co2_red,
                "total_fuel_liters": fuel,
                "fuel_reduction_pct": fuel_red,
                "avg_passengers_per_trip": avg_pax,
                "pooling_rate": pooling,
                "vehicles_used": v_used,
                "vehicle_trips": v_trips,
                "avg_in_vehicle_time_min": avg_ivt,
                "max_in_vehicle_time_min": max_ivt,
                "avg_detour_ratio": avg_det,
                "max_detour_ratio": max_det,
            })

        if not run_metrics:
            missing_runs.append(cond)
            continue

        n = len(run_metrics)
        keys = list(run_metrics[0].keys())
        arr = {k: np.array([r[k] for r in run_metrics]) for k in keys}
        row = {"condition": cond, "n_runs": n}
        for k, vals in arr.items():
            row[f"{k}_mean"] = np.mean(vals)
            row[f"{k}_std"] = np.std(vals, ddof=1) if n > 1 else float("nan")

        if meta is not None and cond in meta.index:
            for col in meta.columns:
                row[col] = meta.loc[cond, col]

        rows.append(row)

    if missing_runs:
        print(f"  WARNING: {len(missing_runs)} conditions with no runs: {missing_runs}")

    return pd.DataFrame(rows), missing_runs


# ── Label helpers ────────────────────────────────────────────────────────────

def short_label(cond):
    parts = cond.replace("comp_", "").split("_")
    return "/".join(p[0].upper() + p[1:].lstrip("0") or "0" for p in parts)


def get_special_labels(df):
    labels = {}

    for vt, col in [
        ("Scooter", "target_scooter_share"),
        ("Moped", "target_moped_share"),
        ("Car", "target_car_share"),
        ("Minibus", "target_minibus_share"),
    ]:
        mask = df[col] == 100
        if mask.any():
            labels[df[mask]["condition"].iloc[0]] = f"All {vt}"

    bal = df[
        (df["target_scooter_share"] == 25)
        & (df["target_moped_share"] == 25)
        & (df["target_car_share"] == 25)
        & (df["target_minibus_share"] == 25)
    ]
    if not bal.empty:
        labels[bal["condition"].iloc[0]] = "Balanced"

    rel = df[
        (df["service_rate_mean"] >= SVC_FULL)
        & (df["effective_on_time_service_rate_mean"] >= OT_PRACTICAL)
    ]
    if not rel.empty:
        idx = rel["effective_on_time_service_rate_mean"].idxmax()
        cond = df.loc[idx, "condition"]
        labels.setdefault(cond, "Best\nreliability")

    eff = df[
        (df["service_rate_mean"] >= SVC_FULL)
        & (df["effective_on_time_service_rate_mean"] >= OT_PRACTICAL)
    ]
    if not eff.empty:
        idx = eff["vmt_reduction_pct_mean"].idxmax()
        cond = df.loc[idx, "condition"]
        labels.setdefault(cond, "Best VMT\n(on-time≥97%)")

    return labels


# ── Figure helpers ───────────────────────────────────────────────────────────

def _split_service_masks(df):
    full_mask = df["service_rate_mean"].to_numpy() >= SVC_FULL
    return full_mask, ~full_mask


def practical_candidates(df):
    return df[
        (df["service_rate_mean"] >= SVC_FULL)
        & (df["effective_on_time_service_rate_mean"] >= OT_PRACTICAL)
    ].copy()


def full_service_candidates(df):
    return df[df["service_rate_mean"] >= SVC_FULL].copy()


def fig_tradeoff(df, out_dir):
    fig, ax = plt.subplots(figsize=(10, 7))
    x = df["effective_on_time_service_rate_mean"].to_numpy()
    y = df["vmt_reduction_pct_mean"].to_numpy()
    color = df["co2_reduction_pct_mean"].to_numpy()
    size = (df["avg_passengers_per_trip_mean"].to_numpy() * 30) ** 1.4
    full_mask, partial_mask = _split_service_masks(df)

    sc = ax.scatter(
        x[full_mask],
        y[full_mask],
        c=color[full_mask],
        s=size[full_mask] * 1.1,
        cmap="YlOrRd",
        alpha=0.9,
        edgecolors="grey",
        linewidths=0.4,
        zorder=4,
    )
    if partial_mask.any():
        ax.scatter(
            x[partial_mask],
            y[partial_mask],
            color="#777777",
            s=np.clip(size[partial_mask] * 0.6 * 1.05, 10, 250),
            alpha=0.55,
            edgecolors="#444444",
            linewidths=0.6,
            marker="o",
            facecolors="none",
            zorder=3,
            label="Partial service (<99% served)",
        )

    cbar = plt.colorbar(sc, ax=ax, shrink=0.85)
    cbar.set_label(r"$\mathrm{CO_2}$ reduction (%)", fontsize=10)
    cbar.ax.yaxis.set_tick_params(labelsize=12)

    for thresh, ls, label in [
        (OT_PRACTICAL, "-", f"EffOT ≥{OT_PRACTICAL:.0f}%"),
    ]:
        ax.axvline(thresh, color="#d62728", ls=ls, lw=1.1, alpha=0.7, zorder=2, label=label)

    for pax, lbl in [(2, "2 pax/trip"), (4, "4 pax/trip"), (6, "6 pax/trip")]:
        ax.scatter([], [], s=(pax * 30) ** 1.4, c="grey", alpha=0.6,
                   edgecolors="grey", linewidths=0.4, label=lbl)
    ax.legend(fontsize=8, frameon=False, loc="upper left")

    labels = get_special_labels(df)
    used_positions = []
    for cond, lbl in labels.items():
        row = df[df["condition"] == cond]
        if row.empty:
            continue
        xi = row["effective_on_time_service_rate_mean"].iloc[0]
        yi = row["vmt_reduction_pct_mean"].iloc[0]
        dx, dy = 0.3, 1.2
        for px, py in used_positions:
            if abs(xi - px) < 1.5 and abs(yi - py) < 3:
                dy += 2.5
        used_positions.append((xi, yi))
        ax.annotate(
            lbl,
            xy=(xi, yi),
            xytext=(xi + dx, yi + dy),
            fontsize=8.5,
            arrowprops=dict(arrowstyle="-", color="grey", lw=0.7, alpha=0.7),
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="grey", alpha=0.85, lw=0.5),
        )

    ax.set_xlabel("Effective on-time service rate (%)")
    ax.set_ylabel("VMT reduction vs private car (%)")
    ax.set_title("(a) Reliability vs Efficiency Trade-off", fontsize=10.5)
    ax.grid(ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_tradeoff"))


def fig_service_reliability(df, out_dir):
    df_s = df.sort_values("effective_on_time_service_rate_mean", ascending=False)
    x = np.arange(len(df_s))
    w = 0.4
    svc_m = df_s["service_rate_mean"].to_numpy()
    ot_m = df_s["effective_on_time_service_rate_mean"].to_numpy()
    ot_s = df_s["effective_on_time_service_rate_std"].fillna(0).to_numpy()
    xlabs = [c.replace("comp_", "").replace("_", "\n") for c in df_s["condition"]]

    fig, ax = plt.subplots(figsize=(18, 5))
    ax.bar(x - w / 2, svc_m, width=w, color="#2196F3", edgecolor="white", linewidth=0.3,
           alpha=0.85, label="Service rate (%)")
    ax.bar(x + w / 2, ot_m, width=w, yerr=ot_s, capsize=1.5,
           color="#FF9800", edgecolor="white", linewidth=0.3,
           alpha=0.85, label="Effective on-time service rate (%)",
           error_kw={"elinewidth": 0.8})
    ax.axhline(OT_PRACTICAL, color="#d62728", ls="-", lw=0.9, alpha=0.6,
               label=f"EffOT ≥{OT_PRACTICAL:.0f}%")
    ax.set_xticks(x)
    ax.set_xticklabels(xlabs, fontsize=8.5, rotation=90)
    ax.set_ylabel("Rate (%)")
    ax.set_ylim(0, 108)
    ax.set_title(
        "Service Rate and Effective On-Time Rate by Fleet Composition\n"
        "(sorted by effective on-time service rate, descending)",
        fontsize=10,
        pad=6,
    )
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_service"))


def fig_vmt_co2(df, out_dir):
    fig, ax = plt.subplots(figsize=(7, 5.5))
    x = df["vmt_reduction_pct_mean"].to_numpy()
    y = df["co2_reduction_pct_mean"].to_numpy()
    c = df["effective_on_time_service_rate_mean"].to_numpy()
    full_mask, partial_mask = _split_service_masks(df)

    sc = ax.scatter(x[full_mask], y[full_mask], c=c[full_mask], s=55,
                    cmap="RdYlGn", alpha=0.9, edgecolors="grey",
                    linewidths=0.4, zorder=4)
    if partial_mask.any():
        ax.scatter(x[partial_mask], y[partial_mask], color="#777777", s=40,
                   alpha=0.55, edgecolors="#444444", linewidths=0.6,
                   marker="o", facecolors="none", zorder=3)

    cbar = plt.colorbar(sc, ax=ax, shrink=0.85)
    cbar.set_label("Effective on-time service rate (%)", fontsize=10)
    cbar.ax.yaxis.set_tick_params(labelsize=12)
    ax.set_xlabel("VMT reduction vs private car (%)")
    ax.set_ylabel(r"$\mathrm{CO_2}$ reduction vs private car (%)")
    ax.set_title(r"(b) VMT vs CO$_2$ (colour = reliability)", fontsize=10.5, pad=6)
    ax.grid(ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_vmt_co2"))


def fig_combined(df, out_dir):
    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2))
    ax_a, ax_b, ax_c, ax_d = axes.flatten()

    x = df["effective_on_time_service_rate_mean"].to_numpy()
    y = df["vmt_reduction_pct_mean"].to_numpy()
    color = df["co2_reduction_pct_mean"].to_numpy()
    size = (df["avg_passengers_per_trip_mean"].to_numpy() * 30) ** 1.4
    pax = df["avg_passengers_per_trip_mean"].to_numpy()
    full_mask, partial_mask = _split_service_masks(df)

    # (a) Tradeoff
    sc_a = ax_a.scatter(x[full_mask], y[full_mask], c=color[full_mask], s=size[full_mask] * 1.1,
                        cmap="YlOrRd", alpha=0.9, edgecolors="grey",
                        linewidths=0.4, zorder=4)
    if partial_mask.any():
        ax_a.scatter(x[partial_mask], y[partial_mask], color="#777777",
                     s=np.clip(size[partial_mask] * 0.6 * 1.05, 10, 250), alpha=0.55,
                     edgecolors="#444444", linewidths=0.6, marker="o",
                     facecolors="none", zorder=3)
    cbar_a = plt.colorbar(sc_a, ax=ax_a, shrink=0.8)
    cbar_a.set_label(r"CO$_2$ reduction (%)", fontsize=10)
    cbar_a.ax.yaxis.set_tick_params(labelsize=12)
    ax_a.axvline(OT_PRACTICAL, color="#d62728", ls="-", lw=1.0, alpha=0.65)
    ax_a.set_xlabel("Effective on-time service rate (%)")
    ax_a.set_ylabel("VMT reduction (%)")
    ax_a.set_title("(a) Reliability vs Efficiency Trade-off", fontsize=10.5)
    ax_a.grid(ls="--", alpha=0.35)

    balanced = df[df["condition"] == "comp_S25_M25_C25_MB25"]
    if not balanced.empty:
        bx = balanced["effective_on_time_service_rate_mean"].iloc[0]
        by = balanced["vmt_reduction_pct_mean"].iloc[0]
        ax_a.scatter([bx], [by], marker="*", s=220, c="black", zorder=6)
        ax_a.annotate("Balanced",
                      xy=(bx, by), xytext=(bx + 0.5, by + 1.5), fontsize=10,
                      arrowprops=dict(arrowstyle="-", color="black", lw=0.8))

    # (b) VMT vs CO2
    sc_b = ax_b.scatter(df.loc[full_mask, "vmt_reduction_pct_mean"],
                        df.loc[full_mask, "co2_reduction_pct_mean"],
                        c=df.loc[full_mask, "effective_on_time_service_rate_mean"],
                        s=60, cmap="RdYlGn", alpha=0.9,
                        edgecolors="grey", linewidths=0.4, zorder=4)
    if partial_mask.any():
        ax_b.scatter(df.loc[partial_mask, "vmt_reduction_pct_mean"],
                 df.loc[partial_mask, "co2_reduction_pct_mean"],
                 color="#777777", s=40, alpha=0.55,
                     edgecolors="#444444", linewidths=0.6, marker="o",
                     facecolors="none", zorder=3)
    cbar_b = plt.colorbar(sc_b, ax=ax_b, shrink=0.8)
    cbar_b.set_label("On-time rate (%)", fontsize=10)
    cbar_b.ax.yaxis.set_tick_params(labelsize=12)
    ax_b.set_xlabel("VMT reduction (%)")
    ax_b.set_ylabel(r"CO$_2$ reduction (%)")
    ax_b.set_title("(b) VMT vs CO$_2$ (colour = reliability)", fontsize=10.5)
    ax_b.grid(ls="--", alpha=0.35)

    # (c) Avg pax vs VMT
    sc_c = ax_c.scatter(pax[full_mask], y[full_mask], c=color[full_mask], s=66,
                        cmap="YlOrRd", alpha=0.9, edgecolors="grey",
                        linewidths=0.4, zorder=4)
    if partial_mask.any():
        ax_c.scatter(pax[partial_mask], y[partial_mask], color="#777777", s=40,
                     alpha=0.55, edgecolors="#444444", linewidths=0.6,
                     marker="o", facecolors="none", zorder=3)
    cbar_c = plt.colorbar(sc_c, ax=ax_c, shrink=0.8)
    cbar_c.set_label(r"CO$_2$ reduction (%)", fontsize=10)
    cbar_c.ax.yaxis.set_tick_params(labelsize=12)
    ax_c.set_xlabel("Avg passengers per trip")
    ax_c.set_ylabel("VMT reduction (%)")
    ax_c.set_title("(c) Avg pax/trip vs VMT reduction", fontsize=10.5)
    ax_c.grid(ls="--", alpha=0.35)

    # (d) Top practical full-service compositions (horizontal bars)
    full_df = practical_candidates(df)
    if full_df.empty:
        ax_d.text(0.5, 0.5, "No practical full-service compositions\n(svc≥99.9%, EffOT≥97.0%)",
                  ha="center", va="center")
        ax_d.set_axis_off()
    else:
        topn = full_df.sort_values("vmt_reduction_pct_mean", ascending=False).head(5)
        topn = topn.reset_index(drop=True)
        vals = topn["vmt_reduction_pct_mean"].to_numpy()
        labels = [c.replace("comp_", "").replace("_", " ") for c in topn["condition"]]
        y_pos = np.arange(len(vals))[::-1]

        colors = ["#FF9800"] * len(vals)
        edgecolors = ["white"] * len(vals)
        linewidths = [0.8] * len(vals)
        hatches = [None] * len(vals)
        for i, cond in enumerate(topn["condition"]):
            if cond == "comp_S25_M25_C25_MB25":
                colors[i] = "#2E7D32"
                edgecolors[i] = "black"
                linewidths[i] = 1.6
                hatches[i] = "//"

        bars = ax_d.barh(y_pos, vals[::-1], color=colors[::-1], edgecolor=edgecolors[::-1], linewidth=linewidths[::-1])
        for bar, hatch in zip(bars, hatches[::-1]):
            if hatch:
                bar.set_hatch(hatch)

        ax_d.set_yticks(y_pos)
        ax_d.set_yticklabels(labels[::-1], fontsize=9.5)
        ax_d.invert_yaxis()
        ax_d.set_xlabel("VMT reduction (%)", fontsize=10.5)
        ax_d.set_title("(d) Top practical full-service compositions by VMT reduction", fontsize=10.5)
        ax_d.grid(axis="x", ls="--", alpha=0.35)

        # add EffOT labels at end of bars
        effs = topn["effective_on_time_service_rate_mean"].to_numpy()
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax_d.text(width + 0.5, bar.get_y() + bar.get_height() / 2,
                      f"{effs[::-1][i]:.1f}%", va="center", ha="left", fontsize=9.5)

    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_grid"))


# ── Ranking tables ───────────────────────────────────────────────────────────

REPORT_COLS = [
    "condition",
    "target_scooter_share", "target_moped_share",
    "target_car_share", "target_minibus_share",
    "scooter_count", "moped_count", "car_count", "minibus_count",
    "total_fleet_seats", "total_fleet_vehicles",
    "service_rate_mean",
    "effective_on_time_service_rate_mean",
    "late_deliveries_mean",
    "vmt_reduction_pct_mean",
    "co2_reduction_pct_mean",
    "avg_passengers_per_trip_mean",
]


def make_reliability_first_table(df, out_dir):
    rel = practical_candidates(df)
    rel = rel.sort_values(
        ["effective_on_time_service_rate_mean", "late_deliveries_mean", "vmt_reduction_pct_mean", "co2_reduction_pct_mean"],
        ascending=[False, True, False, False],
    )

    existing = [c for c in REPORT_COLS if c in rel.columns]
    out_path = os.path.join(out_dir, "..", "top_reliability_first.csv")
    rel[existing].to_csv(out_path, index=False)
    print(f"  Reliability-first table ({len(rel)} rows): {out_path}")
    return rel


def make_practical_efficiency_table(df, out_dir):
    eff = practical_candidates(df)

    out_path = os.path.join(out_dir, "..", "top_efficiency_full_service.csv")
    eff = eff.sort_values(["vmt_reduction_pct_mean", "co2_reduction_pct_mean"], ascending=False)
    existing = [c for c in REPORT_COLS if c in eff.columns]
    eff[existing].to_csv(out_path, index=False)
    print(f"  Practical-efficiency table ({len(eff)} rows): {out_path}")
    return eff


# ── Console summary ───────────────────────────────────────────────────────────

def _row_summary(df, idx):
    r = df.loc[idx]
    return (
        f"{r['condition']:<35}  "
        f"on-time={r['effective_on_time_service_rate_mean']:.1f}%  "
        f"VMT red={r['vmt_reduction_pct_mean']:.1f}%  "
        f"late={r['late_deliveries_mean']:.1f}"
    )


def print_summary(df, missing):
    print(f"\n  Completed conditions : {len(df)}")
    print(f"  Missing conditions   : {len(missing)}")
    if missing:
        for m in missing:
            print(f"    {m}")

    partial = df[df["service_rate_mean"] < 99.0]
    if not partial.empty:
        print(f"\n  WARNING: {len(partial)} composition(s) appear to provide partial service (service_rate_mean < {SVC_FULL}%).")
        print("  These points are plotted in gray and should be treated cautiously when comparing efficiency metrics.")

    practical = practical_candidates(df)
    full_service = full_service_candidates(df)

    print(f"\n  Practical full-service candidates (service >= {SVC_FULL}%, EffOT >= {OT_PRACTICAL}%)")
    if practical.empty:
        print("  No practical full-service candidates found.")
    else:
        top_vmt = practical.sort_values("vmt_reduction_pct_mean", ascending=False).head(5)
        print("  Top 5 by VMT reduction:")
        for _, row in top_vmt.iterrows():
            print(f"    {row['condition']:<35} VMT={row['vmt_reduction_pct_mean']:.1f}%  EffOT={row['effective_on_time_service_rate_mean']:.1f}%  service={row['service_rate_mean']:.1f}%")

    if not full_service.empty:
        top_eff = full_service.sort_values("effective_on_time_service_rate_mean", ascending=False).head(5)
        print("  Top 5 by EffOT among full-service candidates:")
        for _, row in top_eff.iterrows():
            print(f"    {row['condition']:<35} EffOT={row['effective_on_time_service_rate_mean']:.1f}%  VMT={row['vmt_reduction_pct_mean']:.1f}%  service={row['service_rate_mean']:.1f}%")

    bal = df[df["condition"] == "comp_S25_M25_C25_MB25"]
    if not bal.empty:
        row = bal.iloc[0]
        print("\n  Balanced reference (comp_S25_M25_C25_MB25):")
        print(f"    service={row['service_rate_mean']:.1f}%  EffOT={row['effective_on_time_service_rate_mean']:.1f}%  VMT={row['vmt_reduction_pct_mean']:.1f}%  CO2={row['co2_reduction_pct_mean']:.1f}%  pax/trip={row['avg_passengers_per_trip_mean']:.2f}")

    print("\n  ── Homogeneous fleet baselines ────────────────────────────")
    for vt, col in [("Scooter", "target_scooter_share"),
                    ("Moped", "target_moped_share"),
                    ("Car", "target_car_share"),
                    ("Minibus", "target_minibus_share")]:
        mask = df[col] == 100
        if mask.any():
            idx = df[mask].index[0]
            print(f"  All {vt:<8}: {_row_summary(df, idx)}")

    print("\n  ── Interpretation ─────────────────────────────────────────")
    print("  Reliability comes first: the AV service is a feeder to public")
    print("  transport. Missing the train is a major service failure.")
    print("  VMT and CO2 reductions are secondary benefits among fleets")
    print(f"  that provide dependable station access (EffOT >= {OT_PRACTICAL}%).")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default=RESULTS_ROOT)
    p.add_argument("--configs-dir", default=CONFIGS_DIR)
    p.add_argument("--out", default=os.path.join(RESULTS_ROOT, "plots"))
    args = p.parse_args()

    setup_pub_style()
    print("Aggregating fleet composition grid results...")
    df, missing = aggregate(args.results_dir, args.configs_dir)

    if df.empty:
        print("ERROR: no data found. Check --results-dir path.")
        return

    csv_path = os.path.join(args.results_dir, "fleet_composition_grid_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df, missing)

    print(f"\nGenerating plots -> {args.out}")
    fig_combined(df, args.out)
    fig_tradeoff(df, args.out)
    fig_service_reliability(df, args.out)
    fig_vmt_co2(df, args.out)

    make_reliability_first_table(df, args.out)
    make_practical_efficiency_table(df, args.out)

    print("\nDone — 1 combined + 3 individual figures + 2 ranking tables.")


if __name__ == "__main__":
    main()
