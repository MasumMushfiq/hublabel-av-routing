#!/usr/bin/env python3
"""
analyze_vehicle_type_assignment.py
───────────────────────────────────
Analyze vehicle-type contribution and distance-based assignment for three
representative heterogeneous fleets using existing PyVRP experiment outputs.
Does NOT rerun any optimization.

Representative heterogeneous fleets from the completed residential-origin
Melton 224-seat fleet-composition grid (35 compositions, 15 seeds, 300 s
solver runtime, fixed 20-minute train-aligned slots, zero pre-departure
margin, no distance-band penalty, all-electric vehicle model):
  Balanced      S25/M25/C25/MB25  ->  comp_S25_M25_C25_MB25
  VMT-oriented  S25/M0/C0/MB75    ->  comp_S25_M0_C0_MB75
  Low-emission  S25/M75/C0/MB0    ->  comp_S25_M75_C0_MB0

This mechanism analysis explains how AV vehicle types contribute to served
demand, adjusted AV-only VMT, pooling efficiency, and distance-based assignment.
System-level VMT reduction, system CO2 reduction, service rate, and fallback
private cars are reported in the grid and representative comparison sections.

Usage (from hub_label/ root):
  python3 experiments/scripts/analyze_vehicle_type_assignment.py \\
      --results-root experiments/results/fleet_composition_grid_224seats \\
      --output-dir   experiments/results/analysis/vehicle_type_assignment \\
      --fig-dir      experiments/results/analysis/vehicle_type_assignment/plots \\
      --distance-bins 0,2,4,6,8,999
"""

import argparse
import json
import sys
import warnings
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import AutoMinorLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

# ─── Fleet definitions ─────────────────────────────────────────────────────────

FLEETS = {
    "balanced":     "comp_S25_M25_C25_MB25",
    "vmt_oriented": "comp_S25_M0_C0_MB75",
    "low_emission": "comp_S25_M75_C0_MB0",
}

FLEET_LABELS = {
    "balanced":     "Balanced",
    "vmt_oriented": "VMT-oriented",
    "low_emission": "Low-emission",
}

FLEET_COMPOSITION_LABELS = {
    "balanced":     "S25/M25/C25/MB25",
    "vmt_oriented": "S25/M0/C0/MB75",
    "low_emission": "S25/M75/C0/MB0",
}

VEHICLE_TYPES = ["Scooter", "Moped", "Car", "Minibus"]
# Okabe-Ito qualitative palette, chosen to avoid red-green confusion.
VT_COLORS = {
    "Scooter": "#0072B2",  # blue
    "Moped":   "#009E73",  # bluish green
    "Car":     "#E69F00",  # orange
    "Minibus": "#CC79A7",  # reddish purple
}

# ─── Publication style ────────────────────────────────────────────────────────

def setup_pub_style():
    plt.rcParams.clear()
    plt.rcParams.update({
        "font.family":     "serif",
        "font.serif":      ["Times New Roman", "DejaVu Serif", "serif"],
        "figure.dpi":      150,
        "savefig.dpi":     300,
        "axes.linewidth":  1.2,
        "grid.alpha":      0.3,
        "grid.linewidth":  0.8,
        "font.size":       14,
        "axes.labelsize":  16,
        "axes.titlesize":  16,
        "legend.fontsize": 13,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "pdf.fonttype":    42,
        "ps.fonttype":     42,
    })


def savefig(fig, base):
    """Save figure as both PDF and PNG."""
    base = Path(base)
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(base) + ".pdf", bbox_inches="tight")
    fig.savefig(str(base) + ".png", bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  Saved: {base}.pdf / .png")


# ─── Defensive column detection ───────────────────────────────────────────────

# Candidate column names (compared case-insensitively)
_VT_CANDS    = ["av_type", "vehicle_type", "type", "mode", "assigned_vehicle_type"]
_CID_CANDS   = ["commuter_id", "customer_id", "passenger_id", "id"]
_STATUS_CANDS = ["status"]
_DIST_MM_CANDS = ["direct_station_dist_mm", "direct_dist_mm", "direct_distance_mm"]
_DIST_KM_CANDS = [
    "direct_distance_km", "shortest_path_km",
    "distance_to_station_km", "origin_station_distance_km",
]
_IVT_CANDS   = ["in_vehicle_time_min", "ivt_min", "ride_time_min"]
_ADIST_CANDS = ["in_vehicle_distance_km", "route_distance_km", "assigned_distance_km"]
_DET_CANDS   = ["detour_ratio", "detour"]
_ASSIGNED_STATUS = "assigned"


def _find_col(df, candidates, label, src=""):
    """Return the first matching column name (case-insensitive), or None."""
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lower_map:
            return lower_map[cand.lower()]
    if src:
        warnings.warn(
            f"[{src}] No {label} column found. Tried: {candidates}"
        )
    return None


# ─── Single-run data loading ──────────────────────────────────────────────────

def parse_run(run_dir):
    """
    Load assignments.csv and metrics.json from one run directory.

    Returns (df_served, metrics_dict) where df_served has columns:
      vehicle_type, dist_km, ivt_min, actual_dist_km, detour_ratio.

    ivt_min, actual_dist_km, and detour_ratio are NaN when not present in
    assignments.csv (they are only available as fleet-level aggregates in
    metrics.json in the current schema).

    Returns (None, None) if assignments.csv is missing.
    """
    asgn_path = run_dir / "assignments.csv"
    if not asgn_path.exists():
        warnings.warn(f"assignments.csv not found in {run_dir}")
        return None, None

    df = pd.read_csv(asgn_path)
    df.columns = [c.strip() for c in df.columns]
    src = run_dir.name

    # Load metrics.json (optional)
    metrics = None
    mpath = run_dir / "metrics.json"
    if mpath.exists():
        with open(mpath) as fh:
            metrics = json.load(fh)

    # Vehicle type (required)
    vt_col = _find_col(df, _VT_CANDS, "vehicle type", src)
    if vt_col is None:
        return None, metrics

    # Status filter: keep only commuters served on time by AV after late-arrival
    # pruning. PRUNED_LATE and UNSERVED commuters are fallback private-car users
    # in the final system evaluation, not AV fleet vehicle-type assignments.
    status_col = _find_col(df, _STATUS_CANDS, "status", "")
    if status_col:
        mask = df[status_col].astype(str).str.strip().str.lower().eq(_ASSIGNED_STATUS)
        df = df[mask].copy()
        if len(df) == 0:
            warnings.warn(f"[{src}] Status filter matched 0 ASSIGNED rows.")
    else:
        warnings.warn(
            f"[{src}] No status column found; cannot verify ASSIGNED-only filtering."
        )

    # Direct distance → km
    dist_km_col = _find_col(df, _DIST_KM_CANDS, "direct distance (km)", "")
    dist_mm_col = _find_col(df, _DIST_MM_CANDS, "direct distance (mm)", "")
    if dist_km_col:
        dist_km = pd.to_numeric(df[dist_km_col], errors="coerce")
    elif dist_mm_col:
        # Column stores millimeters; divide by 1 000 000 to convert to km.
        dist_km = pd.to_numeric(df[dist_mm_col], errors="coerce") / 1_000_000.0
    else:
        warnings.warn(f"[{src}] No direct distance column found. dist_km will be NaN.")
        dist_km = pd.Series(np.nan, index=df.index)

    # Optional per-commuter columns (rarely present in assignments.csv)
    ivt_col   = _find_col(df, _IVT_CANDS,   "in-vehicle time", "")
    adist_col = _find_col(df, _ADIST_CANDS, "actual distance",  "")
    det_col   = _find_col(df, _DET_CANDS,   "detour ratio",     "")

    out = pd.DataFrame({
        "vehicle_type":   df[vt_col].astype(str).values,
        "dist_km":        dist_km.values,
        "ivt_min":        (pd.to_numeric(df[ivt_col], errors="coerce").values
                           if ivt_col else np.full(len(df), np.nan)),
        "actual_dist_km": (pd.to_numeric(df[adist_col], errors="coerce").values
                           if adist_col else np.full(len(df), np.nan)),
        "detour_ratio":   (pd.to_numeric(df[det_col], errors="coerce").values
                           if det_col else np.full(len(df), np.nan)),
    })
    return out, metrics


# ─── Per-seed contribution metrics ───────────────────────────────────────────

def contribution_rows_for_seed(fleet, seed, df, metrics):
    """
    One row per vehicle type for this (fleet, seed).

    VMT data comes from metrics.json per_vehicle_type because per-commuter actual
    route distances are not recorded in assignments.csv. In the current schema,
    per_vehicle_type[*].vmt_km and adjusted_av_total_vmt_km are adjusted AV-only
    metrics after late-arrival pruning; fallback private cars are excluded.
    """
    total_served = len(df)
    total_vmt    = (metrics or {}).get(
        "adjusted_av_total_vmt_km",
        (metrics or {}).get("total_vmt_km", np.nan),
    )
    pvt_metrics  = (metrics or {}).get("per_vehicle_type", {})
    rows = []

    for vt in VEHICLE_TYPES:
        sub = df[df["vehicle_type"] == vt]
        n   = len(sub)
        pvt = pvt_metrics.get(vt, {})

        dist  = sub["dist_km"].dropna()
        ivt   = sub["ivt_min"].dropna()
        adist = sub["actual_dist_km"].dropna()
        det   = sub["detour_ratio"].dropna()

        # Derive per-row detour ratio if actual and direct distances are both available
        if len(det) == 0:
            valid = (
                sub["actual_dist_km"].notna()
                & sub["dist_km"].notna()
                & (sub["dist_km"] > 0)
            )
            if valid.any():
                dr  = sub.loc[valid, "actual_dist_km"] / sub.loc[valid, "dist_km"]
                det = dr.replace([np.inf, -np.inf], np.nan).dropna()

        vmt = pvt.get("vmt_km", np.nan)
        if pd.isna(vmt):
            vmt = np.nan
        mean_direct_distance_km = dist.mean() if len(dist) > 0 else np.nan
        av_km_per_served = vmt / n if n > 0 and not pd.isna(vmt) else np.nan
        av_km_per_direct = (
            av_km_per_served / mean_direct_distance_km
            if (
                not pd.isna(av_km_per_served)
                and not pd.isna(mean_direct_distance_km)
                and mean_direct_distance_km > 0
            )
            else np.nan
        )

        rows.append({
            "fleet":                     fleet,
            "fleet_label":               FLEET_LABELS[fleet],
            "fleet_composition":         FLEET_COMPOSITION_LABELS[fleet],
            "seed":                      seed,
            "vehicle_type":              vt,
            "served_commuters":          n,
            "served_share_percent":      n / total_served * 100
                                         if total_served > 0 else np.nan,
            "vehicle_vmt_km":            vmt,
            "total_adjusted_av_vmt_km":  total_vmt,
            "vmt_share_percent":         vmt / total_vmt * 100
                                         if (not pd.isna(vmt) and total_vmt) else np.nan,
            "vmt_source":                "metrics.json per_vehicle_type.vmt_km (adjusted AV-only)",
            "av_km_per_served_commuter": av_km_per_served,
            "av_km_per_direct_km":       av_km_per_direct,
            "mean_direct_distance_km":   mean_direct_distance_km,
            "median_direct_distance_km": dist.median()       if len(dist) > 0 else np.nan,
            "p25_direct_distance_km":    dist.quantile(0.25) if len(dist) > 0 else np.nan,
            "p75_direct_distance_km":    dist.quantile(0.75) if len(dist) > 0 else np.nan,
            "mean_in_vehicle_time_min":  ivt.mean()          if len(ivt) > 0  else np.nan,
            "mean_actual_distance_km":   adist.mean()        if len(adist) > 0 else np.nan,
            "mean_detour_ratio":         det.mean()          if len(det) > 0  else np.nan,
        })
    return rows


# ─── Per-seed distance-bin assignment ────────────────────────────────────────

def make_bin_labels(bin_edges):
    """Human-readable labels for distance bins."""
    labels = []
    for i in range(len(bin_edges) - 1):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        labels.append(f"{lo:g}+ km" if hi >= 999 else f"{lo:g}–{hi:g} km")
    return labels


def distbin_rows_for_seed(fleet, seed, df, bin_edges, bin_labels):
    """
    One row per (distance_bin, vehicle_type) for this (fleet, seed).
    Returns an empty list if dist_km is entirely NaN.
    """
    if df["dist_km"].isna().all():
        return []

    df = df.copy()
    df["dist_bin"] = pd.cut(
        df["dist_km"],
        bins=bin_edges,
        labels=bin_labels,
        right=False,
        include_lowest=True,
    )
    total = len(df)
    rows  = []
    for lbl in bin_labels:
        bin_df = df[df["dist_bin"] == lbl]
        n_bin  = len(bin_df)
        for vt in VEHICLE_TYPES:
            n_vt = int((bin_df["vehicle_type"] == vt).sum())
            rows.append({
                "fleet":        fleet,
                "seed":         seed,
                "distance_bin": lbl,
                "vehicle_type": vt,
                "n_commuters":  n_vt,
                "n_bin_total":  n_bin,
                "pct_of_bin":   n_vt / n_bin * 100  if n_bin > 0  else np.nan,
                "pct_of_total": n_vt / total * 100  if total > 0  else np.nan,
            })
    return rows


# ─── Main loading loop ────────────────────────────────────────────────────────

def load_all_fleets(results_root, bin_edges, bin_labels):
    """
    Iterate over all runs for the three representative fleets.

    Returns:
      df_contrib  — per-seed per-vehicle-type contribution metrics
      df_distbin  — per-seed per-bin per-vehicle-type counts/percentages
      df_raw      — pooled per-commuter (fleet, vehicle_type, dist_km) for boxplot
      n_loaded    — dict of fleet → number of runs successfully loaded
    """
    contrib_rows_all = []
    distbin_rows_all = []
    raw_frames       = []
    n_loaded         = {}

    print("\nRepresentative heterogeneous fleets:")
    for fleet, folder in FLEETS.items():
        print(
            f"  {FLEET_LABELS[fleet]:<12} {FLEET_COMPOSITION_LABELS[fleet]:<16} "
            f"-> {folder}"
        )

    for fleet, folder in FLEETS.items():
        fleet_dir = results_root / folder
        if not fleet_dir.is_dir():
            warnings.warn(f"Fleet directory not found: {fleet_dir}")
            n_loaded[fleet] = 0
            continue
        print(f"\nFound {FLEET_LABELS[fleet]} fleet: {fleet_dir}")

        run_dirs = sorted(
            [d for d in fleet_dir.iterdir()
             if d.is_dir() and d.name.startswith("run_")],
            key=lambda d: int(d.name.split("_")[1])
                         if d.name.split("_")[1].isdigit() else 0,
        )
        ok = 0
        for run_dir in run_dirs:
            s = run_dir.name.split("_")[1]
            seed = int(s) if s.isdigit() else 0

            df, metrics = parse_run(run_dir)
            if df is None or len(df) == 0:
                warnings.warn(f"Skipping {run_dir.name} — no usable data.")
                continue

            contrib_rows_all.extend(
                contribution_rows_for_seed(fleet, seed, df, metrics)
            )
            distbin_rows_all.extend(
                distbin_rows_for_seed(fleet, seed, df, bin_edges, bin_labels)
            )
            raw = df[["vehicle_type", "dist_km"]].copy()
            raw["fleet"] = fleet
            raw["seed"]  = seed
            raw_frames.append(raw)
            ok += 1

        n_loaded[fleet] = ok
        print(f"  {FLEET_LABELS[fleet]:<12}: {ok}/{len(run_dirs)} seed runs processed")

    df_contrib = pd.DataFrame(contrib_rows_all)
    df_distbin = pd.DataFrame(distbin_rows_all)
    df_raw     = (pd.concat(raw_frames, ignore_index=True)
                  if raw_frames else pd.DataFrame(columns=["fleet", "vehicle_type", "dist_km"]))
    return df_contrib, df_distbin, df_raw, n_loaded


# ─── Cross-seed aggregation ───────────────────────────────────────────────────

def summarize(df, group_cols):
    """Compute mean and std across seeds for all numeric columns."""
    num_cols = [
        c for c in df.columns
        if c not in group_cols and c != "seed"
        and pd.api.types.is_numeric_dtype(df[c])
    ]
    agg  = {c: ["mean", "std"] for c in num_cols}
    out  = df.groupby(group_cols).agg(agg)
    out.columns = ["_".join(c) for c in out.columns]
    return out.reset_index()


# ─── LaTeX table ──────────────────────────────────────────────────────────────

def _latex_escape(text):
    """Escape a small amount of plain text for LaTeX table cells."""
    return (
        str(text)
        .replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("_", r"\_")
    )


def write_latex_contribution_table(contrib_summary, out_path):
    """
    Compact paper table for AV-only vehicle-type contribution.

    Percentages are cross-seed means. VMT share is computed from adjusted
    AV-only per-vehicle-type VMT, excluding fallback private-car VMT. Inactive
    vehicle-type rows are omitted from the paper table but remain in the CSV.
    """
    active_threshold = 1e-9
    rows = []
    for fleet in FLEETS:
        for vt in VEHICLE_TYPES:
            sub = contrib_summary[
                (contrib_summary["fleet"] == fleet)
                & (contrib_summary["vehicle_type"] == vt)
            ]
            if sub.empty:
                continue
            r = sub.iloc[0]
            served_pct = r.get("served_share_percent_mean", np.nan)
            if pd.isna(served_pct) or served_pct <= active_threshold:
                continue
            rows.append(
                (
                    FLEET_LABELS[fleet],
                    vt,
                    served_pct,
                    r.get("vmt_share_percent_mean", np.nan),
                    r.get("av_km_per_served_commuter_mean", np.nan),
                    r.get("mean_direct_distance_km_mean", np.nan),
                )
            )

    def fmt_pct(v):
        return "--" if pd.isna(v) else f"{v:.1f}\\%"

    def fmt_km(v):
        return "--" if pd.isna(v) else f"{v:.2f}"

    lines = [
        r"\resizebox{\columnwidth}{!}{%",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Fleet & Type & Served \% & AV VMT \% & AV-km/served & Mean dist. (km) \\",
        r"\midrule",
    ]
    last_fleet = None
    for fleet_label, vt, served_pct, vmt_pct, av_km_per_served, mean_dist in rows:
        fleet_cell = _latex_escape(fleet_label) if fleet_label != last_fleet else ""
        lines.append(
            f"{fleet_cell} & {_latex_escape(vt)} & {fmt_pct(served_pct)} & "
            f"{fmt_pct(vmt_pct)} & {fmt_km(av_km_per_served)} & "
            f"{fmt_km(mean_dist)} \\\\"
        )
        last_fleet = fleet_label
    lines.extend([r"\bottomrule", r"\end{tabular}%", r"}"])

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n")
    print(f"Saved: {out_path}")


# ─── Figure 1: direct distance boxplot ───────────────────────────────────────

def fig_distance_boxplot(df_raw, fig_dir):
    """
    Box plots of direct origin-to-station distance (km) by vehicle type,
    pooled across all seeds. One panel per fleet.
    """
    fleet_names = list(FLEETS.keys())
    fig, axes = plt.subplots(
        1, len(fleet_names),
        figsize=(4.5 * len(fleet_names), 5),
        sharey=True,
    )
    if len(fleet_names) == 1:
        axes = [axes]

    for ax, fleet in zip(axes, fleet_names):
        sub = df_raw[df_raw["fleet"] == fleet]
        data, tick_labels, colors = [], [], []
        for vt in VEHICLE_TYPES:
            vals = sub[sub["vehicle_type"] == vt]["dist_km"].dropna().values
            if len(vals) == 0:
                continue
            data.append(vals)
            tick_labels.append(vt)
            colors.append(VT_COLORS[vt])

        if not data:
            ax.set_title(FLEET_LABELS[fleet])
            ax.text(0.5, 0.5, "No data", transform=ax.transAxes,
                    ha="center", va="center")
            continue

        bp = ax.boxplot(
            data,
            tick_labels=tick_labels,
            patch_artist=True,
            medianprops={"color": "black", "linewidth": 1.5},
            whiskerprops={"linewidth": 1.0},
            capprops={"linewidth": 1.0},
            flierprops={"marker": "o", "markersize": 2,
                        "alpha": 0.25, "linestyle": "none"},
            widths=0.5,
        )
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.75)

        ax.set_title(FLEET_LABELS[fleet])
        ax.set_xlabel("Vehicle type")
        ax.grid(axis="y", ls="--", alpha=0.35)
        ax.yaxis.set_minor_locator(AutoMinorLocator())

    axes[0].set_ylabel("Direct origin-to-station distance (km)")
    fig.tight_layout()
    savefig(fig, fig_dir / "vehicle_type_distance_boxplot")


# ─── Figure 2: distance-bin stacked bar ──────────────────────────────────────

def fig_distbin_stacked_bar(df_distbin, bin_labels, fig_dir):
    """
    Stacked bar charts showing the share of served commuters assigned to each
    vehicle type within each distance bin. Mean across seeds. One panel per fleet.
    """
    fleet_names = list(FLEETS.keys())
    fig, axes = plt.subplots(
        1, len(fleet_names),
        figsize=(4.25 * len(fleet_names), 4.8),
        sharey=True,
    )
    if len(fleet_names) == 1:
        axes = [axes]

    for ax, fleet in zip(axes, fleet_names):
        sub = df_distbin[df_distbin["fleet"] == fleet]

        # Mean pct_of_bin across seeds for each (distance_bin, vehicle_type)
        agg = (
            sub.groupby(["distance_bin", "vehicle_type"])["pct_of_bin"]
            .mean()
            .reset_index()
        )
        pivot = agg.pivot(index="distance_bin", columns="vehicle_type",
                          values="pct_of_bin")
        # Preserve declared bin order; skip bins not in the data
        ordered = [b for b in bin_labels if b in pivot.index]
        pivot   = pivot.reindex(ordered).fillna(0)

        x      = np.arange(len(pivot))
        bottom = np.zeros(len(pivot))

        for vt in VEHICLE_TYPES:
            if vt not in pivot.columns:
                continue
            vals = pivot[vt].values
            ax.bar(
                x, vals, bottom=bottom, width=0.65,
                label=vt, color=VT_COLORS[vt],
                edgecolor="white", linewidth=0.4,
            )
            for i, (v, b) in enumerate(zip(vals, bottom)):
                if v >= 7:
                    ax.text(
                        i, b + v / 2, f"{v:.0f}%",
                        ha="center", va="center",
                        fontsize=9, color="white", fontweight="bold",
                    )
            bottom += vals

        ax.set_xticks(x)
        ax.set_xticklabels(list(pivot.index), rotation=30, ha="right")
        ax.set_title(FLEET_LABELS[fleet])
        ax.set_ylim(0, 108)
        ax.grid(axis="y", ls="--", alpha=0.35)
        ax.yaxis.set_minor_locator(AutoMinorLocator())

    axes[0].set_ylabel("Share of served commuters (%)")
    fig.supxlabel("Direct origin-to-station distance bin", y=0.17, fontsize=15)

    handles = [
        plt.Rectangle(
            (0, 0), 1, 1,
            facecolor=VT_COLORS[vt], alpha=0.8, linewidth=0,
        )
        for vt in VEHICLE_TYPES
    ]
    fig.legend(
        handles, VEHICLE_TYPES,
        title="Vehicle type",
        loc="lower center",
        ncol=4,
        frameon=False,
        bbox_to_anchor=(0.5, 0.01),
    )
    fig.subplots_adjust(left=0.07, right=0.99, top=0.88, bottom=0.34, wspace=0.08)
    savefig(fig, fig_dir / "distance_bin_assignment_stacked_bar")


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Analyze vehicle-type assignment for representative fleet experiments."
    )
    p.add_argument(
        "--results-root",
        default="experiments/results/fleet_composition_grid_224seats",
        help="Root of the fleet-composition grid results directory.",
    )
    p.add_argument(
        "--output-dir",
        default="experiments/results/analysis/vehicle_type_assignment",
        help="Directory for output CSV files.",
    )
    p.add_argument(
        "--fig-dir",
        default="experiments/results/analysis/vehicle_type_assignment/plots",
        help="Directory for output figures (default: <output-dir>/plots).",
    )
    p.add_argument(
        "--distance-bins",
        default="0,2,4,6,8,999",
        help="Comma-separated bin edges in km (last value treated as ∞). "
             "Example: 0,2,4,6,8,999",
    )
    return p.parse_args()


def print_mechanism_interpretation():
    """Print paper-facing interpretation guidance for the mechanism section."""
    print("\nMechanism interpretation:")
    print("  Balanced shows the clearest mixed vehicle-type division of labor.")
    print("  VMT-oriented is minibus-dominant across distance bins.")
    print("  Low-emission is moped-dominant across distance bins.")
    print("  Scooters remain a limited/niche contributor despite their 25% seat share.")
    print(
        "  AV-km per served commuter captures pooling efficiency and uses "
        "adjusted AV-only VMT."
    )
    print(
        "  Interpret distance stratification mainly for the balanced fleet; "
        "the specialized fleets are dominated by their workhorse vehicle type."
    )


def main():
    args = parse_args()

    root      = Path(args.results_root)
    out_dir   = Path(args.output_dir)
    fig_dir   = Path(args.fig_dir)
    bin_edges = [float(x) for x in args.distance_bins.split(",")]
    bin_labels = make_bin_labels(bin_edges)

    out_dir.mkdir(parents=True, exist_ok=True)
    fig_dir.mkdir(parents=True, exist_ok=True)

    setup_pub_style()

    print("=" * 60)
    print("Vehicle-type assignment analysis")
    print(f"  Results root : {root}")
    print(f"  Output dir   : {out_dir}")
    print(f"  Figure dir   : {fig_dir}")
    print(f"  Distance bins: {bin_labels}")
    print(
        "  Assignment filter: status == ASSIGNED only "
        "(PRUNED_LATE/UNSERVED are fallback private cars)"
    )
    print(
        "  VMT contribution: metrics.json per_vehicle_type.vmt_km divided by "
        "adjusted_av_total_vmt_km (adjusted AV-only)"
    )
    print("=" * 60)

    df_contrib, df_distbin, df_raw, n_loaded = load_all_fleets(
        root, bin_edges, bin_labels
    )

    if df_contrib.empty:
        print("ERROR: no data loaded. Check --results-root.")
        sys.exit(1)

    # ── CSV: per-seed tables ───────────────────────────────────────────────────

    p = out_dir / "vehicle_type_contribution_by_seed.csv"
    df_contrib.to_csv(p, index=False)
    print(f"\nSaved: {p}")

    if not df_distbin.empty:
        p = out_dir / "distance_bin_assignment_by_seed.csv"
        df_distbin.to_csv(p, index=False)
        print(f"Saved: {p}")
    else:
        warnings.warn(
            "No distance-bin data produced — dist_km may be NaN for all runs."
        )

    # ── CSV: cross-seed summaries ──────────────────────────────────────────────

    contrib_summary = summarize(df_contrib, ["fleet", "vehicle_type"])
    p = out_dir / "vehicle_type_contribution_summary.csv"
    contrib_summary.to_csv(p, index=False)
    print(f"Saved: {p}")

    write_latex_contribution_table(
        contrib_summary,
        out_dir / "vehicle_type_contribution_table.tex",
    )

    if not df_distbin.empty:
        bin_summary = summarize(df_distbin, ["fleet", "distance_bin", "vehicle_type"])
        p = out_dir / "distance_bin_assignment_summary.csv"
        bin_summary.to_csv(p, index=False)
        print(f"Saved: {p}")

    # ── Figures ────────────────────────────────────────────────────────────────

    print(f"\nGenerating figures → {fig_dir}")
    if not df_raw.empty and not df_raw["dist_km"].isna().all():
        fig_distance_boxplot(df_raw, fig_dir)
    else:
        warnings.warn("Skipping boxplot — no valid dist_km data.")

    if not df_distbin.empty:
        fig_distbin_stacked_bar(df_distbin, bin_labels, fig_dir)

    # ── Final summary ──────────────────────────────────────────────────────────

    print("\n" + "=" * 60)
    print("Runs loaded per fleet:")
    for fleet, n in n_loaded.items():
        print(f"  {FLEET_LABELS[fleet]:<16}: {n} seed run(s)")
    print("\nVMT contribution source:")
    print("  adjusted AV-only per-vehicle-type metrics from metrics.json")
    print("  fallback private-car VMT is excluded from vehicle-type shares")
    print_mechanism_interpretation()
    print(f"\nCSV outputs : {out_dir}/")
    print(f"Figures     : {fig_dir}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
