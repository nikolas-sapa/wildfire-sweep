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
    "mode",
    "airspeed_mps",
    "wind_east_mps",
    "n_bases",
    "drones_per_base",
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
    "rejected_share",
    "eur_per_km2_yr",
)
NUMERIC_COLUMNS = tuple(column for column in REQUIRED_COLUMNS if column != "mode")
SHARE_COLUMNS = (
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
    "rejected_share",
)
AIR_SPEEDS = (18, 20)
WIND_VALUES = (0, 4, 8, 12)
CONFIGURATIONS = ((4, 2), (9, 1), (25, 1), (49, 1))
COLORS = {
    (4, 2): "#006bff",
    (9, 1): "#16a34a",
    (25, 1): "#7c3aed",
    (49, 1): "#64748b",
}
TITLE = "Synthetic network study: wind, reserve and response"
FOOTER = (
    "Uniform synthetic alerts; fixed wind; Monte Carlo intervals only. "
    "Not field validation."
)


def read_physical_summary(
    summary_path: Path,
) -> dict[tuple[float, float, float, float], dict[str, float]]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("summary CSV has no header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("summary CSV has duplicate columns")
        missing_columns = sorted(set(REQUIRED_COLUMNS) - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(f"summary CSV missing columns: {missing_columns}")

        rows: dict[tuple[float, float, float, float], dict[str, float]] = {}
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"summary CSV row {row_number} has extra values")
            mode = (row.get("mode") or "").strip()
            if not mode:
                raise ValueError(f"summary CSV row {row_number} has no mode")
            if mode != "physical":
                continue

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
                raise ValueError(f"summary CSV row {row_number} has reversed confidence bounds")
            if (
                values["within_15min_share"] + values["rejected_share"]
                > 1 + 1e-12
            ):
                raise ValueError(
                    f"summary CSV row {row_number} has shares exceeding one"
                )
            if values["eur_per_km2_yr"] < 0:
                raise ValueError(f"summary CSV row {row_number} has a negative cost")

            key = (
                values["airspeed_mps"],
                values["wind_east_mps"],
                values["n_bases"],
                values["drones_per_base"],
            )
            if key in rows:
                raise ValueError(f"duplicate physical scenario group: {key}")
            rows[key] = values

    expected = {
        (float(airspeed), float(wind), float(bases), float(drones))
        for airspeed in AIR_SPEEDS
        for wind in WIND_VALUES
        for bases, drones in CONFIGURATIONS
    }
    missing_groups = sorted(expected - rows.keys())
    extra_groups = sorted(rows.keys() - expected)
    if missing_groups or extra_groups:
        raise ValueError(
            f"summary CSV physical scenario groups differ from expected; "
            f"missing={missing_groups}, extra={extra_groups}"
        )
    for bases, drones in CONFIGURATIONS:
        configuration = (float(bases), float(drones))
        reference_key = (18.0, 0.0, *configuration)
        reference_cost = rows[reference_key]["eur_per_km2_yr"]
        for key, row in rows.items():
            if key[2:] == configuration and not math.isclose(
                row["eur_per_km2_yr"],
                reference_cost,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError(f"physical scenario group {key} has inconsistent cost")
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


def render_study(summary_path: Path, output_path: Path) -> None:
    validate_output_path(output_path)
    rows = read_physical_summary(summary_path)
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True, sharey=True)
    figure.suptitle(TITLE, fontsize=17, fontweight="semibold", color="#111827")

    for row_index, airspeed in enumerate(AIR_SPEEDS):
        for column_index, metric in enumerate(("within_15min_share", "rejected_share")):
            axis = axes[row_index, column_index]
            title = "Within 15 min" if column_index == 0 else "Rejected share"
            axis.set_title(f"{title} at {airspeed} m/s", loc="left", pad=10)
            axis.set_ylabel("Share (%)")
            axis.set_ylim(0, 100)
            axis.set_yticks(range(0, 101, 20))
            axis.set_xticks(WIND_VALUES)
            axis.set_xlim(-0.5, 12.5)
            axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
            axis.set_axisbelow(True)
            for spine in axis.spines.values():
                spine.set_color("#d1d5db")

            for bases, drones in CONFIGURATIONS:
                series = [
                    rows[(float(airspeed), float(wind), float(bases), float(drones))]
                    for wind in WIND_VALUES
                ]
                values = [row[metric] * 100 for row in series]
                label_row = rows[(18.0, 0.0, float(bases), float(drones))]
                cost = label_row["eur_per_km2_yr"]
                label = (
                    f"{bases} bases, {drones} drones/base · "
                    f"{cost:,.0f} EUR/km²/yr"
                )
                color = COLORS[(bases, drones)]

                if column_index == 0:
                    lows = [row["mc_95ci_low"] * 100 for row in series]
                    highs = [row["mc_95ci_high"] * 100 for row in series]
                    axis.fill_between(
                        WIND_VALUES,
                        lows,
                        highs,
                        color=color,
                        alpha=0.16,
                        linewidth=0,
                    )
                axis.plot(
                    WIND_VALUES,
                    values,
                    color=color,
                    linewidth=2,
                    marker="o",
                    markersize=4,
                    label=label,
                )

            axis.set_xlabel("Wind (m/s)")

    handles, labels = axes[0, 0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.065),
        ncol=2,
        frameon=False,
    )
    figure.text(0.5, 0.015, FOOTER, ha="center", fontsize=9, color="#475569")
    figure.tight_layout(rect=(0.035, 0.13, 0.98, 0.92))

    image = io.BytesIO()
    try:
        figure.savefig(image, format="png", dpi=180, facecolor="white")
        write_new_png(output_path, image.getvalue())
    finally:
        plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("summary_csv", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        render_study(arguments.summary_csv, arguments.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
