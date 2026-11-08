import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np

from research import MissionConfig, dispatch_physical, nearest_rank, success_interval
from robustness import response_counts, scenario_grid, write_csv
from sweep import CONFIG, base_grid, cost_per_km2_yr


ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / "factorial_protocol.json"
DEFAULT_SOURCE = ROOT / "research_results/2026-11-08-robustness"
FACTORS = ("endurance", "launch", "reserve")
METRICS = ("real_alerts", "within_15min", "rejected", "served_late",
           "within_15min_share", "mc_95ci_low", "mc_95ci_high", "rejected_share",
           "served_late_share", "p90_s", "p90_unreachable", "eur_per_km2_yr")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def factorial_interval(successes, totals, factors, seed, replicates=1000):
    successes, totals = np.asarray(successes, dtype=float), np.asarray(totals, dtype=float)
    if (totals.ndim != 1 or not len(totals)
            or successes.shape != (2, 2, 2, len(totals))):
        raise ValueError("Expected a 2x2x2 cube of aligned, nonempty season counts")
    for values in (successes, totals):
        if (not np.isfinite(values).all() or np.any(values < 0)
                or np.any(values != np.floor(values))):
            raise ValueError("Counts must be finite nonnegative integers")
    if np.any(successes > totals):
        raise ValueError("Timely counts must not exceed shared real-alert counts")
    if (not factors or any(type(i) is not int or i not in range(3) for i in factors)
            or len(set(factors)) != len(factors)):
        raise ValueError("Expected a nonempty subset of distinct factor indices 0, 1, 2")
    if type(replicates) is not int or replicates < 1:
        raise ValueError("Bootstrap replicates must be a positive integer")
    if not totals.sum():
        return None, None, None
    signed = np.zeros(len(totals))
    for bits in itertools.product((0, 1), repeat=3):
        weight = (-1) ** (len(factors) - sum(bits[i] for i in factors)) / 2 ** (3-len(factors))
        signed += weight * successes[bits]
    estimate = float(100 * signed.sum() / totals.sum())
    if len(totals) < 2:
        return estimate, None, None
    draws = np.random.default_rng(seed).integers(0, len(totals), (replicates, len(totals)))
    denominators = totals[draws].sum(axis=1)
    valid = denominators > 0
    if not valid.any():
        return estimate, None, None
    ratios = 100 * signed[draws].sum(axis=1)[valid] / denominators[valid]
    low, high = np.quantile(ratios, [0.025, 0.975])
    return estimate, float(low), float(high)


def factorial_grid(protocol):
    if (tuple(protocol["factor_order"]) != FACTORS
            or protocol["n_bases"] != [9, 25]
            or protocol["wind_east_mps"] != [8.0, 12.0]
            or set(protocol["reused_conditions"]) != {"000", "100", "010", "001", "111"}
            or set(protocol["new_conditions"]) != {"110", "101", "011"}
            or protocol["airspeed_mps"] != 18.0
            or protocol["timely_threshold_s"] != 900.0
            or protocol["bootstrap_quantiles"] != [0.025, 0.975]
            or protocol["bootstrap_replicates"] != 1000):
        raise ValueError("Unsupported factorial design or metric definition")
    scenarios = []
    for bases, wind in itertools.product(protocol["n_bases"], protocol["wind_east_mps"]):
        spacing = {9: 16.0, 25: 12.0}[bases]
        if len(base_grid(spacing, CONFIG["domain_km2"])) != bases:
            raise ValueError("Base geometry no longer matches the factorial design")
        for bits in itertools.product((0, 1), repeat=3):
            key = "".join(map(str, bits))
            reused = key in protocol["reused_conditions"]
            levels = [protocol["factors"][name]["stressed" if bit else "reference"]
                      for name, bit in zip(FACTORS, bits)]
            scenarios.append({
                "scenario": f"b{bases}-w{wind:g}-e{bits[0]}-l{bits[1]}-r{bits[2]}",
                "condition": protocol["reused_conditions" if reused else "new_conditions"][key],
                "nominal_spacing_km": spacing, "n_bases": bases, "drones_per_base": 1,
                "wind_east_mps": wind, "airspeed_mps": protocol["airspeed_mps"],
                "endurance_min": levels[0], "reserve_fraction": levels[2],
                "launch_latency_s": levels[1],
                **{f"{name}_stress": bit for name, bit in zip(FACTORS, bits)},
                "provenance": "reused" if reused else "simulated",
            })
    return scenarios


def read_csv(path):
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def load_source(source, scenarios):
    manifest = json.loads((source / "manifest.json").read_text())
    expected_protocol = json.loads((ROOT / "robustness_protocol.json").read_text())
    if (manifest.get("status") != "complete" or manifest.get("schema_version") != 1
            or manifest.get("legacy_config") != CONFIG
            or manifest.get("protocol") != expected_protocol
            or type(manifest.get("seasons")) is not int or manifest["seasons"] < 2
            or type(manifest.get("seed")) is not int or manifest["seed"] < 0):
        raise ValueError("Source must be a complete, compatible robustness capture")
    artifacts = ("alerts.npz", "responses.npz", "summary.csv", "seasons.csv", "comparisons.csv")
    if set(manifest["artifact_sha256"]) != set(artifacts):
        raise ValueError("Source artifact inventory is incomplete")
    for name in artifacts:
        if sha256(source / name) != manifest["artifact_sha256"][name]:
            raise ValueError(f"Source artifact checksum mismatch: {name}")
    for name in ("research.py", "sweep.py", "robustness.py", "robustness_protocol.json",
                 "requirements.txt"):
        if sha256(ROOT / name) != manifest["source_sha256"].get(name):
            raise ValueError(f"Source model/configuration changed: {name}")
    expected = {row["scenario"]: row for row in scenario_grid(expected_protocol)}
    summary_rows = read_csv(source / "summary.csv")
    summaries = {row["scenario"]: row for row in summary_rows}
    if len(summaries) != len(summary_rows) or set(summaries) != set(expected):
        raise ValueError("Source must contain exactly the 20 expected unique scenarios")
    for row in scenarios:
        if row["provenance"] != "reused":
            continue
        old_id = f"b{row['n_bases']}-w{row['wind_east_mps']:g}-{row['condition']}"
        if old_id not in expected:
            raise ValueError("Factorial reuse does not match source conditions")
        for key, value in expected[old_id].items():
            if key != "scenario" and row[key] != value:
                raise ValueError(f"Factor levels differ from source: {key}")
            if key != "scenario":
                saved = summaries[old_id][key]
                if (saved != value if isinstance(value, str) else float(saved) != value):
                    raise ValueError(f"Source summary metadata mismatch: {key}")
    seasons = manifest["seasons"]
    season_rows = read_csv(source / "seasons.csv")
    counts = {(row["scenario"], int(row["season"])): row for row in season_rows}
    if (len(counts) != len(season_rows)
            or set(counts) != set(itertools.product(expected, range(seasons)))):
        raise ValueError("Source season inventory is incomplete or duplicated")
    with np.load(source / "alerts.npz", allow_pickle=False) as capture:
        offsets = capture["offsets"].copy()
        times, points, truth = (capture[key].copy() for key in ("times", "points", "is_real"))
    if (offsets.shape != (seasons+1,) or offsets.dtype.kind not in "iu"
            or offsets[0] != 0 or np.any(np.diff(offsets) < 0)
            or offsets[-1] != len(times) or points.shape != (len(times), 2)
            or truth.shape != times.shape or truth.dtype.kind != "b"
            or not np.isfinite(times).all() or not np.isfinite(points).all()):
        raise ValueError("Source alerts have invalid shapes, values or offsets")
    captures = [(times[a:b], points[a:b], truth[a:b])
                for a, b in zip(offsets[:-1], offsets[1:])]
    totals = np.array([int(c[2].sum()) for c in captures])
    if int(totals.sum()) != manifest["real_alerts_per_scenario"]:
        raise ValueError("Source alert count differs from manifest")
    for identifier in expected:
        for season, total in enumerate(totals):
            row = counts[identifier, season]
            values = [int(row[k]) for k in ("within_15min", "rejected", "served_late")]
            if int(row["real_alerts"]) != total or min(values) < 0 or sum(values) != total:
                raise ValueError("Source season counts do not close against alert inputs")
        for field in ("real_alerts", "within_15min", "rejected", "served_late"):
            if int(summaries[identifier][field]) != sum(int(counts[identifier, s][field])
                                                       for s in range(seasons)):
                raise ValueError("Source aggregate counts do not close against seasons")
    return manifest, summaries, counts, captures, totals


def run_factorial(output, source=DEFAULT_SOURCE):
    output, source = Path(output), Path(source).resolve()
    if output.exists():
        raise FileExistsError(f"Refusing existing output: {output}")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    scenarios = factorial_grid(protocol)
    inherited, old_summary, old_counts, captures, totals = load_source(source, scenarios)
    source_digest = sha256(source / "manifest.json")
    output.mkdir(parents=True, exist_ok=False)
    cfg = inherited["legacy_config"]
    bootstrap_seed = [1, inherited["seed"]]
    replicates = protocol["bootstrap_replicates"]
    summary, season_rows, counts, new_responses, reused_ids = [], [], {}, {}, {}
    for scenario in scenarios:
        identifier = scenario["scenario"]
        if scenario["provenance"] == "reused":
            old_id = f"b{scenario['n_bases']}-w{scenario['wind_east_mps']:g}-{scenario['condition']}"
            reused_ids[identifier] = old_id
            summary.append({**scenario, **{key: old_summary[old_id][key] for key in METRICS}})
            rows = [{**old_counts[old_id, s], "scenario": identifier}
                    for s in range(inherited["seasons"])]
            season_rows.extend(rows)
            counts[identifier] = np.array([int(row["within_15min"]) for row in rows])
            continue
        bases = base_grid(scenario["nominal_spacing_km"], cfg["domain_km2"])
        mission = MissionConfig(
            airspeed_mps=scenario["airspeed_mps"], wind_mps=(scenario["wind_east_mps"], 0.0),
            endurance_min=scenario["endurance_min"], reserve_fraction=scenario["reserve_fraction"],
            max_wind_mps=inherited["protocol"]["max_wind_mps"],
        )
        responses, successes = [], []
        for season, (times, points, truth) in enumerate(captures):
            result = dispatch_physical(times, points, bases, scenario["drones_per_base"],
                                       scenario["launch_latency_s"], cfg, mission)
            real = result["response_s"][truth]
            season_counts = response_counts(real)
            responses.append(real)
            successes.append(season_counts["within_15min"])
            season_rows.append({"scenario": identifier, "season": season, **season_counts})
        combined = np.concatenate(responses)
        new_responses[identifier] = combined
        counts[identifier] = np.array(successes)
        aggregate = response_counts(combined)
        share, low, high = success_interval(counts[identifier], totals, bootstrap_seed, replicates)
        p90 = nearest_rank(combined, 0.9)
        total = aggregate["real_alerts"]
        summary.append({
            **scenario, **aggregate, "within_15min_share": share,
            "mc_95ci_low": low, "mc_95ci_high": high,
            "rejected_share": aggregate["rejected"] / total if total else None,
            "served_late_share": aggregate["served_late"] / total if total else None,
            "p90_s": p90 if p90 is not None and math.isfinite(p90) else None,
            "p90_unreachable": p90 is not None and math.isinf(p90),
            "eur_per_km2_yr": cost_per_km2_yr(scenario["n_bases"],
                                           scenario["drones_per_base"], cfg),
        })
    effects = []
    for bases, wind in itertools.product(protocol["n_bases"], protocol["wind_east_mps"]):
        cube = np.empty((2, 2, 2, inherited["seasons"]), dtype=int)
        for row in scenarios:
            if row["n_bases"] == bases and row["wind_east_mps"] == wind:
                bits = tuple(row[f"{name}_stress"] for name in FACTORS)
                cube[bits] = counts[row["scenario"]]
        for size in range(1, 4):
            for subset in itertools.combinations(range(3), size):
                estimate, low, high = factorial_interval(
                    cube, totals, subset, bootstrap_seed, replicates,
                )
                effects.append({
                    "n_bases": bases, "wind_east_mps": wind,
                    "factors": "+".join(FACTORS[i] for i in subset), "difference_order": size,
                    "real_alerts": int(totals.sum()), "contrast_pp": estimate,
                    "mc_95ci_low_pp": low, "mc_95ci_high_pp": high,
                })
    np.savez_compressed(output / "new_responses.npz",
                        offsets=np.cumsum([0] + totals.tolist()), **new_responses)
    write_csv(output / "summary.csv", summary)
    write_csv(output / "seasons.csv", season_rows)
    write_csv(output / "effects.csv", effects)
    source_names = ("factorial.py", "factorial_protocol.json", "robustness.py",
                    "robustness_protocol.json", "research.py", "sweep.py", "requirements.txt")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=False)
    try:
        source_path = source.relative_to(ROOT).as_posix()
    except ValueError:
        source_path = str(source)
    artifacts = ("summary.csv", "seasons.csv", "effects.csv", "new_responses.npz")
    manifest = {
        "schema_version": 1, "status": "complete", "protocol": protocol,
        "legacy_config": cfg, "seasons": inherited["seasons"], "seed": inherited["seed"],
        "real_alerts_per_scenario": int(totals.sum()), "source_capture": source_path,
        "source_manifest_sha256": source_digest,
        "source_artifact_sha256": inherited["artifact_sha256"],
        "reused_scenarios": reused_ids, "simulated_scenarios": list(new_responses),
        "python": platform.python_version(), "numpy": np.__version__,
        "git_parent_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_sha256": {name: sha256(ROOT / name) for name in source_names},
        "artifact_sha256": {name: sha256(output / name) for name in artifacts},
        "interpretation": [
            "20 cells are copied from the source capture; only 12 missing cells are dispatched.",
            "Same 200-season source inputs in the published study, not independent replication.",
            "Main contrasts average across other factor levels; pair terms are full differences-in-differences.",
            "Pointwise paired season-bootstrap intervals cover Monte Carlo sampling, not input/model uncertainty.",
            "Hypothetical fixed-wind assumptions and proxy costs, not measured performance or operating advice.",
            "All rejected real alerts remain in denominators; false alerts still consume fleet time.",
            "Retain the referenced source capture; old alert/response arrays are not duplicated here.",
        ],
    }
    with (output / "manifest.json").open("x") as handle:
        handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Complete a captured synthetic factorial design, not field validation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    try:
        rows = run_factorial(args.output, args.source)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(f"Wrote {len(rows)} cells (20 reused, 12 new) to {args.output}; not field evidence")


if __name__ == "__main__":
    main()
