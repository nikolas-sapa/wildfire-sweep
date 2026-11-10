import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


HEADINGS = (0, 45, 90, 135, 180, 225, 270, 315)
LAYOUTS = (9, 25)
LAYOUT_COLORS = {9: "#7d7d7d", 25: "#006bff"}
PROFILE_ORDER = (
    "reference",
    "short_endurance",
    "larger_reserve",
    "slow_launch",
    "combined",
)
PROFILE_LABELS = {
    "reference": "Reference",
    "short_endurance": "36min endurance",
    "larger_reserve": "35% reserve",
    "slow_launch": "180s launch",
    "combined": "Combined",
}
REQUIRED_COLUMNS = {
    "n_bases",
    "wind_speed_mps",
    "heading_deg",
    "profile",
    "offline_bases",
    "timely_area_percent",
    "timely_area_loss_pp",
}
MANIFEST_MAX_BYTES = 65536
SUMMARY_MAX_BYTES = 4 * 1024 * 1024


def read_stable_bytes(path, limit, label):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{label} is not a regular file")
        if before.st_size > limit:
            raise ValueError(f"{label} exceeds its size limit")
        contents = handle.read(before.st_size + 1)
        after = os.fstat(handle.fileno())
    if len(contents) != before.st_size:
        raise ValueError(f"{label} changed while being read")
    before_identity = (before.st_size, before.st_mtime_ns, before.st_ino)
    after_identity = (after.st_size, after.st_mtime_ns, after.st_ino)
    if before_identity != after_identity:
        raise ValueError(f"{label} changed while being read")
    return contents


def read_capture(capture_dir):
    manifest_path = capture_dir / "manifest.json"
    summary_path = capture_dir / "summary.csv"
    manifest_bytes = read_stable_bytes(manifest_path, MANIFEST_MAX_BYTES, "manifest.json")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("manifest.json is invalid") from error
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json root must be an object")
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("manifest schema_version must be 1")
    if manifest.get("kind") != "coverage-analysis-receipt":
        raise ValueError("manifest kind is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ValueError("manifest files must be an object")
    expected_hash = files.get("summary.csv")
    if not isinstance(expected_hash, str) or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None:
        raise ValueError("manifest has no valid summary.csv SHA-256")

    capture_hashes = manifest.get("capture_sha256")
    if not isinstance(capture_hashes, dict):
        raise ValueError("manifest has no resolution capture hashes")
    capture_80_hash = capture_hashes.get("80")
    if not isinstance(capture_80_hash, str) or re.fullmatch(r"[0-9a-f]{64}", capture_80_hash) is None:
        raise ValueError("manifest has no valid 80-capture SHA-256")

    summary_bytes = read_stable_bytes(summary_path, SUMMARY_MAX_BYTES, "summary.csv")
    actual_hash = hashlib.sha256(summary_bytes).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("summary.csv SHA-256 does not match capture manifest")

    try:
        text = summary_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("summary.csv is not valid UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise ValueError("summary.csv has no header")
    if len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError("summary.csv header has duplicate columns")
    missing = REQUIRED_COLUMNS - set(reader.fieldnames)
    if missing:
        raise ValueError(f"summary.csv is missing required columns: {', '.join(sorted(missing))}")
    rows = []
    for line_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(f"summary.csv row {line_number} has extra columns")
        if any(value is None for value in row.values()):
            raise ValueError(f"summary.csv row {line_number} has missing columns")
        rows.append(row)
    return capture_80_hash[:8], rows


def numeric_value(row, column):
    try:
        value = float(row[column])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"summary row has an invalid {column}") from error
    if not math.isfinite(value):
        raise ValueError(f"summary row has a non-finite {column}")
    return value


def panel_value(row, column, upper_limit):
    value = numeric_value(row, column)
    if not 0 <= value <= upper_limit:
        raise ValueError(f"summary {column} is outside the panel range")
    return value


def matches_reference_row(row, layout, heading, profile):
    try:
        n_bases = int(row["n_bases"])
    except (TypeError, ValueError) as error:
        raise ValueError("summary row has an invalid n_bases") from error
    if n_bases != layout:
        return False
    if numeric_value(row, "wind_speed_mps") != 12:
        return False
    if numeric_value(row, "heading_deg") != heading:
        return False
    if row["profile"] != profile:
        return False
    try:
        offline_bases = json.loads(row["offline_bases"])
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError("summary row has invalid offline_bases JSON") from error
    if not isinstance(offline_bases, list):
        raise ValueError("summary row offline_bases is not a list")
    return offline_bases == []


def select_one(rows, layout, heading, profile):
    matches = [
        row for row in rows
        if matches_reference_row(row, layout, heading, profile)
    ]
    if len(matches) != 1:
        raise ValueError(
            "expected exactly one summary row for "
            f"layout={layout}, heading={heading}, profile={profile}; found {len(matches)}"
        )
    return matches[0]


def create_direction_figure(rows, capture_hash_prefix):
    figure, axis = plt.subplots(figsize=(12, 6.5))
    for layout in LAYOUTS:
        values = [
            panel_value(
                select_one(rows, layout, heading, "reference"),
                "timely_area_percent",
                100,
            )
            for heading in HEADINGS
        ]
        axis.plot(
            HEADINGS,
            values,
            color=LAYOUT_COLORS[layout],
            marker="o",
            linewidth=2,
            markersize=6,
            label=f"{layout} bases",
        )
    axis.set_title("Directional potential coverage")
    axis.set_xlabel("Wind direction toward (degrees, east=0)")
    axis.set_ylabel("Potential timely area (%)")
    axis.set_xticks(HEADINGS)
    axis.set_ylim(0, 100)
    axis.set_axisbelow(True)
    axis.grid(axis="y", color="#d9d9d9", linewidth=0.8)
    axis.legend(frameon=False)
    figure.subplots_adjust(bottom=0.2, top=0.88)
    figure.text(
        0.5,
        0.045,
        "Synthetic cell-center approximation; initially idle network, one alert at a time. "
        "Not field-validated. "
        f"80x80 capture SHA-256 prefix: {capture_hash_prefix}.",
        ha="center",
        va="center",
        fontsize=9,
        color="#555555",
    )
    return figure


def add_bar_labels(axis, bars, values, upper_limit, gap, decimals):
    for bar, value in zip(bars, values):
        if value + gap < upper_limit:
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                value + gap,
                f"{value:.{decimals}f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#333333",
            )


def create_stress_figure(rows, capture_hash_prefix):
    figure, axes = plt.subplots(1, 2, figsize=(14, 6.5))
    positions = list(range(len(PROFILE_ORDER)))
    width = 0.34
    panels = (
        (axes[0], "timely_area_percent", "Potential timely area (%)", 100, 1.0, 1),
        (axes[1], "timely_area_loss_pp", "Timely area loss (pp)", 35, 0.5, 2),
    )
    for axis, column, ylabel, upper_limit, gap, decimals in panels:
        for layout_index, layout in enumerate(LAYOUTS):
            values = [
                panel_value(
                    select_one(rows, layout, 0, profile),
                    column,
                    upper_limit,
                )
                for profile in PROFILE_ORDER
            ]
            offset = (layout_index - 0.5) * width
            bars = axis.bar(
                [position + offset for position in positions],
                values,
                width=width,
                color=LAYOUT_COLORS[layout],
                label=f"{layout} bases",
            )
            add_bar_labels(axis, bars, values, upper_limit, gap, decimals)
        axis.set_ylabel(ylabel)
        axis.set_xticks(positions, [PROFILE_LABELS[profile] for profile in PROFILE_ORDER])
        axis.set_ylim(0, upper_limit)
        axis.set_axisbelow(True)
        axis.grid(axis="y", color="#d9d9d9", linewidth=0.8)
        for label in axis.get_xticklabels():
            label.set_rotation(22)
            label.set_ha("right")
    handles, labels = axes[0].get_legend_handles_labels()
    figure.suptitle("No-outage operating stress at 12 m/s, heading 0 (east)")
    figure.legend(
        handles,
        labels,
        ncol=2,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.94),
        frameon=False,
    )
    figure.subplots_adjust(bottom=0.27, top=0.8, wspace=0.28)
    figure.text(
        0.5,
        0.035,
        "Synthetic cell-center approximation; initially idle network, one alert at a time. "
        "Not field-validated. "
        f"80x80 capture SHA-256 prefix: {capture_hash_prefix}.",
        ha="center",
        va="center",
        fontsize=9,
        color="#555555",
    )
    return figure


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    try:
        if not args.capture.is_dir():
            raise ValueError("capture directory does not exist")
        if args.output.exists():
            raise ValueError("output directory already exists")
        if not args.output.parent.is_dir():
            raise ValueError("output parent directory does not exist")

        capture_hash_prefix, rows = read_capture(args.capture)
        direction_figure = create_direction_figure(rows, capture_hash_prefix)
        stress_figure = create_stress_figure(rows, capture_hash_prefix)
        direction_buffer = io.BytesIO()
        stress_buffer = io.BytesIO()
        direction_figure.savefig(direction_buffer, format="png", dpi=180, facecolor="white")
        stress_figure.savefig(stress_buffer, format="png", dpi=180, facecolor="white")
        plt.close(direction_figure)
        plt.close(stress_figure)

        args.output.mkdir(exist_ok=False)
        outputs = (
            ("direction.png", direction_buffer.getvalue()),
            ("stress.png", stress_buffer.getvalue()),
        )
        for name, content in outputs:
            with (args.output / name).open("xb") as output_file:
                output_file.write(content)
    except (OSError, UnicodeDecodeError, ValueError, csv.Error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
