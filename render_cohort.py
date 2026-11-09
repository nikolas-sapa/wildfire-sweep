import argparse
import csv
import io
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

REQUIRED_COLUMNS = (
    "metric",
    "estimate",
    "ci_95_low",
    "ci_95_high",
    "unit",
    "n_records",
    "n_clusters",
    "informative_clusters",
    "valid_bootstrap_draws",
    "ci_status",
)
INTERVAL_COLUMNS = ("estimate", "ci_95_low", "ci_95_high")
COUNT_COLUMNS = (
    "n_records",
    "n_clusters",
    "informative_clusters",
    "valid_bootstrap_draws",
)
METRIC_UNITS = {
    "event_recall": "fraction",
    "alarm_precision": "fraction",
    "false_alarms_per_nonfire_hour": "per_nonfire_hour",
    "detected_delay_p50_s": "seconds",
    "detected_delay_p90_s": "seconds",
}
EXPECTED_METRICS = tuple(METRIC_UNITS)
CI_STATUSES = ("undefined", "insufficient_clusters", "cluster_bootstrap")
BOOTSTRAP_REPLICATES = 1000
STATUS_SUFFIX = {
    "undefined": "(undefined)",
    "insufficient_clusters": "(no interval)",
    "cluster_bootstrap": "",
}
POINT_COLOR = "#006bff"
INTERVAL_COLOR = "#1e3a5f"
MUTED_COLOR = "#64748b"
PANELS = (
    (
        "Recall / precision",
        "Percent",
        ("event_recall", "alarm_precision"),
        ("Recall", "Precision"),
        True,
    ),
    (
        "False onset rate",
        "per non-fire hour",
        ("false_alarms_per_nonfire_hour",),
        ("False onset rate",),
        False,
    ),
    (
        "Detected-only delay",
        "Seconds",
        ("detected_delay_p50_s", "detected_delay_p90_s"),
        ("p50", "p90"),
        False,
    ),
)
TITLE = "Captured cohort metrics"
FOOTER = (
    "Pointwise nominal 95% cluster-bootstrap intervals on declared cluster_id "
    "groups; declared groups are not verified independence. Not field validation."
)

try:
    font_names = {font.name for font in font_manager.fontManager.ttflist}
    geist = next(
        (name for name in sorted(font_names) if name.startswith("Geist")),
        None,
    )
except Exception:
    geist = None
if geist:
    plt.rcParams["font.sans-serif"] = [geist, *plt.rcParams["font.sans-serif"]]


def _parse_value(cell, column, row_number, unit):
    text = (cell or "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(
            f"summary CSV row {row_number} has an invalid {column}"
        ) from error
    if not math.isfinite(value):
        raise ValueError(
            f"summary CSV row {row_number} has a nonfinite {column}"
        )
    if unit == "fraction":
        if not 0 <= value <= 1:
            raise ValueError(
                f"summary CSV row {row_number} has an out-of-range {column}"
            )
    elif value < 0:
        raise ValueError(f"summary CSV row {row_number} has a negative {column}")
    return value


def _parse_count(cell, column, row_number):
    text = (cell or "").strip()
    try:
        return int(text, 10)
    except ValueError as error:
        raise ValueError(
            f"summary CSV row {row_number} has an invalid {column}"
        ) from error


def read_cohort_summary(summary_path):
    summary_path = Path(summary_path)
    with summary_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("summary CSV has no header")
        if list(reader.fieldnames) != list(REQUIRED_COLUMNS):
            raise ValueError(
                "summary CSV header must be exactly: "
                + ",".join(REQUIRED_COLUMNS)
            )

        records = {}
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"summary CSV row {row_number} has extra values")
            if any(value is None for value in row.values()):
                raise ValueError(f"summary CSV row {row_number} has missing values")

            metric = row["metric"].strip()
            if metric not in METRIC_UNITS:
                raise ValueError(
                    f"summary CSV row {row_number} has unknown metric: {metric}"
                )
            if metric in records:
                raise ValueError(f"duplicate cohort metric: {metric}")
            unit = row["unit"].strip()
            if unit != METRIC_UNITS[metric]:
                raise ValueError(
                    f"summary CSV row {row_number} has wrong unit for {metric}"
                )
            status = row["ci_status"].strip()
            if status not in CI_STATUSES:
                raise ValueError(
                    f"summary CSV row {row_number} has unknown ci_status: {status}"
                )

            parsed = {
                column: _parse_value(row[column], column, row_number, unit)
                for column in INTERVAL_COLUMNS
            }
            estimate = parsed["estimate"]
            low = parsed["ci_95_low"]
            high = parsed["ci_95_high"]
            if (low is None) != (high is None):
                raise ValueError(
                    f"summary CSV row {row_number} has a partial interval"
                )
            if low is not None and low > high:
                raise ValueError(
                    f"summary CSV row {row_number} has reversed confidence bounds"
                )

            counts = {
                column: _parse_count(row[column], column, row_number)
                for column in COUNT_COLUMNS
            }
            if counts["n_records"] < 1:
                raise ValueError(
                    f"summary CSV row {row_number} has invalid n_records"
                )
            if not 1 <= counts["n_clusters"] <= counts["n_records"]:
                raise ValueError(
                    f"summary CSV row {row_number} has invalid n_clusters"
                )
            if not 0 <= counts["informative_clusters"] <= counts["n_clusters"]:
                raise ValueError(
                    f"summary CSV row {row_number} has invalid informative_clusters"
                )
            if not 0 <= counts["valid_bootstrap_draws"] <= BOOTSTRAP_REPLICATES:
                raise ValueError(
                    f"summary CSV row {row_number} has invalid valid_bootstrap_draws"
                )

            if status == "undefined":
                consistent = (
                    estimate is None
                    and low is None
                    and counts["informative_clusters"] == 0
                    and counts["valid_bootstrap_draws"] == 0
                )
            elif status == "insufficient_clusters":
                consistent = (
                    estimate is not None
                    and low is None
                    and counts["informative_clusters"] == 1
                )
            else:
                consistent = (
                    estimate is not None
                    and low is not None
                    and counts["informative_clusters"] >= 2
                    and counts["valid_bootstrap_draws"] >= 1
                )
            if not consistent:
                raise ValueError(
                    f"summary CSV row {row_number} has inconsistent {status} fields"
                )

            records[metric] = {
                "estimate": estimate,
                "ci_95_low": low,
                "ci_95_high": high,
                "unit": unit,
                "ci_status": status,
                **counts,
            }

    missing = [metric for metric in EXPECTED_METRICS if metric not in records]
    if missing:
        raise ValueError(f"summary CSV is missing metrics: {missing}")
    if len({record["n_records"] for record in records.values()}) != 1:
        raise ValueError("summary CSV rows disagree on n_records")
    if len({record["n_clusters"] for record in records.values()}) != 1:
        raise ValueError("summary CSV rows disagree on n_clusters")
    return records


def validate_output_path(output_path) -> None:
    if output_path.suffix.lower() != ".png":
        raise ValueError("output path must have a .png suffix")
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"output already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise FileNotFoundError(
            f"output parent directory does not exist: {output_path.parent}"
        )


def write_new_png(output_path, image: bytes) -> None:
    descriptor = os.open(
        output_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(image)


def render(summary_path, output_path) -> None:
    summary_path = Path(summary_path)
    output_path = Path(output_path)
    validate_output_path(output_path)
    records = read_cohort_summary(summary_path)
    figure, axes = plt.subplots(1, 3, figsize=(12.5, 4.8))
    try:
        figure.suptitle(
            TITLE, fontsize=15, fontweight="semibold", color="#14243a"
        )
        for axis, (title, ylabel, names, labels, percent) in zip(axes, PANELS):
            scale = 100.0 if percent else 1.0
            entries = [records[name] for name in names]
            if percent:
                y_min, y_max = -2.0, 102.0
                axis.set_yticks(range(0, 101, 20))
            else:
                top = max(
                    (
                        record[key]
                        for record in entries
                        for key in ("estimate", "ci_95_high")
                        if record[key] is not None
                    ),
                    default=1.0,
                )
                y_min, y_max = 0.0, max(top * 1.25, 1.0)
            axis.set_ylim(y_min, y_max)
            axis.set_title(title, loc="left", pad=10)
            axis.set_ylabel(ylabel)
            axis.set_xlim(-0.6, len(entries) - 0.4)
            axis.grid(axis="y", color="#e5e7eb", linewidth=0.8)
            axis.set_axisbelow(True)
            for spine in axis.spines.values():
                spine.set_color("#d1d5db")

            caption_y = y_min + 0.06 * (y_max - y_min)
            tick_labels = []
            for index, (record, label) in enumerate(zip(entries, labels)):
                status = record["ci_status"]
                suffix = STATUS_SUFFIX[status]
                tick_labels.append(f"{label}\n{suffix}" if suffix else label)
                if status == "undefined":
                    axis.text(
                        index,
                        caption_y,
                        "undefined",
                        ha="center",
                        va="bottom",
                        fontsize=9,
                        color=MUTED_COLOR,
                    )
                    continue
                point = record["estimate"] * scale
                if status == "cluster_bootstrap":
                    low = record["ci_95_low"] * scale
                    high = record["ci_95_high"] * scale
                    axis.vlines(
                        [index],
                        [low],
                        [high],
                        color=INTERVAL_COLOR,
                        linewidth=1.5,
                        zorder=2,
                    )
                    axis.hlines(
                        [low, high],
                        index - 0.14,
                        index + 0.14,
                        color=INTERVAL_COLOR,
                        linewidth=1.2,
                        zorder=2,
                    )
                    axis.scatter(
                        [index],
                        [point],
                        color=POINT_COLOR,
                        marker="o",
                        s=46,
                        zorder=3,
                    )
                else:
                    axis.scatter(
                        [index],
                        [point],
                        facecolors="white",
                        edgecolors=POINT_COLOR,
                        marker="o",
                        s=46,
                        linewidths=1.5,
                        zorder=3,
                    )
            axis.set_xticks(range(len(entries)))
            axis.set_xticklabels(tick_labels, fontsize=9)

        figure.text(
            0.5, 0.028, FOOTER, ha="center", fontsize=9, color="#475569"
        )
        figure.tight_layout(rect=(0.015, 0.17, 0.995, 0.90))

        image = io.BytesIO()
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
