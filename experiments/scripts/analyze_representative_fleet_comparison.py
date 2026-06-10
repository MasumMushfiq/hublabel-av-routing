#!/usr/bin/env python3
"""
Build a compact paper-facing comparison table for selected representative fleets.

The script reads an existing fleet-composition-grid summary and extracts only the
four representative fleets used in the SIGSPATIAL 2026 AV feeder paper framing.
It does not rerun simulations or modify experiment outputs.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Iterable


DEFAULT_INPUT_CSV = Path(
    "experiments/results/fleet_composition_grid_224seats/fleet_composition_grid_summary.csv"
)
DEFAULT_OUTPUT_DIR = Path(
    "experiments/results/analysis/representative_fleet_comparison"
)

REPRESENTATIVE_FLEETS = [
    {
        "role": "All-car comparator",
        "condition": "comp_S0_M0_C100_MB0",
        "vehicles": 56,
    },
    {
        "role": "Balanced",
        "condition": "comp_S25_M25_C25_MB25",
        "vehicles": 105,
    },
    {
        "role": "VMT-oriented",
        "condition": "comp_S25_M0_C0_MB75",
        "vehicles": 77,
    },
    {
        "role": "Low-emission",
        "condition": "comp_S25_M75_C0_MB0",
        "vehicles": 140,
    },
]

REQUIRED_FIELDS = {
    "condition": "condition",
    "service_rate": "service_rate_mean",
    "fallback_private_cars": "fallback_private_cars_mean",
}

OPTIONAL_FIELD_CANDIDATES = {
    "ivt": [
        "avg_in_vehicle_time_min_mean",
        "average_in_vehicle_time_min_mean",
        "mean_in_vehicle_time_min_mean",
    ],
    "parking": [
        "station_parking_reduction_pct_mean",
        "station_commuter_parking_reduction_pct_mean",
        "station_parking_reduction_pct",
        "station_commuter_parking_reduction_pct",
    ],
    "cost": [
        "av_total_operating_cost_mean",
        "av_total_operating_cost",
    ],
}

OUTPUT_CSV_NAME = "representative_fleet_comparison.csv"
OUTPUT_TEX_NAME = "representative_fleet_comparison.tex"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract representative fleet comparison rows from a grid summary."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_CSV,
        help=f"Input summary CSV (default: {DEFAULT_INPUT_CSV})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    return parser.parse_args()


def read_summary(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Input summary CSV not found: {path}")

    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"Input summary CSV has no header: {path}")
        reader.fieldnames = [field.strip() for field in reader.fieldnames]
        return [{key.strip(): value for key, value in row.items()} for row in reader]


def require_fields(rows: list[dict[str, str]], fields: Iterable[str]) -> None:
    if not rows:
        raise ValueError("Input summary CSV contains no rows.")
    columns = set(rows[0])
    missing = [field for field in fields if field not in columns]
    if missing:
        raise ValueError(f"Input summary CSV is missing required columns: {missing}")


def choose_optional_field(rows: list[dict[str, str]], candidates: list[str]) -> str | None:
    columns = set(rows[0])
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def choose_system_reduction_field(
    rows: list[dict[str, str]],
    reduction_field: str,
    change_field: str,
    label: str,
) -> tuple[str, bool]:
    columns = set(rows[0])
    if reduction_field in columns:
        return reduction_field, False
    if change_field in columns:
        return change_field, True
    raise ValueError(
        f"Input summary CSV is missing system-level {label} reduction/change columns: "
        f"{reduction_field} or {change_field}"
    )


def to_float(value: str | float | int | None) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip()
    if not text:
        return math.nan
    return float(text)


def normalize_percent(value: float) -> float:
    if math.isnan(value):
        return value
    if abs(value) <= 1.5:
        return value * 100.0
    return value


def format_float(value: float, digits: int = 1) -> str:
    if math.isnan(value):
        return ""
    return f"{value:.{digits}f}"


def format_count(value: float) -> str:
    if math.isnan(value):
        return ""
    return f"{value:.0f}"


def parse_seat_shares(condition: str) -> str:
    match = re.fullmatch(r"comp_S(?P<s>\d+)_M(?P<m>\d+)_C(?P<c>\d+)_MB(?P<mb>\d+)", condition)
    if not match:
        return condition
    return "S{}/M{}/C{}/MB{}".format(
        match.group("s"),
        match.group("m"),
        match.group("c"),
        match.group("mb"),
    )


def latex_escape(text: str) -> str:
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def build_rows(
    summary_rows: list[dict[str, str]],
    vmt_field: str,
    derive_vmt_reduction: bool,
    co2_field: str,
    derive_co2_reduction: bool,
    ivt_field: str | None,
    parking_field: str | None,
    cost_field: str | None,
) -> list[dict[str, str]]:
    rows_by_condition = {row["condition"]: row for row in summary_rows}
    missing = [
        fleet["condition"]
        for fleet in REPRESENTATIVE_FLEETS
        if fleet["condition"] not in rows_by_condition
    ]
    if missing:
        raise ValueError(f"Representative fleets not found in summary CSV: {missing}")

    output_rows: list[dict[str, str]] = []
    for fleet in REPRESENTATIVE_FLEETS:
        source = rows_by_condition[fleet["condition"]]
        service_rate = normalize_percent(to_float(source["service_rate_mean"]))
        fallback_private_cars = to_float(source["fallback_private_cars_mean"])

        vmt_reduction = normalize_percent(to_float(source[vmt_field]))
        if derive_vmt_reduction:
            vmt_reduction = -vmt_reduction

        co2_reduction = normalize_percent(to_float(source[co2_field]))
        if derive_co2_reduction:
            co2_reduction = -co2_reduction

        output = {
            "Fleet role": fleet["role"],
            "Seat shares": parse_seat_shares(fleet["condition"]),
            "Vehicles": str(fleet["vehicles"]),
            "Service rate (%)": format_float(service_rate),
            "Fallback private cars": format_count(fallback_private_cars),
            "System VMT reduction (%)": format_float(vmt_reduction),
            "System CO2 reduction (%)": format_float(co2_reduction),
        }

        if ivt_field is not None:
            output["Average in-vehicle time (min)"] = format_float(
                to_float(source[ivt_field])
            )
        if parking_field is not None:
            output["Station commuter parking reduction (%)"] = format_float(
                normalize_percent(to_float(source[parking_field]))
            )
        if cost_field is not None:
            output["AV total operating cost (AUD)"] = format_float(
                to_float(source[cost_field]), digits=0
            )

        output_rows.append(output)

    return output_rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_latex(path: Path, rows: list[dict[str, str]]) -> None:
    headers = list(rows[0].keys())
    latex_headers = [
        "Fleet role",
        "Seat shares",
        "Veh.",
        "Service (\\%)",
        "Fallback private cars",
        "System VMT red. (\\%)",
        "System \\COtwo{} red. (\\%)",
    ]
    if "Average in-vehicle time (min)" in headers:
        latex_headers.append("Avg. IVT (min)")
    if "Station commuter parking reduction (%)" in headers:
        latex_headers.append("Station parking red. (\\%)")
    if "AV total operating cost (AUD)" in headers:
        latex_headers.append("AV op. cost (AUD)")

    column_spec = "l l r r r r r" + " r" * (len(latex_headers) - 7)
    lines = [
        r"\begin{table*}[t]",
        r"\centering",
        r"\caption{Representative fleet comparison.}",
        r"\label{tab:representative-fleet-comparison}",
        rf"\begin{{tabular}}{{{column_spec}}}",
        r"\toprule",
        " & ".join(latex_headers) + r" \\",
        r"\midrule",
    ]

    for row in rows:
        values = [
            latex_escape(row["Fleet role"]),
            latex_escape(row["Seat shares"]),
            row["Vehicles"],
            row["Service rate (%)"],
            row["Fallback private cars"],
            row["System VMT reduction (%)"],
            row["System CO2 reduction (%)"],
        ]
        if "Average in-vehicle time (min)" in row:
            values.append(row["Average in-vehicle time (min)"])
        if "Station commuter parking reduction (%)" in row:
            values.append(row["Station commuter parking reduction (%)"])
        if "AV total operating cost (AUD)" in row:
            values.append(row["AV total operating cost (AUD)"])
        lines.append(" & ".join(values) + r" \\")

    lines.extend([r"\bottomrule", r"\end{tabular}", r"\end{table*}", ""])
    path.write_text("\n".join(lines))


def main() -> None:
    args = parse_args()
    rows = read_summary(args.input)
    require_fields(rows, REQUIRED_FIELDS.values())

    vmt_field, derive_vmt_reduction = choose_system_reduction_field(
        rows,
        "system_vmt_reduction_pct_mean",
        "system_vmt_change_pct_mean",
        "VMT",
    )
    co2_field, derive_co2_reduction = choose_system_reduction_field(
        rows,
        "system_co2_reduction_pct_mean",
        "system_co2_change_pct_mean",
        "CO2",
    )

    ivt_field = choose_optional_field(rows, OPTIONAL_FIELD_CANDIDATES["ivt"])
    parking_field = choose_optional_field(rows, OPTIONAL_FIELD_CANDIDATES["parking"])
    cost_field = choose_optional_field(rows, OPTIONAL_FIELD_CANDIDATES["cost"])

    output_rows = build_rows(
        rows,
        vmt_field,
        derive_vmt_reduction,
        co2_field,
        derive_co2_reduction,
        ivt_field,
        parking_field,
        cost_field,
    )

    output_csv = args.output_dir / OUTPUT_CSV_NAME
    output_tex = args.output_dir / OUTPUT_TEX_NAME
    write_csv(output_csv, output_rows)
    write_latex(output_tex, output_rows)

    print("All four representative fleets were found.")
    print(f"Wrote CSV: {output_csv}")
    print(f"Wrote LaTeX: {output_tex}")
    print(f"Service field: {REQUIRED_FIELDS['service_rate']}")
    print(f"Fallback private cars field: {REQUIRED_FIELDS['fallback_private_cars']}")
    print(
        "System VMT reduction field: "
        f"{vmt_field}{' (derived as negative change)' if derive_vmt_reduction else ''}"
    )
    print(
        "System CO2 reduction field: "
        f"{co2_field}{' (derived as negative change)' if derive_co2_reduction else ''}"
    )
    print(f"IVT field used: {ivt_field or 'unavailable'}")
    print(f"Parking field used: {parking_field or 'unavailable'}")
    print(f"Cost field used: {cost_field or 'unavailable'}")
    if ivt_field is None:
        print("WARNING: Average in-vehicle time is unavailable; omitted from outputs.")
    if parking_field is None:
        print(
            "WARNING: Station commuter parking reduction is unavailable; "
            "omitted from outputs."
        )
    if cost_field is None:
        print(
            "WARNING: AV total operating cost is unavailable; omitted from outputs."
        )


if __name__ == "__main__":
    main()
