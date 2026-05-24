#!/usr/bin/env python3
"""
analyze_balanced_fleet_distance_bands.py
─────────────────────────────────────────
Post-processing analysis of the balanced 25/25/25/25 fleet composition.

Condition: comp_s025_m025_c025_b025
           50 Scooter / 27 Moped / 14 Car / 5 Minibus = 200 seats

Groups commuters by direct home-to-station distance band and analyses
service quality, vehicle-type assignment, and late arrivals per band.

Outputs (all under experiments/results/analysis/balanced_fleet_distance_bands):
  distance_band_analysis.csv
  plots/fig_balanced_reliability_by_distance.pdf/.png
  plots/fig_balanced_vehicle_assignment_by_distance.pdf/.png
  plots/fig_balanced_late_by_vehicle_distance.pdf/.png

Usage (from hub_label/ root):
  python3 experiments/scripts/analyze_balanced_fleet_distance_bands.py
"""

import os
import json
import argparse
import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.ticker import AutoMinorLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"]  = 42

CONDITION    = "comp_s025_m025_c025_b025"
RESULTS_ROOT = "experiments/results/fleet_composition_grid_200seats"
COND_DIR     = os.path.join(RESULTS_ROOT, CONDITION)
ANALYSIS_DIR  = os.path.join("experiments/results/analysis", "balanced_fleet_distance_bands")

# Distance bands in km (right-open except last)
BANDS      = [(0, 1), (1, 2), (2, 4), (4, 6), (6, None)]
BAND_LABELS = ["0–1 km", "1–2 km", "2–4 km", "4–6 km", "6+ km"]

VEHICLE_TYPES = ["Scooter", "Moped", "Car", "Minibus"]
VT_COLORS = {
    "Scooter": "#64B5F6",
    "Moped":   "#81C784",
    "Car":     "#FFB74D",
    "Minibus": "#E57373",
}


def setup_pub_style():
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
    print(f"  Saved: {base_path}.pdf / .png")


def band_index(dist_km):
    for i, (lo, hi) in enumerate(BANDS):
        if hi is None or dist_km < hi:
            return i
    return len(BANDS) - 1


# ── Per-run analysis ──────────────────────────────────────────────────────────

def analyse_run(run_dir):
    """
    Returns a list of per-commuter dicts with band and vehicle-type info,
    or None if the run is incomplete.
    """
    asgn_path = os.path.join(run_dir, "assignments.csv")
    if not os.path.isfile(asgn_path):
        return None

    df = pd.read_csv(asgn_path)

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Distance: direct_station_dist_mm → km
    dist_col = None
    for candidate in ["direct_station_dist_mm", "direct_dist_mm",
                      "direct_distance_mm"]:
        if candidate in df.columns:
            dist_col = candidate
            break
    if dist_col is None:
        print(f"  WARNING: no distance column in {asgn_path}")
        return None

    df["dist_km"] = df[dist_col] / 1_000_000.0
    df["band_idx"] = df["dist_km"].apply(band_index)
    df["band"]     = df["band_idx"].apply(lambda i: BAND_LABELS[i])

    # Vehicle type
    vt_col = None
    for candidate in ["av_type", "vehicle_type", "vt"]:
        if candidate in df.columns:
            vt_col = candidate
            break
    if vt_col is None:
        print(f"  WARNING: no vehicle-type column in {asgn_path}")
        return None
    df["vt"] = df[vt_col]

    # Status
    status_col = "status" if "status" in df.columns else None
    if status_col:
        df["served"] = df[status_col].str.upper() == "ASSIGNED"
    else:
        df["served"] = True   # assume all rows are served

    # Late
    late_col = None
    for candidate in ["arrived_late", "late"]:
        if candidate in df.columns:
            late_col = candidate
            break
    if late_col:
        df["is_late"] = df[late_col].astype(str).str.upper().isin(
            ["YES", "TRUE", "1"])
    else:
        df["is_late"] = False

    # Delay in seconds
    delay_col = None
    for candidate in ["delay_sec", "delay_seconds", "delay"]:
        if candidate in df.columns:
            delay_col = candidate
            break
    if delay_col:
        df["delay_sec"] = pd.to_numeric(df[delay_col], errors="coerce").fillna(0)
    else:
        df["delay_sec"] = 0.0

    # In-vehicle time (minutes) — may not be in assignments.csv
    ivt_col = None
    for candidate in ["in_vehicle_time_min", "ivt_min", "travel_time_min"]:
        if candidate in df.columns:
            ivt_col = candidate
            break
    df["ivt_min"] = pd.to_numeric(
        df[ivt_col], errors="coerce") if ivt_col else np.nan

    # Detour ratio
    det_col = None
    for candidate in ["detour_ratio", "detour"]:
        if candidate in df.columns:
            det_col = candidate
            break
    df["detour_ratio"] = pd.to_numeric(
        df[det_col], errors="coerce") if det_col else np.nan

    return df


def summarise_run(df):
    """
    Aggregates a single run's per-commuter dataframe into per-band metrics.
    Returns a dict keyed by band label.
    """
    result = {}
    for bi, band in enumerate(BAND_LABELS):
        sub = df[df["band_idx"] == bi]
        n_total  = len(sub)
        n_served = sub["served"].sum()
        n_ontime = (sub["served"] & ~sub["is_late"]).sum()
        n_late   = (sub["served"] &  sub["is_late"]).sum()

        late_sub = sub[sub["served"] & sub["is_late"]]
        avg_delay = late_sub["delay_sec"].mean() / 60.0 \
            if len(late_sub) > 0 else 0.0

        avg_dist  = sub["dist_km"].mean() if n_total > 0 else 0.0
        avg_ivt   = sub[sub["served"]]["ivt_min"].mean()   \
            if sub["served"].any() else np.nan
        avg_det   = sub[sub["served"]]["detour_ratio"].mean() \
            if sub["served"].any() else np.nan

        row = {
            "n_total":          n_total,
            "n_served":         n_served,
            "service_rate":     n_served / n_total * 100 if n_total else 0,
            "n_ontime":         n_ontime,
            "eff_ontime_rate":  n_ontime / n_total * 100 if n_total else 0,
            "n_late":           n_late,
            "avg_delay_min":    avg_delay,
            "avg_dist_km":      avg_dist,
            "avg_ivt_min":      avg_ivt,
            "avg_detour_ratio": avg_det,
        }
        # Vehicle-type breakdown
        served_sub = sub[sub["served"]]
        for vt in VEHICLE_TYPES:
            vt_sub      = served_sub[served_sub["vt"] == vt]
            n_vt        = len(vt_sub)
            n_late_vt   = vt_sub["is_late"].sum()
            row[f"n_{vt}"]      = n_vt
            row[f"n_late_{vt}"] = n_late_vt
            row[f"pct_{vt}"]    = n_vt / n_served * 100 if n_served else 0

        result[band] = row
    return result


# ── Aggregation across seeds ──────────────────────────────────────────────────

def aggregate_all_runs(cond_dir):
    run_dirs = sorted([
        os.path.join(cond_dir, d)
        for d in os.listdir(cond_dir)
        if os.path.isdir(os.path.join(cond_dir, d))
        and d.startswith("run_")
    ])

    print(f"  Found {len(run_dirs)} run directories")
    all_band_data = {band: [] for band in BAND_LABELS}
    n_loaded = 0

    for run_dir in run_dirs:
        df = analyse_run(run_dir)
        if df is None:
            print(f"  Skipping {run_dir} (incomplete)")
            continue
        summary = summarise_run(df)
        for band, metrics in summary.items():
            all_band_data[band].append(metrics)
        n_loaded += 1

    print(f"  Successfully analysed {n_loaded} runs")

    # Build aggregated DataFrame
    rows = []
    for bi, band in enumerate(BAND_LABELS):
        records = all_band_data[band]
        if not records:
            continue
        keys = list(records[0].keys())
        n    = len(records)
        row  = {
            "band":       band,
            "band_idx":   bi,
            "lo_km":      BANDS[bi][0],
            "hi_km":      BANDS[bi][1] if BANDS[bi][1] else 999,
            "n_seeds":    n,
        }
        for k in keys:
            raw = []
            for r in records:
                v = r[k]
                try:
                    fv = float(v)
                    if not np.isnan(fv):
                        raw.append(fv)
                except (TypeError, ValueError):
                    pass
            if len(raw) == 0:
                row[f"{k}_mean"] = np.nan
                row[f"{k}_std"]  = np.nan
            else:
                vals = np.array(raw)
                row[f"{k}_mean"] = np.mean(vals)
                row[f"{k}_std"]  = np.std(vals, ddof=1) if len(vals) > 1 else np.nan
        rows.append(row)

    return pd.DataFrame(rows)


# ── Figures ───────────────────────────────────────────────────────────────────

def fig_reliability_by_distance(df, out_dir):
    """
    Bar chart: service rate and effective on-time rate by distance band.
    """
    x    = np.arange(len(df))
    w    = 0.35
    svc  = df["service_rate_mean"].to_numpy()
    ot   = df["eff_ontime_rate_mean"].to_numpy()
    svc_s = df["service_rate_std"].fillna(0).to_numpy()
    ot_s  = df["eff_ontime_rate_std"].fillna(0).to_numpy()

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - w/2, svc, width=w, yerr=svc_s, capsize=3,
           color="#2196F3", edgecolor="white", linewidth=0.4,
           alpha=0.88, label="Service rate (%)",
           error_kw={"elinewidth": 1.0})
    ax.bar(x + w/2, ot, width=w, yerr=ot_s, capsize=3,
           color="#FF9800", edgecolor="white", linewidth=0.4,
           alpha=0.88, label="Effective on-time service rate (%)",
           error_kw={"elinewidth": 1.0})

    ax.axhline(100, color="grey",    ls=":",  lw=0.8, alpha=0.5)
    ax.axhline(98,  color="#d62728", ls="-",  lw=0.9, alpha=0.6,
               label="98% threshold")
    ax.axhline(97,  color="#d62728", ls="--", lw=0.9, alpha=0.5,
               label="97% threshold")

    ax.set_xticks(x)
    ax.set_xticklabels(BAND_LABELS)
    ax.set_xlabel("Direct home-to-station distance band")
    ax.set_ylabel("Rate (%)")
    ax.set_ylim(0, 108)
    ax.set_title(
        "Service and On-Time Reliability by Distance Band\n"
        "Balanced Fleet (50S/27M/14C/5MB, 200 seats) · 15 Seeds",
        pad=6,
    )
    ax.legend(fontsize=8, frameon=False)
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())

    # Annotate n_total per band
    for i, row in df.iterrows():
        n = int(row["n_total_mean"])
        ax.text(i, 2, f"n≈{n}", ha="center", va="bottom",
                fontsize=7, color="grey")

    fig.tight_layout()
    savefig(fig, os.path.join(out_dir,
                              "fig_balanced_reliability_by_distance"))


def fig_vehicle_assignment_by_distance(df, out_dir):
    """
    Stacked bar: served commuter share by vehicle type per distance band.
    """
    x      = np.arange(len(df))
    w      = 0.55
    bottom = np.zeros(len(df))

    fig, ax = plt.subplots(figsize=(9, 5))
    for vt in VEHICLE_TYPES:
        col = f"pct_{vt}_mean"
        if col not in df.columns:
            continue
        vals = df[col].fillna(0).to_numpy()
        ax.bar(x, vals, bottom=bottom, width=w,
               label=vt, color=VT_COLORS[vt],
               edgecolor="white", linewidth=0.4)
        # Label inside bar if large enough
        for i, (v, b) in enumerate(zip(vals, bottom)):
            if v >= 5:
                ax.text(i, b + v / 2, f"{v:.0f}%",
                        ha="center", va="center",
                        fontsize=7, color="white", fontweight="bold")
        bottom += vals

    ax.set_xticks(x)
    ax.set_xticklabels(BAND_LABELS)
    ax.set_xlabel("Direct home-to-station distance band")
    ax.set_ylabel("Share of served commuters (%)")
    ax.set_ylim(0, 108)
    ax.set_title(
        "Vehicle-Type Assignment by Distance Band\n"
        "Balanced Fleet (50S/27M/14C/5MB, 200 seats) · 15 Seeds",
        pad=6,
    )
    ax.legend(title="Vehicle type", fontsize=9,
              title_fontsize=9, frameon=False, loc="upper right")
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir,
                              "fig_balanced_vehicle_assignment_by_distance"))


def fig_late_by_vehicle_distance(df, out_dir):
    """
    Grouped bar chart: late arrivals by vehicle type per distance band.
    """
    x    = np.arange(len(df))
    n_vt = len(VEHICLE_TYPES)
    w    = 0.18
    offsets = np.linspace(-(n_vt - 1) / 2, (n_vt - 1) / 2, n_vt) * w

    fig, ax = plt.subplots(figsize=(10, 5))
    for i, vt in enumerate(VEHICLE_TYPES):
        col = f"n_late_{vt}_mean"
        if col not in df.columns:
            continue
        vals = df[col].fillna(0).to_numpy()
        std_col = f"n_late_{vt}_std"
        stds = df[std_col].fillna(0).to_numpy() if std_col in df.columns \
            else np.zeros_like(vals)
        ax.bar(x + offsets[i], vals, width=w, yerr=stds, capsize=2,
               color=VT_COLORS[vt], edgecolor="white", linewidth=0.4,
               alpha=0.88, label=vt,
               error_kw={"elinewidth": 0.8})

    ax.set_xticks(x)
    ax.set_xticklabels(BAND_LABELS)
    ax.set_xlabel("Direct home-to-station distance band")
    ax.set_ylabel("Late arrivals (count, mean ± 1σ)")
    ax.set_title(
        "Late Arrivals by Vehicle Type and Distance Band\n"
        "Balanced Fleet (50S/27M/14C/5MB, 200 seats) · 15 Seeds",
        pad=6,
    )
    ax.legend(title="Vehicle type", fontsize=9,
              title_fontsize=9, frameon=False)
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir,
                              "fig_balanced_late_by_vehicle_distance"))


# ── Console summary ───────────────────────────────────────────────────────────

def print_summary(df):
    print(f"\n  {'Band':<10}  {'N':>5}  {'Served':>6}  {'Svc%':>6}  "
          f"{'OnTime%':>8}  {'Late':>5}  {'AvgDist':>8}  "
          f"{'AvgDelay':>9}")
    print(f"  {'-'*72}")
    for _, r in df.iterrows():
        n      = int(r["n_total_mean"])  if not np.isnan(r["n_total_mean"])  else 0
        served = int(r["n_served_mean"]) if not np.isnan(r["n_served_mean"]) else 0
        late   = int(r["n_late_mean"])   if not np.isnan(r["n_late_mean"])   else 0
        print(f"  {r['band']:<10}  {n:>5}  {served:>6}  "
              f"{r['service_rate_mean']:>5.1f}%  "
              f"{r['eff_ontime_rate_mean']:>7.1f}%  "
              f"{late:>5}  "
              f"{r['avg_dist_km_mean']:>7.2f}km  "
              f"{r['avg_delay_min_mean']:>8.2f}min")

    print(f"\n  Vehicle-type assignment by band (% of served, mean):")
    print(f"  {'Band':<10}  " +
          "  ".join(f"{vt:>10}" for vt in VEHICLE_TYPES))
    print(f"  {'-'*55}")
    for _, r in df.iterrows():
        vals = "  ".join(
            f"{r.get(f'pct_{vt}_mean', 0):>9.1f}%" for vt in VEHICLE_TYPES
        )
        print(f"  {r['band']:<10}  {vals}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cond-dir",  default=COND_DIR)
    p.add_argument("--out",       default=os.path.join(ANALYSIS_DIR, "plots"))
    args = p.parse_args()

    setup_pub_style()
    print(f"Analysing balanced fleet distance bands...")
    print(f"  Condition : {CONDITION}")
    print(f"  Directory : {args.cond_dir}")

    df = aggregate_all_runs(args.cond_dir)

    if df.empty:
        print("ERROR: no data found.")
        return

    os.makedirs(ANALYSIS_DIR, exist_ok=True)
    csv_path = os.path.join(ANALYSIS_DIR, "distance_band_analysis.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Analysis CSV: {csv_path}")

    print_summary(df)

    print(f"\nGenerating plots -> {args.out}")
    fig_reliability_by_distance(df, args.out)
    fig_vehicle_assignment_by_distance(df, args.out)
    fig_late_by_vehicle_distance(df, args.out)
    print("\nDone — 3 figures.")


if __name__ == "__main__":
    main()