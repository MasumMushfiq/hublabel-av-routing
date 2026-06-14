#!/usr/bin/env python3
"""
plot_fleet_composition_grid.py
───────────────────────────────
Aggregates and plots the active Footscray 80-seat fleet-composition grid.
Current framing: service rate and fallback private cars are interpreted
alongside system-level VMT, energy, CO2, and cost metrics.

Produces:
  Combined figure:
    fig_fleet_composition_grid.pdf/.png     — compact 2×2 overview

  Individual figures:
    fig_fleet_composition_tradeoff.pdf/.png — service vs VMT scatter
    fig_fleet_composition_service.pdf/.png  — service & fallback bars
    fig_fleet_composition_vmt_co2.pdf/.png  — VMT vs CO2 scatter
    fleet_composition_tradeoff_system_vmt_co2.pdf/.png
                                            — paper-facing system VMT vs CO2 scatter

  Data:
    fleet_composition_grid_summary.csv
    fleet_composition_representative_table.csv
    fleet_composition_representative_table.tex
    top_service_first.csv            — optional high-service screen, sorted by service
    top_efficiency_high_service.csv  — optional high-service screen, sorted by VMT

Usage (from hub_label/ root):
  python3 experiments/scripts/plot_fleet_composition_grid.py \
      --results-dir experiments/results/footscray/fleet_composition_grid_footscray_80seats
"""

import os
import json
import argparse
import re

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
from plot_pub_style import setup_pub_style as apply_pub_style
from matplotlib.ticker import AutoMinorLocator

matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

RESULTS_ROOT = "experiments/results/footscray/fleet_composition_grid_footscray_80seats"

HIGH_SERVICE_SCREENING_THRESHOLD = 97.0

PRIMARY_REQUIRED_FIELDS = [
    "service_rate",
    "served_commuters",
    "fallback_private_cars",
    "system_total_vmt_km",
    "system_vmt_change_pct",
    "system_total_energy_kwh",
    "system_energy_change_pct",
    "system_total_co2_kg",
    "system_co2_change_pct",
]

EXTRA_NUMERIC_FIELDS = [
    # Primary service counts
    "served_commuters",
    "unserved_commuters",
    # Passenger/service secondary metrics
    "avg_wait_time_min",
    "avg_total_travel_time_min",
    # Parking metrics
    "baseline_parking_spaces",
    "station_commuter_parking_spaces",
    "station_parking_reduction_pct",
    "fleet_storage_equiv_spaces",
    "net_parking_equiv_if_fleet_stored_at_station",
    "net_parking_reduction_pct_if_fleet_stored_at_station",
    # Cost metrics
    "av_fleet_fixed_cost",
    "av_distance_operating_cost",
    "av_energy_cost",
    "av_total_operating_cost",
    "av_cost_per_commuter_total",
    "av_cost_per_passenger_km",
    "av_cost_per_vehicle_km",
    # Fallback private-car metrics
    "fallback_private_car_vmt_km",
    "fallback_private_car_energy_kwh",
    "fallback_private_car_co2_kg",
    "fallback_private_car_energy_cost",
    "fallback_private_car_share_pct",
    # Baseline metrics
    "baseline_total_vmt_km",
    "baseline_total_energy_kwh",
    "baseline_total_co2_kg",
    "baseline_energy_cost",
]

KEY_SECONDARY_FIELDS = [
    "avg_in_vehicle_time_min",
    "station_parking_reduction_pct",
    "av_total_operating_cost",
]

REPRESENTATIVE_FLEETS = [
    {
        "role": "All-car comparator",
        "label": "All-car",
        "condition": "comp_S0_M0_C100_MB0",
        "seat_shares": "S0/M0/C100/MB0",
        "shares": (0, 0, 100, 0),
        "expected_vehicles": 20,
        "marker": "o",
    },
    {
        "role": "Balanced",
        "label": "Balanced",
        "condition": "comp_S25_M25_C25_MB25",
        "seat_shares": "S25/M25/C25/MB25",
        "shares": (25, 25, 25, 25),
        "expected_vehicles": 37,
        "marker": "s",
    },
    {
        "role": "VMT-oriented",
        "label": "VMT-oriented",
        "condition": "comp_S25_M0_C0_MB75",
        "seat_shares": "S25/M0/C0/MB75",
        "shares": (25, 0, 0, 75),
        "expected_vehicles": 26,
        "marker": "^",
    },
    {
        "role": "Low-emission",
        "label": "Low-emission",
        "condition": "comp_S50_M50_C0_MB0",
        "seat_shares": "S50/M50/C0/MB0",
        "shares": (50, 50, 0, 0),
        "expected_vehicles": 60,
        "marker": "D",
    },
]


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
    if configs_dir is None:
        return None
    meta_path = os.path.join(configs_dir, "composition_metadata.csv")
    if os.path.isfile(meta_path):
        return pd.read_csv(meta_path).set_index("condition")
    return None


LABEL_PATTERN = re.compile(r"^comp_S(\d+)_M(\d+)_C(\d+)_MB(\d+)$")


def parse_shares(condition):
    match = LABEL_PATTERN.fullmatch(condition)
    if not match:
        return {}
    scooter, moped, car, minibus = (int(value) for value in match.groups())
    return {
        "target_scooter_share": scooter,
        "target_moped_share": moped,
        "target_car_share": car,
        "target_minibus_share": minibus,
    }


def _first_number(*values, default=0.0):
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _first_present(*dict_key_pairs):
    for data, key in dict_key_pairs:
        if not isinstance(data, dict):
            continue
        if key in data and data[key] is not None:
            return data[key]
    return None


def _optional_number_from_sources(field, *sources):
    for source in sources:
        if not isinstance(source, dict) or field not in source:
            continue
        value = source[field]
        if isinstance(value, (dict, list, tuple)):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return np.nan


def _system_change_pct(comparison, metrics, metric_name, fallback_total, baseline_total, run_path):
    system_key = f"system_{metric_name}_change_pct"
    change = _first_present((comparison, system_key), (metrics, system_key))
    if change is not None:
        return _first_number(change, default=np.nan)

    if baseline_total:
        return (float(fallback_total) - float(baseline_total)) / float(baseline_total) * 100.0

    legacy_key = f"{metric_name}_change_pct"
    legacy_change = _first_present((comparison, legacy_key), (metrics, legacy_key))
    if legacy_change is not None:
        print(
            f"  WARNING: using legacy {legacy_key} for {run_path}; "
            f"{system_key} was unavailable."
        )
        return _first_number(legacy_change, default=np.nan)

    print(f"  WARNING: missing {system_key} for {run_path}; setting change to NaN")
    return np.nan


def _system_reduction_pct(system_change_pct):
    return -float(system_change_pct) if system_change_pct is not None else np.nan


def _has_share_metadata(df):
    return all(
        col in df.columns
        for col in [
            "target_scooter_share",
            "target_moped_share",
            "target_car_share",
            "target_minibus_share",
        ]
    )


def aggregate(results_dir, configs_dir=None):
    meta = load_metadata(configs_dir)
    rows = []
    field_seen = {field: 0 for field in PRIMARY_REQUIRED_FIELDS + EXTRA_NUMERIC_FIELDS + KEY_SECONDARY_FIELDS}
    field_missing = {field: 0 for field in PRIMARY_REQUIRED_FIELDS + EXTRA_NUMERIC_FIELDS + KEY_SECONDARY_FIELDS}
    total_runs = 0
    conditions = sorted(
        d for d in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, d)) and d.startswith("comp_")
    )
    print(f"  Found {len(conditions)} condition directories")
    missing_runs = []

    for cond in conditions:
        cond_dir = os.path.join(results_dir, cond)
        run_metrics = []

        metric_paths = sorted(
            os.path.join(root, "metrics.json")
            for root, _, files in os.walk(cond_dir)
            if "metrics.json" in files
        )
        for mpath in metric_paths:
            run_dir = os.path.dirname(mpath)
            bpath = os.path.join(run_dir, "baseline.json")
            cpath = os.path.join(run_dir, "comparison.json")

            with open(mpath) as f:
                m = json.load(f)
            comparison = {}
            if os.path.isfile(cpath):
                with open(cpath) as f:
                    comparison = json.load(f)

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
                b = dict(b)
                b.setdefault("baseline_total_vmt_km", baseline_vmt)
                b.setdefault("baseline_total_energy_kwh", baseline_energy)
                b.setdefault("baseline_total_co2_kg", baseline_co2)
            else:
                b = {}
            total_runs += 1

            served = m.get("served_commuters", 0)
            total = m.get("total_commuters", 1)
            service_rate = _first_number(
                comparison.get("service_rate_pct"),
                comparison.get("service_rate"),
                m.get("service_rate"),
                served / total * 100 if total else None,
            )
            fallback_private_cars = _first_number(
                comparison.get("fallback_private_cars"),
                m.get("fallback_private_cars"),
                m.get("late_deliveries", 0) + m.get("unserved_commuters", 0),
            )
            system_vmt = _first_number(
                comparison.get("system_total_vmt_km"),
                m.get("system_total_vmt_km"),
                default=np.nan,
            )
            system_energy = _first_number(
                comparison.get("system_total_energy_kwh"),
                m.get("system_total_energy_kwh"),
                default=np.nan,
            )
            system_co2 = _first_number(
                comparison.get("system_total_co2_kg"),
                m.get("system_total_co2_kg"),
                default=np.nan,
            )
            av_total_vmt = _first_number(
                comparison.get("adjusted_av_total_vmt_km"),
                m.get("adjusted_av_total_vmt_km"),
                comparison.get("av_total_vmt_km"),
                m.get("total_vmt_km"),
                default=np.nan,
            )
            av_total_energy = _first_number(
                comparison.get("adjusted_av_total_energy_kwh"),
                m.get("adjusted_av_total_energy_kwh"),
                comparison.get("av_total_energy_kwh"),
                m.get("total_energy_kwh"),
                default=np.nan,
            )
            av_total_co2 = _first_number(
                comparison.get("adjusted_av_total_co2_kg"),
                m.get("adjusted_av_total_co2_kg"),
                comparison.get("av_total_co2_kg"),
                m.get("total_co2_kg"),
                default=np.nan,
            )
            late = _optional_number_from_sources("late_deliveries", comparison, m)
            on_time = _optional_number_from_sources("on_time_rate", comparison, m)
            avg_pax = _optional_number_from_sources("avg_passengers_per_trip", comparison, m)
            loaded = _first_number(
                comparison.get("loaded_vmt_km"),
                m.get("loaded_vmt_km"),
                m.get("adjusted_av_total_vmt_km"),
                default=np.nan,
            )
            empty = _optional_number_from_sources("empty_vmt_km", comparison, m)
            empty_r = _optional_number_from_sources("empty_vmt_ratio", comparison, m)
            v_used = _optional_number_from_sources("vehicles_used", comparison, m)
            v_trips = _optional_number_from_sources("vehicle_trips", comparison, m)
            avg_ivt = _optional_number_from_sources("avg_in_vehicle_time_min", comparison, m)
            max_ivt = _optional_number_from_sources("max_in_vehicle_time_min", comparison, m)
            av_cost_per_served_commuter = _first_number(
                comparison.get("av_cost_per_served_commuter"),
                m.get("av_cost_per_served_commuter"),
                default=np.nan,
            )
            avg_det = _optional_number_from_sources("avg_detour_ratio", comparison, m)
            max_det = _optional_number_from_sources("max_detour_ratio", comparison, m)
            solo = _optional_number_from_sources("solo_trips", comparison, m)
            shared = _optional_number_from_sources("shared_trips", comparison, m)
            pooling = _optional_number_from_sources("pooling_rate", comparison, m)
            if pd.isna(pooling) and pd.notna(solo) and pd.notna(shared) and (solo + shared) > 0:
                pooling = shared / (solo + shared) * 100

            run_path = run_dir
            system_vmt_change = _system_change_pct(
                comparison, m, "vmt", system_vmt, baseline_vmt, run_path
            )
            system_energy_change = _system_change_pct(
                comparison, m, "energy", system_energy, baseline_energy, run_path
            )
            system_co2_change = _system_change_pct(
                comparison, m, "co2", system_co2, baseline_co2, run_path
            )
            system_vmt_reduction = _system_reduction_pct(system_vmt_change)
            system_energy_reduction = _system_reduction_pct(system_energy_change)
            system_co2_reduction = _system_reduction_pct(system_co2_change)

            row = {
                "service_rate": service_rate,
                "served_commuters": _optional_number_from_sources("served_commuters", comparison, m),
                "on_time_rate": on_time,
                "late_deliveries": late,
                "unserved_commuters": _optional_number_from_sources("unserved_commuters", comparison, m),
                "fallback_private_cars": fallback_private_cars,
                "system_total_vmt_km": system_vmt,
                "system_total_energy_kwh": system_energy,
                "system_total_co2_kg": system_co2,
                "system_vmt_change_pct": system_vmt_change,
                "system_energy_change_pct": system_energy_change,
                "system_co2_change_pct": system_co2_change,
                "system_vmt_reduction_pct": system_vmt_reduction,
                "system_energy_reduction_pct": system_energy_reduction,
                "system_co2_reduction_pct": system_co2_reduction,
                # AV-only totals. Paper-facing plots and tables use explicit system_* columns.
                "total_vmt_km": av_total_vmt,
                "total_energy_kwh": av_total_energy,
                "total_co2_kg": av_total_co2,
                "loaded_vmt_km": loaded,
                "empty_vmt_km": empty,
                "empty_vmt_ratio": empty_r,
                "avg_passengers_per_trip": avg_pax,
                "pooling_rate": pooling,
                "vehicles_used": v_used,
                "vehicle_trips": v_trips,
                "avg_in_vehicle_time_min": avg_ivt,
                "max_in_vehicle_time_min": max_ivt,
                "av_cost_per_served_commuter": av_cost_per_served_commuter,
                "avg_detour_ratio": avg_det,
                "max_detour_ratio": max_det,
            }
            for field in EXTRA_NUMERIC_FIELDS:
                if field in row:
                    continue
                row[field] = _optional_number_from_sources(field, comparison, m, b)

            for field in field_seen:
                value = row.get(field, np.nan)
                if pd.isna(value):
                    field_missing[field] += 1
                else:
                    field_seen[field] += 1

            run_metrics.append(row)

        if not run_metrics:
            missing_runs.append(cond)
            continue

        n = len(run_metrics)
        keys = sorted({key for row in run_metrics for key in row})
        arr = {k: np.array([r.get(k, np.nan) for r in run_metrics], dtype=float) for k in keys}
        row = {"condition": cond, "label": cond, "n_runs": n, "runs": n}
        for k, vals in arr.items():
            row[f"{k}_mean"] = np.nanmean(vals)
            row[f"{k}_std"] = np.nanstd(vals, ddof=1) if n > 1 else float("nan")

        if meta is not None and cond in meta.index:
            for col in meta.columns:
                row[col] = meta.loc[cond, col]
        for col, value in parse_shares(cond).items():
            row.setdefault(col, value)
        row["composition_label"] = short_label(cond)

        rows.append(row)

    if missing_runs:
        print(f"  WARNING: {len(missing_runs)} conditions with no runs: {missing_runs}")

    availability = {
        "field_seen": field_seen,
        "field_missing": field_missing,
        "total_runs": total_runs,
    }
    return pd.DataFrame(rows), missing_runs, availability


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

    rel = df[df["service_rate_mean"] >= HIGH_SERVICE_SCREENING_THRESHOLD]
    if not rel.empty:
        idx = rel["service_rate_mean"].idxmax()
        cond = df.loc[idx, "condition"]
        labels.setdefault(cond, "Best\nservice")

    eff = df[df["service_rate_mean"] >= HIGH_SERVICE_SCREENING_THRESHOLD]
    if not eff.empty:
        idx = eff["system_vmt_reduction_pct_mean"].idxmax()
        cond = df.loc[idx, "condition"]
        labels.setdefault(
            cond,
            f"Best VMT\n(optional service≥{HIGH_SERVICE_SCREENING_THRESHOLD:.0f}%)",
        )

    return labels


# ── Figure helpers ───────────────────────────────────────────────────────────

def optional_high_service_candidates(df):
    return df[df["service_rate_mean"] >= HIGH_SERVICE_SCREENING_THRESHOLD].copy()


def fig_tradeoff(df, out_dir):
    fig, ax = plt.subplots(figsize=(10, 7))
    x = df["service_rate_mean"].to_numpy()
    y = df["system_vmt_reduction_pct_mean"].to_numpy()
    color = df["system_co2_reduction_pct_mean"].to_numpy()
    size = (df["avg_passengers_per_trip_mean"].to_numpy() * 30) ** 1.4

    sc = ax.scatter(
        x,
        y,
        c=color,
        s=size * 1.1,
        cmap="YlOrRd",
        alpha=0.9,
        edgecolors="grey",
        linewidths=0.4,
        zorder=4,
    )

    cbar = plt.colorbar(sc, ax=ax, shrink=0.85)
    cbar.set_label(r"System CO$_2$ reduction (%)", fontsize=10)
    cbar.ax.yaxis.set_tick_params(labelsize=12)

    for thresh, ls, label in [
        (
            HIGH_SERVICE_SCREENING_THRESHOLD,
            "-",
            f"Optional service screen ≥{HIGH_SERVICE_SCREENING_THRESHOLD:.0f}%",
        ),
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
        xi = row["service_rate_mean"].iloc[0]
        yi = row["system_vmt_reduction_pct_mean"].iloc[0]
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

    ax.set_xlabel("Service rate (%)")
    ax.set_ylabel("System VMT reduction (%)")
    ax.set_title("(a) Service vs System VMT Reduction", fontsize=10.5)
    ax.grid(ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_tradeoff"))


def fig_service_fallback(df, out_dir):
    df_s = df.sort_values("service_rate_mean", ascending=False)
    x = np.arange(len(df_s))
    w = 0.4
    svc_m = df_s["service_rate_mean"].to_numpy()
    svc_s = df_s["service_rate_std"].fillna(0).to_numpy()
    fallback_m = df_s["fallback_private_cars_mean"].to_numpy()
    fallback_s = df_s["fallback_private_cars_std"].fillna(0).to_numpy()
    xlabs = [c.replace("comp_", "").replace("_", "\n") for c in df_s["condition"]]

    fig, ax = plt.subplots(figsize=(18, 5))
    ax2 = ax.twinx()
    ax.bar(x - w / 2, svc_m, width=w, yerr=svc_s, capsize=1.5,
           color="#2196F3", edgecolor="white", linewidth=0.3,
           alpha=0.85, label="Service rate (%)",
           error_kw={"elinewidth": 0.8})
    ax2.bar(x + w / 2, fallback_m, width=w, yerr=fallback_s, capsize=1.5,
            color="#FF9800", edgecolor="white", linewidth=0.3,
            alpha=0.85, label="Fallback private cars",
            error_kw={"elinewidth": 0.8})
    ax.axhline(HIGH_SERVICE_SCREENING_THRESHOLD, color="#d62728", ls="-", lw=0.9, alpha=0.6,
               label=f"Optional service screen ≥{HIGH_SERVICE_SCREENING_THRESHOLD:.0f}%")
    ax.set_xticks(x)
    ax.set_xticklabels(xlabs, fontsize=8.5, rotation=90)
    ax.set_ylabel("Service rate (%)")
    ax2.set_ylabel("Fallback private cars")
    ax.set_ylim(0, 108)
    ax.set_title(
        "Service Rate and Fallback Private Cars by Fleet Composition\n"
        "(sorted by service rate, descending)",
        fontsize=10,
        pad=6,
    )
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, fontsize=8, frameon=False)
    ax.grid(axis="y", ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_service"))


def fig_vmt_co2(df, out_dir):
    fig, ax = plt.subplots(figsize=(7, 5.5))
    x = df["system_vmt_reduction_pct_mean"].to_numpy()
    y = df["system_co2_reduction_pct_mean"].to_numpy()
    c = df["service_rate_mean"].to_numpy()

    sc = ax.scatter(x, y, c=c, s=55,
                    cmap="RdYlGn", alpha=0.9, edgecolors="grey",
                    linewidths=0.4, zorder=4)

    cbar = plt.colorbar(sc, ax=ax, shrink=0.85)
    cbar.set_label("Service rate (%)", fontsize=10)
    cbar.ax.yaxis.set_tick_params(labelsize=12)
    ax.set_xlabel("System VMT reduction (%)")
    ax.set_ylabel(r"System CO$_2$ reduction (%)")
    ax.set_title(r"(b) System VMT vs CO$_2$ (colour = service)", fontsize=10.5, pad=6)
    ax.grid(ls="--", alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_vmt_co2"))


def fig_combined(df, out_dir):
    fig, axes = plt.subplots(2, 2, figsize=(7.1, 5.2))
    ax_a, ax_b, ax_c, ax_d = axes.flatten()

    x = df["service_rate_mean"].to_numpy()
    y = df["system_vmt_reduction_pct_mean"].to_numpy()
    color = df["system_co2_reduction_pct_mean"].to_numpy()
    size = (df["avg_passengers_per_trip_mean"].to_numpy() * 30) ** 1.4
    pax = df["avg_passengers_per_trip_mean"].to_numpy()

    # (a) Tradeoff
    sc_a = ax_a.scatter(x, y, c=color, s=size * 1.1,
                        cmap="YlOrRd", alpha=0.9, edgecolors="grey",
                        linewidths=0.4, zorder=4)
    cbar_a = plt.colorbar(sc_a, ax=ax_a, shrink=0.8)
    cbar_a.set_label(r"System CO$_2$ reduction (%)", fontsize=10)
    cbar_a.ax.yaxis.set_tick_params(labelsize=12)
    ax_a.axvline(HIGH_SERVICE_SCREENING_THRESHOLD, color="#d62728", ls="-", lw=1.0, alpha=0.65)
    ax_a.set_xlabel("Service rate (%)")
    ax_a.set_ylabel("System VMT reduction (%)")
    ax_a.set_title("(a) Service vs System VMT Reduction", fontsize=10.5)
    ax_a.grid(ls="--", alpha=0.35)

    balanced = df[df["condition"] == "comp_S25_M25_C25_MB25"]
    if not balanced.empty:
        bx = balanced["service_rate_mean"].iloc[0]
        by = balanced["system_vmt_reduction_pct_mean"].iloc[0]
        ax_a.scatter([bx], [by], marker="*", s=220, c="black", zorder=6)
        ax_a.annotate("Balanced",
                      xy=(bx, by), xytext=(bx + 0.5, by + 1.5), fontsize=10,
                      arrowprops=dict(arrowstyle="-", color="black", lw=0.8))

    # (b) VMT vs CO2
    sc_b = ax_b.scatter(df["system_vmt_reduction_pct_mean"],
                        df["system_co2_reduction_pct_mean"],
                        c=df["service_rate_mean"],
                        s=60, cmap="RdYlGn", alpha=0.9,
                        edgecolors="grey", linewidths=0.4, zorder=4)
    cbar_b = plt.colorbar(sc_b, ax=ax_b, shrink=0.8)
    cbar_b.set_label("Service rate (%)", fontsize=10)
    cbar_b.ax.yaxis.set_tick_params(labelsize=12)
    ax_b.set_xlabel("System VMT reduction (%)")
    ax_b.set_ylabel(r"System CO$_2$ reduction (%)")
    ax_b.set_title("(b) System VMT vs CO$_2$ (colour = service)", fontsize=10.5)
    ax_b.grid(ls="--", alpha=0.35)

    # (c) Avg pax vs VMT
    sc_c = ax_c.scatter(pax, y, c=color, s=66,
                        cmap="YlOrRd", alpha=0.9, edgecolors="grey",
                        linewidths=0.4, zorder=4)
    cbar_c = plt.colorbar(sc_c, ax=ax_c, shrink=0.8)
    cbar_c.set_label(r"System CO$_2$ reduction (%)", fontsize=10)
    cbar_c.ax.yaxis.set_tick_params(labelsize=12)
    ax_c.set_xlabel("Avg passengers per trip")
    ax_c.set_ylabel("System VMT reduction (%)")
    ax_c.set_title("(c) Avg pax/trip vs System VMT Reduction", fontsize=10.5)
    ax_c.grid(ls="--", alpha=0.35)

    # (d) Optional high-service compositions (horizontal bars)
    full_df = optional_high_service_candidates(df)
    if full_df.empty:
        ax_d.text(0.5, 0.5, "No service-threshold compositions\n(service≥97.0%)",
                  ha="center", va="center")
        ax_d.set_axis_off()
    else:
        topn = full_df.sort_values("system_vmt_reduction_pct_mean", ascending=False).head(5)
        topn = topn.reset_index(drop=True)
        vals = topn["system_vmt_reduction_pct_mean"].to_numpy()
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
        ax_d.set_xlabel("System VMT reduction (%)", fontsize=10.5)
        ax_d.set_title("(d) Optional high-service screen by VMT reduction", fontsize=10.5)
        ax_d.grid(axis="x", ls="--", alpha=0.35)

        # add service-rate labels at end of bars
        services = topn["service_rate_mean"].to_numpy()
        for i, bar in enumerate(bars):
            width = bar.get_width()
            ax_d.text(width + 0.5, bar.get_y() + bar.get_height() / 2,
                      f"{services[::-1][i]:.1f}%", va="center", ha="left", fontsize=9.5)

    fig.tight_layout()
    savefig(fig, os.path.join(out_dir, "fig_fleet_composition_grid"))


# ── Representative fleet outputs ─────────────────────────────────────────────

def _match_representative(df, rep):
    exact = df[df["condition"] == rep["condition"]]
    if not exact.empty:
        return exact.iloc[0]

    if _has_share_metadata(df):
        scooter, moped, car, minibus = rep["shares"]
        match = df[
            (df["target_scooter_share"] == scooter)
            & (df["target_moped_share"] == moped)
            & (df["target_car_share"] == car)
            & (df["target_minibus_share"] == minibus)
        ]
        if not match.empty:
            return match.iloc[0]

    print(f"  WARNING: missing representative fleet {rep['label']} ({rep['seat_shares']})")
    return None


def representative_rows(df):
    rows = []
    for rep in REPRESENTATIVE_FLEETS:
        row = _match_representative(df, rep)
        if row is not None:
            rows.append((rep, row))
    if len(rows) != len(REPRESENTATIVE_FLEETS):
        print(
            f"  WARNING: found {len(rows)} of {len(REPRESENTATIVE_FLEETS)} "
            "representative fleets in the aggregated summary."
        )
    return rows


def fig_system_tradeoff_representatives(df, out_dir):
    # Size the PDF near an ACM single-column width so LaTeX does not shrink
    # the typography when included with width=\linewidth.
    fig, ax = plt.subplots(figsize=(3.35, 2.85), constrained_layout=True)
    reps = representative_rows(df)
    rep_conditions = {str(row["condition"]) for _, row in reps}
    bg = df[~df["condition"].astype(str).isin(rep_conditions)]

    sc = ax.scatter(
        bg["system_vmt_reduction_pct_mean"],
        bg["system_co2_reduction_pct_mean"],
        c=bg["service_rate_mean"],
        s=34,
        cmap="viridis",
        vmin=70,
        vmax=99,
        alpha=0.82,
        edgecolors="white",
        linewidths=0.35,
        zorder=2,
    )
    cbar = fig.colorbar(sc, ax=ax, shrink=0.88, pad=0.025)
    cbar.set_label("Service rate (%)", fontsize=9.5)
    cbar.ax.tick_params(labelsize=8.5)

    offsets = {
        "All-car": (-18, -13),
        "Balanced": (-18, 13),
        "VMT-oriented": (-18, -16),
        "Low-emission": (12, -13),
    }
    for rep, row in reps:
        x = row["system_vmt_reduction_pct_mean"]
        y = row["system_co2_reduction_pct_mean"]
        xerr = row.get("system_vmt_reduction_pct_std", row.get("system_vmt_change_pct_std", np.nan))
        yerr = row.get("system_co2_reduction_pct_std", row.get("system_co2_change_pct_std", np.nan))
        ax.errorbar(
            [x],
            [y],
            xerr=None if pd.isna(xerr) else [xerr],
            yerr=None if pd.isna(yerr) else [yerr],
            fmt="none",
            ecolor="#333333",
            elinewidth=1.0,
            capsize=3.0,
            capthick=0.9,
            alpha=0.75,
            zorder=4,
        )
        ax.scatter(
            [x],
            [y],
            s=92,
            marker=rep["marker"],
            c=[row["service_rate_mean"]],
            cmap=sc.cmap,
            norm=sc.norm,
            edgecolors="black",
            linewidths=1.25,
            zorder=5,
        )
        dx, dy = offsets.get(rep["label"], (10, 10))
        ax.annotate(
            rep["label"],
            xy=(x, y),
            xytext=(dx, dy),
            textcoords="offset points",
            ha="right" if dx < 0 else "left",
            va="center",
            fontsize=8.5,
            arrowprops=dict(arrowstyle="-", color="#666666", lw=0.7, alpha=0.9),
            zorder=6,
        )

    ax.axvline(0, color="#555555", ls="--", lw=0.8, alpha=0.7, zorder=1)
    ax.axhline(0, color="#555555", ls="--", lw=0.8, alpha=0.7, zorder=1)
    y0, y1 = ax.get_ylim()
    ax.text(
        -2.0,
        y0 + 0.17 * (y1 - y0),
        "\u2190 System VMT increases",
        ha="right",
        va="bottom",
        fontsize=8.2,
        color="#555555",
        alpha=0.85,
    )
    ax.set_xlabel("System VMT reduction (%)", fontsize=10.5)
    ax.set_ylabel(r"System CO$_2$ reduction (%)", fontsize=10.5)
    ax.tick_params(axis="both", which="major", labelsize=9.0)
    ax.tick_params(axis="both", which="minor", labelsize=8.5)
    ax.grid(ls="--", alpha=0.30)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    ax.xaxis.set_minor_locator(AutoMinorLocator())
    savefig(fig, os.path.join(out_dir, "fleet_composition_tradeoff_system_vmt_co2"))


def _configured_vehicle_count(row):
    total = row.get("total_fleet_vehicles", np.nan)
    if pd.notna(total):
        return int(round(float(total)))

    count_cols = ["scooter_count", "moped_count", "car_count", "minibus_count"]
    if all(col in row.index and pd.notna(row.get(col)) for col in count_cols):
        return int(round(sum(float(row[col]) for col in count_cols)))

    return np.nan


def _format_table_value(value, decimals=1):
    if pd.isna(value):
        return ""
    return round(float(value), decimals)


def _latex_value(value, decimals=1):
    if value == "" or pd.isna(value):
        return ""
    return f"{float(value):.{decimals}f}"


def _write_representative_table_latex(table, tex_path):
    headers = [
        "Fleet role",
        "Seat shares",
        "Vehicles",
        "Service rate (\\%)",
        "Fallback private cars",
        "System VMT reduction (\\%)",
        "System \\COtwo{} reduction (\\%)",
    ]
    with open(tex_path, "w") as f:
        f.write("\\begin{tabular}{llrrrrr}\n")
        f.write("\\toprule\n")
        f.write(" & ".join(headers) + " \\\\\n")
        f.write("\\midrule\n")
        for _, row in table.iterrows():
            values = [
                row["Fleet role"],
                row["Seat shares"],
                str(row["Vehicles"]),
                _latex_value(row["Service rate (%)"]),
                _latex_value(row["Fallback private cars"]),
                _latex_value(row["System VMT reduction (%)"]),
                _latex_value(row["System CO2 reduction (%)"]),
            ]
            f.write(" & ".join(values) + " \\\\\n")
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")


def make_representative_table(df, results_dir):
    rows = []
    for rep, row in representative_rows(df):
        vehicles = _configured_vehicle_count(row)
        if pd.notna(vehicles) and vehicles != rep["expected_vehicles"]:
            print(
                f"  WARNING: {rep['label']} configured vehicle count is {vehicles}; "
                f"expected {rep['expected_vehicles']}."
            )
        rows.append({
            "Fleet role": rep["role"],
            "Seat shares": rep["seat_shares"],
            "Vehicles": vehicles,
            "Service rate (%)": _format_table_value(row.get("service_rate_mean", np.nan)),
            "Fallback private cars": _format_table_value(row.get("fallback_private_cars_mean", np.nan)),
            "System VMT reduction (%)": _format_table_value(row.get("system_vmt_reduction_pct_mean", np.nan)),
            "System CO2 reduction (%)": _format_table_value(row.get("system_co2_reduction_pct_mean", np.nan)),
        })

    table = pd.DataFrame(rows)
    csv_path = os.path.join(results_dir, "fleet_composition_representative_table.csv")
    tex_path = os.path.join(results_dir, "fleet_composition_representative_table.tex")
    table.to_csv(csv_path, index=False)
    _write_representative_table_latex(table, tex_path)
    print(f"  Representative table CSV: {csv_path}")
    print(f"  Representative table TeX: {tex_path}")
    return csv_path, tex_path


# ── Ranking tables ───────────────────────────────────────────────────────────

REPORT_COLS = [
    "condition",
    "label",
    "runs",
    "composition_label",
    "target_scooter_share", "target_moped_share",
    "target_car_share", "target_minibus_share",
    "scooter_count", "moped_count", "car_count", "minibus_count",
    "total_fleet_seats", "total_fleet_vehicles",
    "service_rate_mean",
    "service_rate_std",
    "served_commuters_mean",
    "served_commuters_std",
    "fallback_private_cars_mean",
    "fallback_private_cars_std",
    "late_deliveries_mean",
    "late_deliveries_std",
    "unserved_commuters_mean",
    "unserved_commuters_std",
    "system_vmt_change_pct_mean",
    "system_vmt_change_pct_std",
    "system_energy_change_pct_mean",
    "system_energy_change_pct_std",
    "system_co2_change_pct_mean",
    "system_co2_change_pct_std",
    "system_vmt_reduction_pct_mean",
    "system_vmt_reduction_pct_std",
    "system_energy_reduction_pct_mean",
    "system_energy_reduction_pct_std",
    "system_co2_reduction_pct_mean",
    "system_co2_reduction_pct_std",
    "system_total_vmt_km_mean",
    "system_total_vmt_km_std",
    "system_total_energy_kwh_mean",
    "system_total_energy_kwh_std",
    "system_total_co2_kg_mean",
    "system_total_co2_kg_std",
    "total_vmt_km_mean",
    "total_vmt_km_std",
    "total_energy_kwh_mean",
    "total_energy_kwh_std",
    "total_co2_kg_mean",
    "total_co2_kg_std",
    "avg_in_vehicle_time_min_mean",
    "avg_in_vehicle_time_min_std",
    "avg_wait_time_min_mean",
    "avg_wait_time_min_std",
    "avg_total_travel_time_min_mean",
    "avg_total_travel_time_min_std",
    "vehicle_trips_mean",
    "vehicle_trips_std",
    "pooling_rate_mean",
    "pooling_rate_std",
    "av_cost_per_served_commuter_mean",
    "av_cost_per_served_commuter_std",
    "av_cost_per_commuter_total_mean",
    "av_cost_per_commuter_total_std",
    "station_parking_reduction_pct_mean",
    "station_parking_reduction_pct_std",
    "net_parking_reduction_pct_if_fleet_stored_at_station_mean",
    "net_parking_reduction_pct_if_fleet_stored_at_station_std",
    "av_total_operating_cost_mean",
    "av_total_operating_cost_std",
    "avg_passengers_per_trip_mean",
    "avg_passengers_per_trip_std",
]


def make_service_first_table(df, out_dir):
    rel = optional_high_service_candidates(df)
    rel = rel.sort_values(
        [
            "service_rate_mean",
            "fallback_private_cars_mean",
            "system_vmt_reduction_pct_mean",
            "system_co2_reduction_pct_mean",
        ],
        ascending=[False, True, False, False],
    )

    existing = [c for c in REPORT_COLS if c in rel.columns]
    out_path = os.path.join(out_dir, "..", "top_service_first.csv")
    rel[existing].to_csv(out_path, index=False)
    print(f"  Optional high-service table ({len(rel)} rows): {out_path}")
    return rel


def make_practical_efficiency_table(df, out_dir):
    eff = optional_high_service_candidates(df)

    out_path = os.path.join(out_dir, "..", "top_efficiency_high_service.csv")
    eff = eff.sort_values(
        ["system_vmt_reduction_pct_mean", "system_co2_reduction_pct_mean"],
        ascending=False,
    )
    existing = [c for c in REPORT_COLS if c in eff.columns]
    eff[existing].to_csv(out_path, index=False)
    print(f"  Optional high-service efficiency table ({len(eff)} rows): {out_path}")
    return eff


# ── Console summary ───────────────────────────────────────────────────────────

def _row_summary(df, idx):
    r = df.loc[idx]
    return (
        f"{r['condition']:<35}  "
        f"service={r['service_rate_mean']:.1f}%  "
        f"fallback={r['fallback_private_cars_mean']:.1f}  "
        f"system VMT red={r['system_vmt_reduction_pct_mean']:.1f}%"
    )


def print_summary(df, missing):
    print(f"\n  Completed conditions : {len(df)}")
    print(f"  Missing conditions   : {len(missing)}")
    if missing:
        for m in missing:
            print(f"    {m}")

    service_min = df["service_rate_mean"].min()
    service_max = df["service_rate_mean"].max()
    print(f"\n  Service-rate range across grid: min = {service_min:.1f}%, max = {service_max:.1f}%")

    high_service = optional_high_service_candidates(df)

    print(f"\n  Optional high-service screening (service >= {HIGH_SERVICE_SCREENING_THRESHOLD:.1f}%)")
    if high_service.empty:
        print("  No optional high-service candidates found.")
    else:
        top_vmt = high_service.sort_values("system_vmt_reduction_pct_mean", ascending=False).head(5)
        print("  Top 5 by system VMT reduction:")
        for _, row in top_vmt.iterrows():
            print(f"    {row['condition']:<35} VMT={row['system_vmt_reduction_pct_mean']:.1f}%  service={row['service_rate_mean']:.1f}%  fallback={row['fallback_private_cars_mean']:.1f}")

    if not high_service.empty:
        top_service = high_service.sort_values("service_rate_mean", ascending=False).head(5)
        print("  Top 5 by service rate among optional high-service candidates:")
        for _, row in top_service.iterrows():
            print(f"    {row['condition']:<35} service={row['service_rate_mean']:.1f}%  VMT={row['system_vmt_reduction_pct_mean']:.1f}%  fallback={row['fallback_private_cars_mean']:.1f}")

    bal = df[df["condition"] == "comp_S25_M25_C25_MB25"]
    if not bal.empty:
        row = bal.iloc[0]
        print("\n  Balanced reference (comp_S25_M25_C25_MB25):")
        print(f"    service={row['service_rate_mean']:.1f}%  fallback={row['fallback_private_cars_mean']:.1f}  system VMT={row['system_vmt_reduction_pct_mean']:.1f}%  system CO2={row['system_co2_reduction_pct_mean']:.1f}%")

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
    print("  Service rate is the primary service metric under the current")
    print("  fallback framing.")
    print("  System metrics include AV service and fallback private-car trips.")
    print("  The all-car comparator is a homogeneous benchmark.")
    print("  The balanced heterogeneous fleet improves service rate, fallback")
    print("  private cars, system VMT reduction, and system CO2 reduction")
    print("  relative to all-car.")
    print("  Because all baseline, fallback, and AV vehicles are electric,")
    print("  CO2 reductions reflect distance, pooling, and vehicle energy")
    print("  intensity rather than drivetrain switching.")


def print_field_availability(availability):
    total_runs = availability["total_runs"]
    field_seen = availability["field_seen"]
    field_missing = availability["field_missing"]

    print("\n  ── Field availability ─────────────────────────────────────")
    for field in KEY_SECONDARY_FIELDS:
        print(
            f"  {field:<35} present in {field_seen.get(field, 0):>3}/"
            f"{total_runs:<3} runs"
        )

    missing_primary = [
        field for field in PRIMARY_REQUIRED_FIELDS
        if field_missing.get(field, 0) > 0
    ]
    if missing_primary:
        print("  WARNING: primary fields missing for at least one run:")
        for field in missing_primary:
            print(f"    {field}: missing {field_missing[field]}/{total_runs}")

    missing_optional = [
        field for field in EXTRA_NUMERIC_FIELDS + KEY_SECONDARY_FIELDS
        if field_seen.get(field, 0) == 0
    ]
    if missing_optional:
        print("  Optional fields unavailable in all runs:")
        for field in sorted(set(missing_optional)):
            print(f"    {field}")

    partial_optional = [
        field for field in EXTRA_NUMERIC_FIELDS + KEY_SECONDARY_FIELDS
        if 0 < field_seen.get(field, 0) < total_runs
    ]
    if partial_optional:
        print("  Optional fields missing in some runs:")
        for field in sorted(set(partial_optional)):
            print(f"    {field}: missing {field_missing[field]}/{total_runs}")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default=RESULTS_ROOT)
    p.add_argument("--configs-dir", default=None)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    configs_dir = args.configs_dir or os.path.join(args.results_dir, "configs")
    out_dir = args.out or os.path.join(args.results_dir, "plots")

    setup_pub_style()
    print("Aggregating fleet composition grid results...")
    df, missing, availability = aggregate(args.results_dir, configs_dir)

    if df.empty:
        print("ERROR: no data found. Check --results-dir path.")
        return

    csv_path = os.path.join(args.results_dir, "fleet_composition_grid_summary.csv")
    df.to_csv(csv_path, index=False)
    print(f"  Summary CSV: {csv_path}")

    print_summary(df, missing)
    print_field_availability(availability)

    print(f"\nGenerating plots -> {out_dir}")
    fig_combined(df, out_dir)
    fig_tradeoff(df, out_dir)
    fig_service_fallback(df, out_dir)
    fig_vmt_co2(df, out_dir)
    fig_system_tradeoff_representatives(df, out_dir)

    rep_csv_path, rep_tex_path = make_representative_table(df, args.results_dir)
    make_service_first_table(df, out_dir)
    make_practical_efficiency_table(df, out_dir)

    print("\nPaper-facing outputs:")
    print(f"  {os.path.join(out_dir, 'fleet_composition_tradeoff_system_vmt_co2.pdf')}")
    print(f"  {os.path.join(out_dir, 'fleet_composition_tradeoff_system_vmt_co2.png')}")
    print(f"  {rep_csv_path}")
    print(f"  {rep_tex_path}")

    print("\nDone — 1 combined + 4 individual figures + 4 tables.")


if __name__ == "__main__":
    main()
