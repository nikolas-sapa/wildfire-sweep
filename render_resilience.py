import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager

import capture_integrity

LAYOUT_BASES = (9, 25)
WIND_VALUES = (8.0, 12.0)
SUMMARY_COLUMNS = (
    "n_bases",
    "wind_east_mps",
    "offline_base",
    "case_id",
    "active_bases",
    "real_alerts",
    "timely_percent",
    "mc95_low_percent",
    "mc95_high_percent",
)
SUMMARY_NUMERIC = (
    "active_bases",
    "real_alerts",
    "timely_percent",
    "mc95_low_percent",
    "mc95_high_percent",
)
CONTRAST_COLUMNS = (
    "contrast",
    "kind",
    "n_bases",
    "wind_east_mps",
    "delta_timely_pp",
    "mc95_low_pp",
    "mc95_high_pp",
)
SELECTION_COLUMNS = (
    "n_bases",
    "wind_east_mps",
    "offline_base",
    "case_id",
    "selection_rule",
)
SITE_COLUMNS = ("n_bases", "site_id", "x_km", "y_km")
BLUE = "#006bff"
NEUTRAL = "#64748b"
GRID = "#e5e7eb"
SPINE = "#d1d5db"
FOOTER = "#475569"
TITLE = "Held-out synthetic single-base outage: timely service"
LIMITATIONS = [
    "Renders only the frozen captured summary, contrasts, selection, sites and config; no simulation or scoring is rerun.",
    "Pointwise Monte Carlo intervals condition on the training-selected site; not input, selection, model or field uncertainty.",
    "Selected site is worst in training, not a real optimal site or a failure-probability claim.",
    "Synthetic grid coordinates, not an actual Attica map; not field validation.",
]


def _rows(path: Path, required: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"{path.name} has no header")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{path.name} has duplicate columns")
        missing = sorted(set(required) - set(reader.fieldnames))
        if missing:
            raise ValueError(f"{path.name} missing columns: {missing}")
        return list(reader)


def _number(row: dict[str, str], column: str, name: str) -> float:
    try:
        value = float(row[column])
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} has an invalid {column}") from error
    if not math.isfinite(value):
        raise ValueError(f"{name} has a nonfinite {column}")
    return value


def read_summary(path: Path) -> dict[tuple[int, float, bool], dict[str, object]]:
    rows: dict[tuple[int, float, bool], dict[str, object]] = {}
    for row in _rows(path, SUMMARY_COLUMNS):
        try:
            n_bases = int(row["n_bases"])
            offline = int(row["offline_base"])
        except ValueError as error:
            raise ValueError("summary.csv has an invalid base index") from error
        wind = _number(row, "wind_east_mps", "summary.csv")
        values: dict[str, object] = {
            column: _number(row, column, "summary.csv") for column in SUMMARY_NUMERIC
        }
        values["case_id"] = row["case_id"]
        values["offline_base"] = offline
        if not 0 <= values["mc95_low_percent"] <= values["mc95_high_percent"] <= 100:
            raise ValueError("summary.csv has reversed or out-of-range MC95 bounds")
        if not 0 <= values["timely_percent"] <= 100:
            raise ValueError("summary.csv has an out-of-range timely_percent")
        healthy = offline < 0
        if healthy and values["active_bases"] != n_bases:
            raise ValueError("summary.csv healthy row does not use all bases")
        if not healthy and values["active_bases"] != n_bases - 1:
            raise ValueError("summary.csv outage row does not drop exactly one base")
        key = (n_bases, wind, healthy)
        if key in rows:
            raise ValueError(f"summary.csv duplicate scenario: {key}")
        rows[key] = values
    expected = {
        (n, w, healthy)
        for n in LAYOUT_BASES
        for w in WIND_VALUES
        for healthy in (True, False)
    }
    if set(rows) != expected:
        raise ValueError("summary.csv scenarios differ from expected")
    return rows


def read_contrasts(
    path: Path,
) -> tuple[dict[tuple[int, float], dict[str, float]], dict[float, float]]:
    losses: dict[tuple[int, float], dict[str, float]] = {}
    differences: dict[float, float] = {}
    for row in _rows(path, CONTRAST_COLUMNS):
        wind = _number(row, "wind_east_mps", "contrasts.csv")
        values = {
            column: _number(row, column, "contrasts.csv")
            for column in ("delta_timely_pp", "mc95_low_pp", "mc95_high_pp")
        }
        if not -100 <= values["mc95_low_pp"] <= values["mc95_high_pp"] <= 100:
            raise ValueError("contrasts.csv has reversed or out-of-range MC95 bounds")
        if row["kind"] == "outage":
            n_bases = int(row["n_bases"])
            key = (n_bases, wind)
            if key in losses:
                raise ValueError(f"contrasts.csv duplicate outage contrast: {key}")
            losses[key] = values
        elif row["kind"] == "loss_difference":
            if wind in differences:
                raise ValueError(f"contrasts.csv duplicate loss difference: {wind}")
            differences[wind] = values["delta_timely_pp"]
    expected = {(n, w) for n in LAYOUT_BASES for w in WIND_VALUES}
    if set(losses) != expected:
        raise ValueError("contrasts.csv outage contrasts differ from expected")
    if set(differences) != set(WIND_VALUES):
        raise ValueError("contrasts.csv loss differences differ from expected")
    return losses, differences


def read_selection(path: Path) -> dict[tuple[int, float], dict[str, object]]:
    selected: dict[tuple[int, float], dict[str, object]] = {}
    for row in _rows(path, SELECTION_COLUMNS):
        try:
            n_bases = int(row["n_bases"])
            offline = int(row["offline_base"])
        except ValueError as error:
            raise ValueError("selection.csv has an invalid base index") from error
        if offline < 0:
            raise ValueError("selection.csv must name an offline base")
        if not row["selection_rule"]:
            raise ValueError("selection.csv has an empty selection_rule")
        wind = _number(row, "wind_east_mps", "selection.csv")
        key = (n_bases, wind)
        if key in selected:
            raise ValueError(f"selection.csv duplicate selection: {key}")
        selected[key] = {"offline_base": offline, "case_id": row["case_id"]}
    expected = {(n, w) for n in LAYOUT_BASES for w in WIND_VALUES}
    if set(selected) != expected:
        raise ValueError("selection.csv selections differ from expected")
    return selected


def read_sites(path: Path) -> dict[int, list[tuple[int, float, float]]]:
    sites: dict[int, list[tuple[int, float, float]]] = {}
    for row in _rows(path, SITE_COLUMNS):
        try:
            n_bases = int(row["n_bases"])
            site_id = int(row["site_id"])
        except ValueError as error:
            raise ValueError("base_sites.csv has an invalid site index") from error
        x_km = _number(row, "x_km", "base_sites.csv")
        y_km = _number(row, "y_km", "base_sites.csv")
        sites.setdefault(n_bases, []).append((site_id, x_km, y_km))
    if set(sites) != set(LAYOUT_BASES):
        raise ValueError("base_sites.csv layouts differ from expected")
    for n_bases, entries in sites.items():
        entries.sort(key=lambda entry: entry[0])
        if [entry[0] for entry in entries] != list(range(n_bases)):
            raise ValueError(f"base_sites.csv site ids for {n_bases} bases are incomplete")
    return sites


def _use_geist() -> None:
    for font in font_manager.fontManager.ttflist:
        if font.name == "Geist":
            plt.rcParams["font.family"] = "Geist"
            return


def _style_axis(axis) -> None:
    axis.grid(axis="y", color=GRID, linewidth=0.8)
    axis.set_axisbelow(True)
    for spine in axis.spines.values():
        spine.set_color(SPINE)


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _service_png(
    summary: dict[tuple[int, float, bool], dict[str, object]],
    losses: dict[tuple[int, float], dict[str, float]],
    differences: dict[float, float],
    heldout_alerts: int,
) -> bytes:
    figure, axes = plt.subplots(1, 2, figsize=(12, 7), sharey=True)
    figure.suptitle(TITLE, fontsize=16, fontweight="semibold", color="#111827")
    handles = {}
    for axis, wind in zip(axes, WIND_VALUES):
        axis.set_title(f"east wind {wind:g} m/s", loc="left", pad=10)
        axis.set_xticks(range(4))
        axis.set_xlim(-0.6, 3.6)
        axis.set_ylim(0, 100)
        axis.set_yticks(range(0, 101, 20))
        _style_axis(axis)
        positions = 0
        labels = []
        for n_bases in LAYOUT_BASES:
            for healthy in (True, False):
                row = summary[(n_bases, wind, healthy)]
                point = float(row["timely_percent"])
                low = float(row["mc95_low_percent"])
                high = float(row["mc95_high_percent"])
                color = NEUTRAL if healthy else BLUE
                name = "all bases healthy" if healthy else "training-selected outage"
                (marker,) = axis.plot(positions, point, "o", color=color, markersize=7)
                axis.plot(
                    [positions, positions], [low, high],
                    color=color, linewidth=1.5, solid_capstyle="butt",
                )
                for cap in (low, high):
                    axis.plot(
                        [positions - 0.07, positions + 0.07], [cap, cap],
                        color=color, linewidth=1.5, solid_capstyle="butt",
                    )
                handles.setdefault(name, marker)
                labels.append(
                    f"nominal {n_bases}\nactive {int(row['active_bases'])}"
                )
                if not healthy:
                    loss = losses[(n_bases, wind)]
                    axis.annotate(
                        f"loss {loss['delta_timely_pp']:.2f} pp\n"
                        f"MC95 [{loss['mc95_low_pp']:.2f}, {loss['mc95_high_pp']:.2f}]",
                        (positions, 4), ha="center", fontsize=8, color=FOOTER,
                    )
                positions += 1
        axis.set_xticklabels(labels, fontsize=9)
    axes[0].set_ylabel("Timely real alerts (%)")
    figure.legend(
        handles.values(), handles.keys(),
        loc="lower center", bbox_to_anchor=(0.5, 0.115), ncol=2, frameon=False,
    )
    figure.text(
        0.5, 0.055,
        f"{heldout_alerts:,} held-out synthetic real alerts. "
        f"Loss difference (denser minus sparser layout): "
        f"{differences[WIND_VALUES[0]]:+.2f} pp at {WIND_VALUES[0]:g} m/s, "
        f"{differences[WIND_VALUES[1]]:+.2f} pp at {WIND_VALUES[1]:g} m/s; "
        "positive means the denser layout loses less.",
        ha="center", fontsize=9, color=FOOTER,
    )
    figure.text(
        0.5, 0.02,
        "Pointwise MC95% intervals condition on the training-selected site; "
        "not input, selection, model or field uncertainty. Not field validation.",
        ha="center", fontsize=9, color=FOOTER,
    )
    figure.tight_layout(rect=(0.02, 0.16, 0.98, 0.93))
    image = io.BytesIO()
    try:
        figure.savefig(image, format="png", dpi=180, facecolor="white")
    finally:
        plt.close(figure)
    return image.getvalue()


def _sites_png(
    sites: dict[int, list[tuple[int, float, float]]],
    selection: dict[tuple[int, float], dict[str, object]],
    side_km: float,
) -> bytes:
    figure, axes = plt.subplots(2, 2, figsize=(10, 10))
    figure.suptitle(
        "Synthetic base grids and training-selected outage",
        fontsize=16, fontweight="semibold", color="#111827",
    )
    ticks = [0, side_km / 3, side_km * 2 / 3, side_km]
    for row_index, n_bases in enumerate(LAYOUT_BASES):
        for column_index, wind in enumerate(WIND_VALUES):
            axis = axes[row_index, column_index]
            axis.set_title(
                f"nominal {n_bases} bases, east wind {wind:g} m/s",
                loc="left", pad=8,
            )
            axis.set_xlim(0, side_km)
            axis.set_ylim(0, side_km)
            axis.set_aspect("equal")
            axis.set_xticks(ticks)
            axis.set_yticks(ticks)
            axis.grid(color=GRID, linewidth=0.8)
            axis.set_axisbelow(True)
            for spine in axis.spines.values():
                spine.set_color(SPINE)
            xs = [entry[1] for entry in sites[n_bases]]
            ys = [entry[2] for entry in sites[n_bases]]
            axis.plot(xs, ys, "o", color=BLUE, markersize=5, linestyle="none")
            offline = int(selection[(n_bases, wind)]["offline_base"])
            site = next(entry for entry in sites[n_bases] if entry[0] == offline)
            axis.plot(
                site[1], site[2], marker="x", color="black",
                markersize=10, markeredgewidth=2, linestyle="none",
            )
            axis.annotate(
                f"training-selected outage: site {offline} "
                f"({n_bases}->{n_bases - 1} active)",
                (0.03, 0.03), xycoords="axes fraction",
                fontsize=8, color=FOOTER,
            )
            axis.set_xlabel("synthetic x (km)")
            axis.set_ylabel("synthetic y (km)")
    figure.text(
        0.5, 0.02,
        "Synthetic square-grid coordinates, not an actual Attica map. "
        "Marker is the training-worst site, not a real optimal site or "
        "failure-probability claim.",
        ha="center", fontsize=9, color=FOOTER,
    )
    figure.tight_layout(rect=(0.02, 0.05, 0.98, 0.95))
    image = io.BytesIO()
    try:
        figure.savefig(image, format="png", dpi=180, facecolor="white")
    finally:
        plt.close(figure)
    return image.getvalue()


def render_capture(run_dir: Path, output_dir: Path) -> Path:
    run_dir = Path(run_dir)
    output_dir = Path(output_dir)
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(f"output already exists: {output_dir}")
    if not output_dir.parent.is_dir():
        raise FileNotFoundError(
            f"output parent directory does not exist: {output_dir.parent}"
        )
    renderer_bytes = Path(__file__).read_bytes()
    renderer_sha256 = hashlib.sha256(renderer_bytes).hexdigest()
    receipt = capture_integrity.verify_capture(str(run_dir))
    manifest_bytes = (run_dir / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != receipt["manifest_sha256"]:
        raise ValueError("input manifest changed while reading")
    study = json.loads(manifest_bytes.decode("utf-8"))
    heldout_alerts = study.get("heldout_real_alerts")
    if not isinstance(heldout_alerts, int) or heldout_alerts <= 0:
        raise ValueError("manifest heldout_real_alerts is missing or invalid")
    summary = read_summary(run_dir / "summary.csv")
    losses, differences = read_contrasts(run_dir / "contrasts.csv")
    selection = read_selection(run_dir / "selection.csv")
    sites = read_sites(run_dir / "base_sites.csv")
    with (run_dir / "config.json").open(encoding="utf-8") as handle:
        domain_km2 = _number(
            {"domain_km2": json.load(handle).get("domain_km2")},
            "domain_km2", "config.json",
        )
    if domain_km2 <= 0:
        raise ValueError("config.json domain_km2 must be positive")
    for key, picked in selection.items():
        outage = summary[(key[0], key[1], False)]
        if outage["offline_base"] != picked["offline_base"]:
            raise ValueError("selection.csv and summary.csv disagree on offline base")
        if outage["case_id"] != picked["case_id"]:
            raise ValueError("selection.csv and summary.csv disagree on case_id")
    for row in summary.values():
        if int(row["real_alerts"]) != heldout_alerts:
            raise ValueError("summary.csv real_alerts disagrees with manifest")
    for n_bases, wind in selection:
        site_ids = {entry[0] for entry in sites[n_bases]}
        if int(selection[(n_bases, wind)]["offline_base"]) not in site_ids:
            raise ValueError("selection.csv names a site absent from base_sites.csv")
    _use_geist()
    service_png = _service_png(summary, losses, differences, heldout_alerts)
    sites_png = _sites_png(sites, selection, math.sqrt(domain_km2))
    if capture_integrity.verify_capture(str(run_dir)) != receipt:
        raise ValueError("input changed while rendering")
    if Path(__file__).read_bytes() != renderer_bytes:
        raise ValueError("renderer source changed while rendering")
    os.mkdir(output_dir)
    _write_new(output_dir / "service.png", service_png)
    _write_new(output_dir / "sites.png", sites_png)
    artifact_sha256 = {
        name: hashlib.sha256((output_dir / name).read_bytes()).hexdigest()
        for name in ("service.png", "sites.png")
    }
    source_sha256 = {"render_resilience.py": renderer_sha256}
    manifest = {
        "schema_version": 1,
        "status": "complete",
        "input_manifest_sha256": receipt["manifest_sha256"],
        "source_sha256": source_sha256,
        "artifact_sha256": artifact_sha256,
        "limitations": LIMITATIONS,
    }
    _write_new(
        output_dir / "manifest.json",
        (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode("utf-8"),
    )
    return output_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        render_capture(arguments.run, arguments.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
