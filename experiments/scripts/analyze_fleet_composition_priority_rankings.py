#!/usr/bin/env python3
"""
analyze_fleet_composition_priority_rankings.py
───────────────────────────────────────────────
Rank full-service fleet compositions from the existing 224-seat composition-grid
summary without rerunning the solver.

Priorities:
  1. Reliability-first
  2. VMT-oriented
  3. low-emission

Inputs:
  experiments/results/fleet_composition_grid_224seats/
    fleet_composition_grid_summary.csv

Outputs:
    experiments/results/analysis/priority_rankings/
    reliability_first_top_full_service.csv
    vmt_first_top_full_service.csv
    low_emission_first_top_full_service.csv
    priority_rankings_top5_combined.csv
    priority_rankings_latex_table.tex

The script is defensive about summary schemas, but it is anchored to the
current repository outputs:
  service_rate_mean
  effective_on_time_service_rate_mean
  vmt_reduction_pct_mean
  co2_reduction_pct_mean
  late_deliveries_mean
  avg_passengers_per_trip_mean
  target_*_share / actual_*_share
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

FULL_SERVICE_THRESHOLD = 99.9
DEFAULT_RESULTS_ROOT = Path("experiments/results/fleet_composition_grid_224seats")
DEFAULT_SUMMARY_CSV = DEFAULT_RESULTS_ROOT / "fleet_composition_grid_summary.csv"
DEFAULT_OUTPUT_DIR = Path("experiments/results/analysis/priority_rankings")


def _pick_existing_path(candidates: Iterable[Path]) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    candidate_list = "\n  - ".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Could not find a composition-grid summary CSV. Tried:\n  - {candidate_list}"
    )


def _find_summary_csv(results_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        if explicit.exists():
            return explicit
        raise FileNotFoundError(f"Summary CSV not found: {explicit}")

    candidates = [
        results_root / "fleet_composition_grid_summary.csv",
        DEFAULT_SUMMARY_CSV,
        Path("results/fleet_composition_grid_224seats/fleet_composition_grid_summary.csv"),
    ]
    return _pick_existing_path(candidates)


def _format_share(value: float | int | None) -> str:
    if pd.isna(value):
        return ""
    return f"{int(round(float(value)))}"


def _normalize_percent(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    finite = numeric.dropna()
    if finite.empty:
        return numeric
    if finite.max() <= 1.5:
        return numeric * 100.0
    return numeric


def _parse_condition_shares(condition: str) -> dict[str, float]:
    shares: dict[str, float] = {}
    if not isinstance(condition, str):
        return shares

    parts = condition.replace("comp_", "").split("_")
    for part in parts:
        if len(part) < 2:
            continue
        key = part[0].upper()
        try:
            value = float(part[1:])
        except ValueError:
            continue
        if key == "S":
            shares["scooter_share"] = value
        elif key == "M":
            shares["moped_share"] = value
        elif key == "C":
            shares["car_share"] = value
        elif key == "B":
            shares["minibus_share"] = value
    return shares


def _composition_label(row: pd.Series) -> str:
    share_cols = [
        ("scooter_share", ["target_scooter_share", "actual_scooter_share"]),
        ("moped_share", ["target_moped_share", "actual_moped_share"]),
        ("car_share", ["target_car_share", "actual_car_share"]),
        ("minibus_share", ["target_minibus_share", "actual_minibus_share"]),
    ]

    shares: dict[str, float] = {}
    for key, candidates in share_cols:
        for candidate in candidates:
            if candidate in row.index and pd.notna(row[candidate]):
                shares[key] = float(row[candidate])
                break

    if len(shares) < 4 and "condition" in row.index:
        shares.update(_parse_condition_shares(str(row["condition"])))

    if len(shares) < 4:
        return str(row.get("condition", ""))

    return "S{}/M{}/C{}/MB{}".format(
        _format_share(shares["scooter_share"]),
        _format_share(shares["moped_share"]),
        _format_share(shares["car_share"]),
        _format_share(shares["minibus_share"]),
    )


def load_summary(summary_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(summary_csv)
    df.columns = [col.strip() for col in df.columns]

    required = [
        "condition",
        "service_rate_mean",
        "effective_on_time_service_rate_mean",
        "vmt_reduction_pct_mean",
        "co2_reduction_pct_mean",
    ]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(
            f"Summary CSV is missing required columns: {missing}\n"
            f"Read from: {summary_csv}"
        )

    df = df.copy()
    df["service_rate_mean"] = _normalize_percent(df["service_rate_mean"])
    df["effective_on_time_service_rate_mean"] = _normalize_percent(
        df["effective_on_time_service_rate_mean"]
    )

    if "late_deliveries_mean" in df.columns and "late_arrivals_mean" not in df.columns:
        df["late_arrivals_mean"] = pd.to_numeric(df["late_deliveries_mean"], errors="coerce")

    if "avg_passengers_per_trip_mean" in df.columns:
        df["avg_passengers_per_trip_mean"] = pd.to_numeric(
            df["avg_passengers_per_trip_mean"], errors="coerce"
        )

    return df


def full_service_candidates(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["service_rate_mean"] >= FULL_SERVICE_THRESHOLD].copy()


def rank_candidates(df: pd.DataFrame, priority: str) -> pd.DataFrame:
    if priority == "reliability_first":
        sort_cols = [
            "effective_on_time_service_rate_mean",
            "vmt_reduction_pct_mean",
            "co2_reduction_pct_mean",
            "condition",
        ]
    elif priority == "vmt_first":
        sort_cols = [
            "vmt_reduction_pct_mean",
            "effective_on_time_service_rate_mean",
            "co2_reduction_pct_mean",
            "condition",
        ]
    elif priority == "low_emission_first":
        sort_cols = [
            "co2_reduction_pct_mean",
            "effective_on_time_service_rate_mean",
            "vmt_reduction_pct_mean",
            "condition",
        ]
    else:
        raise ValueError(f"Unknown priority: {priority}")

    ranked = df.sort_values(sort_cols, ascending=[False, False, False, True], kind="mergesort").copy()
    priority_label = {
        "reliability_first": "Reliability-first",
        "vmt_first": "VMT-oriented",
        "low_emission_first": "low-emission",
    }[priority]
    ranked.insert(0, "priority", priority_label)
    ranked.insert(1, "rank", range(1, len(ranked) + 1))
    ranked.insert(2, "fleet_composition_label", ranked.apply(_composition_label, axis=1))
    return ranked


def _output_columns(df: pd.DataFrame) -> list[str]:
    cols = [
        "priority",
        "rank",
        "condition",
        "fleet_composition_label",
        "target_scooter_share",
        "target_moped_share",
        "target_car_share",
        "target_minibus_share",
        "service_rate_mean",
        "effective_on_time_service_rate_mean",
        "vmt_reduction_pct_mean",
        "co2_reduction_pct_mean",
    ]
    optional = ["late_arrivals_mean", "avg_passengers_per_trip_mean"]
    for col in optional:
        if col in df.columns:
            cols.append(col)
    return [col for col in cols if col in df.columns]


def _prepare_export_frame(df: pd.DataFrame) -> pd.DataFrame:
    export = df.copy()
    for col in [
        "target_scooter_share",
        "target_moped_share",
        "target_car_share",
        "target_minibus_share",
    ]:
        if col in export.columns:
            export[col] = pd.to_numeric(export[col], errors="coerce")
    return export


def _format_optional_number(value: float | int | None, digits: int = 1) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.{digits}f}"


def write_csv_outputs(ranked: dict[str, pd.DataFrame], output_dir: Path) -> pd.DataFrame:
    output_dir.mkdir(parents=True, exist_ok=True)

    file_map = {
        "reliability_first": "reliability_first_top_full_service.csv",
        "vmt_first": "vmt_first_top_full_service.csv",
        "low_emission_first": "low_emission_first_top_full_service.csv",
    }

    combined_rows = []
    for priority, frame in ranked.items():
        top5 = _prepare_export_frame(frame.head(5)).copy()
        top5.to_csv(output_dir / file_map[priority], index=False)
        combined_rows.append(top5)

    combined_df = pd.concat(combined_rows, ignore_index=True)
    combined_df = combined_df[_output_columns(combined_df)]
    combined_df.to_csv(output_dir / "priority_rankings_top5_combined.csv", index=False)
    return combined_df


def build_latex_table(ranked: dict[str, pd.DataFrame], output_path: Path) -> None:
    lines = [
        r"\begin{table}[t]",
        r"\centering",
        r"\small",
        r"\setlength{\tabcolsep}{3.5pt}",
        r"\renewcommand{\arraystretch}{1.08}",
        r"\begin{tabular}{r l r r r r}",
        r"\toprule",
        r"Rank & Fleet composition & Service (\%) & Eff. on-time (\%) & VMT red. (\%) & \COtwo{} red. (\%) \\",
        r"\midrule",
    ]

    priority_titles = {
        "reliability_first": r"\multicolumn{6}{l}{\textbf{Reliability-first}} \\",
        "vmt_first": r"\multicolumn{6}{l}{\textbf{VMT-oriented}} \\",
        "low_emission_first": r"\multicolumn{6}{l}{\textbf{Low-emission}} \\",
    }

    for priority, title in priority_titles.items():
        frame = ranked[priority].head(3)
        lines.append(title)
        for _, row in frame.iterrows():
            lines.append(
                f"{int(row['rank'])} & {row['fleet_composition_label']} & "
                f"{_format_optional_number(row['service_rate_mean'], 1)} & "
                f"{_format_optional_number(row['effective_on_time_service_rate_mean'], 1)} & "
                f"{_format_optional_number(row['vmt_reduction_pct_mean'], 1)} & "
                f"{_format_optional_number(row['co2_reduction_pct_mean'], 1)} \\\\"
            )
        lines.append(r"\addlinespace[2pt]")

    lines.extend([
        r"\bottomrule",
        r"\end{tabular}",
        r"\caption{Top full-service fleet compositions under three planning priorities.}",
        r"\label{tab:priority_rankings_top3}",
        r"\end{table}",
        "",
    ])

    output_path.write_text("\n".join(lines))


def print_console_summary(ranked: dict[str, pd.DataFrame], total_compositions: int, full_service_count: int) -> None:
    bests = {priority: frame.iloc[0] for priority, frame in ranked.items() if not frame.empty}
    same_winner = len({row["condition"] for row in bests.values()}) == 1 if bests else False

    print(f"Total compositions: {total_compositions}")
    print(f"Full-service compositions: {full_service_count}")

    for priority, pretty_name in [
        ("reliability_first", "Reliability-first"),
        ("vmt_first", "VMT-first"),
        ("low_emission_first", "Low-emission-first"),
    ]:
        row = bests[priority]
        print(
            f"Best {pretty_name}: {row['fleet_composition_label']} "
            f"(service={row['service_rate_mean']:.1f}%, "
            f"effOT={row['effective_on_time_service_rate_mean']:.1f}%, "
            f"VMT={row['vmt_reduction_pct_mean']:.1f}%, "
            f"CO2={row['co2_reduction_pct_mean']:.1f}%)"
        )

    if same_winner:
        winner = next(iter(bests.values()))
        print(f"Same composition wins all three rankings: yes ({winner['fleet_composition_label']})")
    else:
        print("Same composition wins all three rankings: no")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--summary-csv", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    summary_csv = _find_summary_csv(args.results_root, args.summary_csv)
    df = load_summary(summary_csv)
    full_service = full_service_candidates(df)

    if full_service.empty:
        print(f"Summary CSV: {summary_csv}")
        print("No full-service compositions found at the 99.9% threshold.")
        return

    ranked = {
        "reliability_first": rank_candidates(full_service, "reliability_first"),
        "vmt_first": rank_candidates(full_service, "vmt_first"),
        "low_emission_first": rank_candidates(full_service, "low_emission_first"),
    }

    combined_df = write_csv_outputs(ranked, args.output_dir)
    build_latex_table(ranked, args.output_dir / "priority_rankings_latex_table.tex")

    print(f"Summary CSV: {summary_csv}")
    print(f"Output directory: {args.output_dir}")
    print_console_summary(ranked, total_compositions=len(df), full_service_count=len(full_service))
    print(f"Combined top-5 rows written: {len(combined_df)}")


if __name__ == "__main__":
    main()