import argparse
import csv
import hashlib
import json
from pathlib import Path

from coverage_capture import load_capture


def _bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def _records(capture):
    summaries = {row["case_id"]: row for row in capture["summary_rows"]}
    return [{**case, **summaries[case["case_id"]]} for case in capture["scenarios"]]


def analyze(capture40, capture80, capture160, output):
    paths = {40: Path(capture40), 80: Path(capture80), 160: Path(capture160)}
    captures = {size: load_capture(path) for size, path in paths.items()}
    for size, capture in captures.items():
        if capture["manifest"]["grid_n"] != size or len(capture["scenarios"]) != 388:
            raise ValueError("Analysis needs all 388 scenarios at each declared resolution")
        if capture["scenarios"] != captures[80]["scenarios"]:
            raise ValueError("Resolution captures have different scenarios or order")
        if capture["manifest"]["source_sha256"] != captures[80]["manifest"]["source_sha256"]:
            raise ValueError("Resolution captures have different source generations")
    rows = _records(captures[80])
    indexed = {size: {row["case_id"]: row for row in capture["summary_rows"]}
               for size, capture in captures.items()}
    references = {
        (row["n_bases"], row["wind_speed_mps"], row["heading_deg"]): row
        for row in rows if row["profile"] == "reference" and not row["offline_bases"]
    }
    enriched = []
    resolution_rows = []
    for row in rows:
        reference = references[(row["n_bases"], row["wind_speed_mps"], row["heading_deg"])]
        area = 100 * row["timely_area_fraction"]
        loss = 100 * (reference["timely_area_fraction"] - row["timely_area_fraction"])
        enriched.append({
            **row, "timely_area_percent": area, "reference_case_id": reference["case_id"],
            "timely_area_loss_pp": loss,
        })
        finest = indexed[160][row["case_id"]]["timely_area_fraction"]
        resolution_rows.append({
            "case_id": row["case_id"],
            "g40_minus_g160_pp": 100 * (
                indexed[40][row["case_id"]]["timely_area_fraction"] - finest),
            "g80_minus_g160_pp": 100 * (row["timely_area_fraction"] - finest),
        })
    networks = []
    for count in (9, 25):
        healthy = [row for row in enriched if row["n_bases"] == count
                   and row["wind_speed_mps"] == 12 and row["profile"] == "reference"
                   and not row["offline_bases"]]
        singles = [row for row in enriched if row["n_bases"] == count
                   and row["wind_speed_mps"] == 12 and len(row["offline_bases"]) == 1]
        doubles = [row for row in enriched if row["n_bases"] == count
                   and row["wind_speed_mps"] == 12 and len(row["offline_bases"]) == 2]
        by_heading = []
        for heading in range(0, 360, 45):
            reference = next(row for row in healthy if row["heading_deg"] == heading)
            single = sorted((row for row in singles if row["heading_deg"] == heading),
                            key=lambda row: (-row["timely_area_loss_pp"], row["case_id"]))[0]
            double = sorted((row for row in doubles if row["heading_deg"] == heading),
                            key=lambda row: (-row["timely_area_loss_pp"], row["case_id"]))[0]
            by_heading.append({
                "heading_deg": heading, "healthy_case_id": reference["case_id"],
                "healthy_timely_area_percent": reference["timely_area_percent"],
                "largest_single_loss_case_id": single["case_id"],
                "largest_single_loss_base_ids": single["offline_bases"],
                "largest_single_loss_pp": single["timely_area_loss_pp"],
                "largest_selected_double_loss_case_id": double["case_id"],
                "largest_selected_double_loss_base_ids": double["offline_bases"],
                "largest_selected_double_loss_pp": double["timely_area_loss_pp"],
            })
        networks.append({
            "n_bases": count, "by_heading": by_heading,
            "healthy_min_percent": min(row["timely_area_percent"] for row in healthy),
            "healthy_max_percent": max(row["timely_area_percent"] for row in healthy),
            "healthy_stress_heading0": [row for row in enriched
                                       if row["n_bases"] == count and row["wind_speed_mps"] == 12
                                       and row["heading_deg"] == 0 and not row["offline_bases"]],
        })
    analysis = {
        "schema_version": 1, "kind": "captured-coverage-analysis", "scenario_count": 388,
        "default_grid_n": 80,
        "capture_sha256": {str(size): capture["capture_sha256"]
                           for size, capture in captures.items()},
        "source_sha256": captures[80]["manifest"]["source_sha256"],
        "networks": networks, "resolution": {
            "comparison_grid_n": 160,
            "max_abs_g40_minus_g160_pp": max(abs(row["g40_minus_g160_pp"])
                                            for row in resolution_rows),
            "max_abs_g80_minus_g160_pp": max(abs(row["g80_minus_g160_pp"])
                                            for row in resolution_rows),
            "not_an_error_bound": True,
        },
        "calm_and_closure": [row for row in enriched if row["wind_speed_mps"] in (0, 13)],
        "limitations": captures[80]["manifest"]["limitations"],
    }
    output = Path(output)
    output.mkdir()
    with (output / "summary.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(enriched[0]), lineterminator="\n")
        writer.writeheader()
        for row in enriched:
            writer.writerow({
                **row, "wind_mps": json.dumps(row["wind_mps"]),
                "offline_bases": json.dumps(row["offline_bases"]),
            })
    with (output / "resolution.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(resolution_rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(resolution_rows)
    with (output / "analysis.json").open("xb") as handle:
        handle.write(_bytes(analysis))
    # Recheck captured inputs, not rerun their models, before issuing the receipt.
    for size, path in paths.items():
        if load_capture(path)["capture_sha256"] != captures[size]["capture_sha256"]:
            raise ValueError("Capture inputs changed during analysis")
    manifest = {
        "schema_version": 1, "kind": "coverage-analysis-receipt",
        "capture_sha256": analysis["capture_sha256"],
        "analysis_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                  for name in ("summary.csv", "resolution.csv", "analysis.json")},
    }
    with (output / "manifest.json").open("xb") as handle:
        handle.write(_bytes(manifest))
    return analysis


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze frozen coverage captures without rerunning models")
    parser.add_argument("--capture40", required=True, type=Path)
    parser.add_argument("--capture80", required=True, type=Path)
    parser.add_argument("--capture160", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = analyze(args.capture40, args.capture80, args.capture160, args.output)
    print(json.dumps({"scenario_count": result["scenario_count"], "resolution": result["resolution"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
