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
    "nominal_spacing_km",
    "n_bases",
    "drones_per_base",
    "wind_east_mps",
    "airspeed_mps",
    "endurance_min",
    "reserve_fraction",
    "launch_latency_s",
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
)
NUMERIC_COLUMNS = tuple(column for column in REQUIRED_COLUMNS if column not in ("scenario", "condition"))
SHARE_COLUMNS = ("within_15min_share", "mc_95ci_low", "mc_95ci_high")
LAYOUTS = {9: 16.0, 25: 12.0}
WINDS = (8.0, 12.0)
CONDITIONS = (
    "reference",
    "shorter_endurance",
    "slower_launch",
    "larger_reserve",
    "combined",
)
CONDITION_SETTINGS = {
    "reference": (46.0, 0.25, 60.0),
    "shorter_endurance": (34.5, 0.25, 60.0),
    "slower_launch": (46.0, 0.25, 180.0),
    "larger_reserve": (46.0, 0.35, 60.0),
    "combined": (34.5, 0.35, 180.0),
}
CONDITION_LABELS = (
    "Reference",
    "Shorter\nendurance",
    "Slower\nlaunch",
    "Larger\nreserve",
    "Combined",
)
WIND_COLORS = {8.0: "#006bff", 12.0: "#1e3a5f"}
TITLE = "Assumption robustness: within-15-minute alert-to-arrival share"
FOOTER = (
    "Synthetic fixed-wind stress assumptions | 18 m/s airspeed | "
    "Pointwise 95% Monte Carlo intervals | Not field validation."
)


def read_robustness_summary(
    summary_path: Path,
) -> dict[tuple[int, float, str], dict[str, float]]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("summary CSV has no header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("summary CSV has duplicate columns")
        missing_columns = sorted(set(REQUIRED_COLUMNS) - set(reader.fieldnames))
        if missing_columns:
            raise ValueError(f"summary CSV missing columns: {missing_columns}")

        rows: dict[tuple[int, float, str], dict[str, float]] = {}
        scenario_ids = set()
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"summary CSV row {row_number} has extra values")
            scenario = (row.get("scenario") or "").strip()
            condition = (row.get("condition") or "").strip()
            if not scenario:
                raise ValueError(f"summary CSV row {row_number} has no scenario ID")
            if condition not in CONDITION_SETTINGS:
                raise ValueError(
                    f"summary CSV row {row_number} has unknown condition: {condition}"
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

            n_bases_value = values["n_bases"]
            if not n_bases_value.is_integer():
                raise ValueError(f"summary CSV row {row_number} has noninteger n_bases")
            n_bases = int(n_bases_value)
            wind = values["wind_east_mps"]
            if n_bases not in LAYOUTS or wind not in WINDS:
                raise ValueError(
                    f"summary CSV row {row_number} has unexpected layout or wind"
                )

            expected_scenario = f"b{n_bases}-w{int(wind)}-{condition}"
            if scenario != expected_scenario:
                raise ValueError(
                    f"summary CSV row {row_number} has inconsistent scenario ID"
                )
            endurance, reserve, launch_latency = CONDITION_SETTINGS[condition]
            expected_metadata = {
                "nominal_spacing_km": LAYOUTS[n_bases],
                "n_bases": float(n_bases),
                "drones_per_base": 1.0,
                "airspeed_mps": 18.0,
                "wind_east_mps": wind,
                "endurance_min": endurance,
                "reserve_fraction": reserve,
                "launch_latency_s": launch_latency,
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

            key = (n_bases, wind, condition)
            if key in rows or scenario in scenario_ids:
                raise ValueError(f"duplicate robustness scenario: {scenario}")
            rows[key] = values
            scenario_ids.add(scenario)

    expected = {
        (n_bases, wind, condition)
        for n_bases in LAYOUTS
        for wind in WINDS
        for condition in CONDITIONS
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


def render_robustness(summary_path: Path, output_path: Path) -> None:
    validate_output_path(output_path)
    rows = read_robustness_summary(summary_path)
    figure, axes = plt.subplots(1, 2, figsize=(13, 6), sharex=True, sharey=True)
    figure.suptitle(TITLE, fontsize=17, fontweight="semibold", color="#14243a")

    for axis, n_bases in zip(axes, LAYOUTS):
        axis.set_title(f"{n_bases} bases", loc="left", pad=12)
        axis.set_ylabel("Within 15 min (%)")
        axis.set_ylim(-2, 102)
        axis.set_yticks(range(0, 101, 20))
        axis.set_xticks(range(len(CONDITIONS)))
        axis.set_xticklabels(CONDITION_LABELS)
        axis.set_xlim(-0.5, len(CONDITIONS) - 0.5)
        axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
        axis.set_axisbelow(True)
        for spine in axis.spines.values():
            spine.set_color("#d1d5db")

        for wind, offset, marker in ((8.0, -0.1, "o"), (12.0, 0.1, "s")):
            series = [rows[(n_bases, wind, condition)] for condition in CONDITIONS]
            x_values = [index + offset for index in range(len(CONDITIONS))]
            timely = [row["within_15min_share"] * 100 for row in series]
            lows = [row["mc_95ci_low"] * 100 for row in series]
            highs = [row["mc_95ci_high"] * 100 for row in series]
            color = WIND_COLORS[wind]
            axis.vlines(
                x_values,
                lows,
                highs,
                color=color,
                linewidth=1.5,
                zorder=2,
            )
            cap_width = 0.045
            for x_value, low, high in zip(x_values, lows, highs):
                axis.hlines(
                    (low, high),
                    x_value - cap_width,
                    x_value + cap_width,
                    color=color,
                    linewidth=1.2,
                    zorder=2,
                )
            axis.scatter(
                x_values,
                timely,
                color=color,
                marker=marker,
                s=42,
                zorder=3,
                label=f"{int(wind)} m/s wind",
            )
        axis.set_xlabel("Stress condition")

    handles, labels = axes[0].get_legend_handles_labels()
    figure.legend(
        handles,
        labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 0.08),
        ncol=2,
        frameon=False,
    )
    figure.text(0.5, 0.015, FOOTER, ha="center", fontsize=11, color="#334155")
    figure.tight_layout(rect=(0.04, 0.17, 0.98, 0.9))

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
        render_robustness(arguments.summary, arguments.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
