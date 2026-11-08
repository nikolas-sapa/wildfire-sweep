import argparse
import csv
import io
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

REQUIRED_COLUMNS = (
    "scenario",
    "condition",
    "provenance",
    "nominal_spacing_km",
    "n_bases",
    "drones_per_base",
    "wind_east_mps",
    "airspeed_mps",
    "endurance_min",
    "reserve_fraction",
    "launch_latency_s",
    "endurance_stress",
    "launch_stress",
    "reserve_stress",
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
)
NUMERIC_COLUMNS = tuple(
    column
    for column in REQUIRED_COLUMNS
    if column not in ("scenario", "condition", "provenance")
)
SHARE_COLUMNS = ("within_15min_share", "mc_95ci_low", "mc_95ci_high")
BIT_COLUMNS = ("endurance_stress", "launch_stress", "reserve_stress")
LAYOUTS = {9: 16.0, 25: 12.0}
WINDS = (8.0, 12.0)
PROVENANCES = ("reused", "simulated")
FACTOR_CELLS = {
    (0, 0, 0): ("reference", "reused", "Ref"),
    (1, 0, 0): ("shorter_endurance", "reused", "E"),
    (0, 1, 0): ("slower_launch", "reused", "L"),
    (0, 0, 1): ("larger_reserve", "reused", "R"),
    (1, 1, 0): ("endurance_launch", "simulated", "E+L"),
    (1, 0, 1): ("endurance_reserve", "simulated", "E+R"),
    (0, 1, 1): ("launch_reserve", "simulated", "L+R"),
    (1, 1, 1): ("combined", "reused", "E+L+R"),
}
KNOWN_CONDITIONS = tuple(sorted({cell[0] for cell in FACTOR_CELLS.values()}))
CELL_ORDER = (
    (0, 0, 0),
    (1, 0, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 1, 0),
    (1, 0, 1),
    (0, 1, 1),
    (1, 1, 1),
)
CONDITION_LABELS = tuple(FACTOR_CELLS[bits][2] for bits in CELL_ORDER)
PROVENANCE_STYLE = {
    "reused": {"marker": "o", "color": "#006bff", "label": "Reused capture"},
    "simulated": {"marker": "s", "color": "#1e3a5f", "label": "Newly simulated"},
}
TITLE = "Full-factorial stress cube: within-15-minute alert-to-arrival share"
FOOTER_FACTORS = (
    "Stresses vs reference: E endurance 34.5 vs 46 min | "
    "L launch 180 vs 60 s | R reserve 35% vs 25%"
)
FOOTER = (
    "Synthetic fixed-wind assumptions | 18 m/s airspeed | "
    "Pointwise 95% Monte Carlo intervals | Not field validation."
)


def read_factorial_summary(
    summary_path: Path,
) -> dict[tuple[int, float, tuple[int, int, int]], dict[str, float]]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("summary CSV has no header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("summary CSV has duplicate columns")
        missing_columns = sorted(set(REQUIRED_COLUMNS) - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(f"summary CSV missing columns: {missing_columns}")

        rows: dict[tuple[int, float, tuple[int, int, int]], dict[str, float]] = {}
        scenario_ids = set()
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"summary CSV row {row_number} has extra values")
            scenario = (row.get("scenario") or "").strip()
            condition = (row.get("condition") or "").strip()
            provenance = (row.get("provenance") or "").strip()
            if not scenario:
                raise ValueError(f"summary CSV row {row_number} has no scenario ID")
            if condition not in KNOWN_CONDITIONS:
                raise ValueError(
                    f"summary CSV row {row_number} has unknown condition: {condition}"
                )
            if provenance not in PROVENANCES:
                raise ValueError(
                    f"summary CSV row {row_number} has unknown provenance: {provenance}"
                )

            values: dict[str, float] = {}
            for column in NUMERIC_COLUMNS:
                try:
                    value = float(row[column])
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"summary CSV row {row_number} has an invalid {column}"
                    ) from error
                if not math.isfinite(value):
                    raise ValueError(
                        f"summary CSV row {row_number} has a nonfinite {column}"
                    )
                values[column] = value

            for column in SHARE_COLUMNS:
                if not 0 <= values[column] <= 1:
                    raise ValueError(
                        f"summary CSV row {row_number} has an out-of-range {column}"
                    )
            if values["mc_95ci_low"] > values["mc_95ci_high"]:
                raise ValueError(
                    f"summary CSV row {row_number} has reversed confidence bounds"
                )

            bits: list[int] = []
            for column in BIT_COLUMNS:
                bit_value = values[column]
                if not bit_value.is_integer() or bit_value not in (0.0, 1.0):
                    raise ValueError(
                        f"summary CSV row {row_number} has an invalid {column}"
                    )
                bits.append(int(bit_value))
            bits_key = (bits[0], bits[1], bits[2])
            expected_condition, expected_provenance, _ = FACTOR_CELLS[bits_key]
            if condition != expected_condition:
                raise ValueError(
                    f"summary CSV row {row_number} has inconsistent condition"
                )
            if provenance != expected_provenance:
                raise ValueError(
                    f"summary CSV row {row_number} has inconsistent provenance"
                )

            n_bases_value = values["n_bases"]
            if not n_bases_value.is_integer():
                raise ValueError(f"summary CSV row {row_number} has noninteger n_bases")
            n_bases = int(n_bases_value)
            wind = values["wind_east_mps"]
            if n_bases not in LAYOUTS or wind not in WINDS:
                raise ValueError(
                    f"summary CSV row {row_number} has unexpected layout or wind"
                )

            expected_scenario = (
                f"b{n_bases}-w{int(wind)}-e{bits[0]}-l{bits[1]}-r{bits[2]}"
            )
            if scenario != expected_scenario:
                raise ValueError(
                    f"summary CSV row {row_number} has inconsistent scenario ID"
                )
            endurance_stress, launch_stress, reserve_stress = bits_key
            expected_metadata = {
                "nominal_spacing_km": LAYOUTS[n_bases],
                "n_bases": float(n_bases),
                "drones_per_base": 1.0,
                "wind_east_mps": wind,
                "airspeed_mps": 18.0,
                "endurance_min": 34.5 if endurance_stress else 46.0,
                "reserve_fraction": 0.35 if reserve_stress else 0.25,
                "launch_latency_s": 180.0 if launch_stress else 60.0,
            }
            for column, expected_value in expected_metadata.items():
                if not math.isclose(
                    values[column],
                    expected_value,
                    rel_tol=0,
                    abs_tol=1e-12,
                ):
                    raise ValueError(
                        f"summary CSV row {row_number} has inconsistent {column}"
                    )

            key = (n_bases, wind, bits_key)
            if key in rows or scenario in scenario_ids:
                raise ValueError(f"duplicate factorial scenario: {scenario}")
            rows[key] = values
            scenario_ids.add(scenario)

    expected = {
        (n_bases, wind, bits)
        for n_bases in LAYOUTS
        for wind in WINDS
        for bits in CELL_ORDER
    }
    missing = sorted(expected - rows.keys())
    extra = sorted(rows.keys() - expected)
    if missing or extra:
        raise ValueError(f"summary CSV scenario grid mismatch; missing={missing}, extra={extra}")
    return rows


def validate_output_path(output_path: Path) -> None:
    if output_path.suffix.lower() != ".png":
        raise ValueError("output path must have a .png suffix")
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(f"output parent directory does not exist: {output_path.parent}")


def write_new_png(output_path: Path, image: bytes) -> None:
    descriptor = os.open(
        output_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(image)


def render(summary_path: Path, output_path: Path) -> None:
    validate_output_path(output_path)
    rows = read_factorial_summary(summary_path)
    figure, axes = plt.subplots(2, 2, figsize=(14, 9), sharex=True, sharey=True)
    figure.suptitle(TITLE, fontsize=17, fontweight="semibold", color="#14243a")

    for row_index, n_bases in enumerate(LAYOUTS):
        for column_index, wind in enumerate(WINDS):
            axis = axes[row_index][column_index]
            axis.set_title(
                f"{n_bases} bases | {int(wind)} m/s east wind", loc="left", pad=12
            )
            axis.set_ylim(-2, 102)
            axis.set_yticks(range(0, 101, 20))
            axis.set_xticks(range(len(CELL_ORDER)))
            axis.set_xticklabels(CONDITION_LABELS, fontsize=9)
            axis.set_xlim(-0.6, len(CELL_ORDER) - 0.4)
            axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
            axis.set_axisbelow(True)
            for spine in axis.spines.values():
                spine.set_color("#d1d5db")
            if column_index == 0:
                axis.set_ylabel("Within 15 min (%)")
            if row_index == 1:
                axis.set_xlabel("Stress combination")

            cap_width = 0.12
            for index, bits in enumerate(CELL_ORDER):
                record = rows[(n_bases, wind, bits)]
                timely = record["within_15min_share"] * 100
                low = record["mc_95ci_low"] * 100
                high = record["mc_95ci_high"] * 100
                style = PROVENANCE_STYLE[FACTOR_CELLS[bits][1]]
                color = style["color"]
                axis.vlines(
                    [index],
                    [low],
                    [high],
                    color=color,
                    linewidth=1.5,
                    zorder=2,
                )
                axis.hlines(
                    [low, high],
                    index - cap_width,
                    index + cap_width,
                    color=color,
                    linewidth=1.2,
                    zorder=2,
                )
                axis.scatter(
                    [index],
                    [timely],
                    color=color,
                    marker=style["marker"],
                    s=42,
                    zorder=3,
                )

    legend_handles = [
        plt.Line2D(
            [0],
            [0],
            marker=style["marker"],
            color="none",
            markerfacecolor=style["color"],
            markeredgecolor=style["color"],
            markersize=8,
            label=style["label"],
        )
        for style in PROVENANCE_STYLE.values()
    ]
    figure.legend(
        handles=legend_handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.085),
        ncol=2,
        frameon=False,
    )
    figure.text(0.5, 0.048, FOOTER_FACTORS, ha="center", fontsize=11, color="#334155")
    figure.text(0.5, 0.015, FOOTER, ha="center", fontsize=11, color="#334155")
    figure.tight_layout(rect=(0.03, 0.14, 0.99, 0.92))

    image = io.BytesIO()
    try:
        figure.savefig(image, format="png", dpi=180, facecolor="white")
        write_new_png(output_path, image.getvalue())
    finally:
        plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        render(arguments.summary, arguments.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
