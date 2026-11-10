import argparse
import sys
from pathlib import Path

from coverage_data import CoverageData


def _escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("\\", "\\\\")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("#", "\\#")
        .replace("\r\n", " ")
        .replace("\n", " ")
        .replace("\r", " ")
    )


def _fmt(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return _escape(value)


def _fmt_cell(value):
    if isinstance(value, list):
        return "[" + ", ".join(_fmt(item) for item in value) + "]"
    return _fmt(value)


def _percent(fraction):
    return f"{100 * fraction:.2f}%"


def _render(catalog, capture):
    cases = catalog["cases"]
    grid = catalog["grid"]
    lines = []
    add = lines.append
    add("# Coverage atlas: captured scenario inventory")
    add("")
    add("Rendered from a stored capture via `CoverageData`. No recomputation, "
        "capture generation or new metrics were performed.")
    add("")
    add("Coverage is the fraction of equal-area cell centers reached within the "
        "stored timely threshold by an initially idle network. It is not a season "
        "success rate, ignition-risk estimate, confidence interval, forecast, "
        "detector result, geographic map or flight-control system.")
    add("")
    add("## Provenance")
    add("")
    add("| field | value |")
    add("| --- | --- |")
    for field, value in (
        ("capture directory", str(capture)),
        ("study_id", catalog["study_id"]),
        ("mode", catalog["mode"]),
        ("schema_version", catalog["schema_version"]),
        ("capture_sha256", catalog["capture_sha256"]),
        ("grid_n", catalog["grid_n"]),
        ("domain_side_km", catalog["domain_side_km"]),
        ("timely_threshold_s", catalog["timely_threshold_s"]),
        ("grid order", grid["order"]),
        ("grid locations", grid["locations"]),
        ("grid north", grid["north"]),
    ):
        add(f"| {_escape(field)} | {_fmt_cell(value)} |")
    add("")
    add("Outcome codes:")
    add("")
    add("| outcome | code |")
    add("| --- | --- |")
    for name, code in catalog["outcome_codes"].items():
        add(f"| {_escape(name)} | {_fmt(code)} |")
    add("")
    add("## Source fingerprints (source_sha256)")
    add("")
    add("| file | sha256 |")
    add("| --- | --- |")
    for name, digest in catalog["source_sha256"].items():
        add(f"| {_escape(name)} | {_escape(digest)} |")
    add("")
    add("## Source-verified layout coordinates")
    add("")
    add("| n_bases | base_id | x_km | y_km | available |")
    add("| --- | --- | --- | --- | --- |")
    for count, bases in catalog["layouts"].items():
        for base in bases:
            add("| " + " | ".join((
                _escape(count),
                _fmt(base["id"]),
                _fmt(base["x_km"]),
                _fmt(base["y_km"]),
                _fmt(base["available"]),
            )) + " |")
    add("")
    add(f"## Scenario inventory ({_fmt(len(cases))} cases)")
    add("")
    add("Exactly the scenarios stored in this capture are listed; this is not a "
        "claim of all possible scenarios.")
    add("")
    add("### Stored scenario inputs")
    add("")
    add("| case_id | n_bases | wind_mps | wind_speed_mps | heading_deg | profile "
        "| offline_bases | airspeed_mps | endurance_min | reserve_fraction "
        "| launch_latency_s |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for case in cases:
        add("| " + " | ".join((
            _escape(case["case_id"]),
            _fmt(case["n_bases"]),
            _fmt_cell(case["wind_mps"]),
            _fmt(case["wind_speed_mps"]),
            _fmt(case["heading_deg"]),
            _escape(case["profile"]),
            _fmt_cell(case["offline_bases"]),
            _fmt(case["airspeed_mps"]),
            _fmt(case["endurance_min"]),
            _fmt(case["reserve_fraction"]),
            _fmt(case["launch_latency_s"]),
        )) + " |")
    add("")
    add("### Stored cell outcomes")
    add("")
    add("| case_id | unreachable_cells | late_cells | timely_cells "
        "| weather_closed_cells | total_cells | timely_area_fraction "
        "| reachable_area_fraction | timely_area_percent | reachable_area_percent |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for case in cases:
        summary = case["summary"]
        add("| " + " | ".join((
            _escape(summary["case_id"]),
            _fmt(summary["unreachable_cells"]),
            _fmt(summary["late_cells"]),
            _fmt(summary["timely_cells"]),
            _fmt(summary["weather_closed_cells"]),
            _fmt(summary["total_cells"]),
            _fmt(summary["timely_area_fraction"]),
            _fmt(summary["reachable_area_fraction"]),
            _percent(summary["timely_area_fraction"]),
            _percent(summary["reachable_area_fraction"]),
        )) + " |")
    add("")
    add("Field notes:")
    add("")
    add("- `wind_mps` lists the stored east/north components toward which the wind "
        "blows; `heading_deg` is that direction in degrees (east=0, north=90) and "
        "is null for calm cases.")
    add("- `offline_bases` are original layout base IDs disabled for the scenario; "
        "`[]` means no outage.")
    add("- Counts are stored per-cell outcomes over the grid; percent columns are "
        "100 x the stored fraction, shown to 2 decimals.")
    add("")
    add("## Limitations")
    add("")
    for item in catalog["limitations"]:
        add(f"- {_escape(item)}")
    add("")
    return "\n".join(lines)


def _parser():
    parser = argparse.ArgumentParser(
        description="Render a stored coverage-atlas capture as escaped Markdown")
    parser.add_argument("--capture", required=True, type=Path,
                        help="existing capture directory containing manifest.json")
    parser.add_argument("--output", required=True, type=Path,
                        help="new Markdown file; must not already exist")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        catalog = CoverageData(args.capture).catalog()
        document = _render(catalog, args.capture)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(document)
    except (ImportError, OSError, TypeError, ValueError, KeyError, AttributeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
