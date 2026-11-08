import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np

from research import MissionConfig, dispatch_physical, nearest_rank, success_interval
from sweep import CONFIG, base_grid, cost_per_km2_yr, generate_season


PROTOCOL_PATH = Path(__file__).with_name("robustness_protocol.json")
TIMELY_THRESHOLD_S = 900.0


def paired_interval(candidate, reference, totals, seed, replicates=1000):
    candidate, reference, totals = (
        np.asarray(values, dtype=float) for values in (candidate, reference, totals)
    )
    if (totals.ndim != 1 or not len(totals)
            or candidate.shape != totals.shape or reference.shape != totals.shape):
        raise ValueError("Expected aligned, nonempty season counts")
    for values in (candidate, reference, totals):
        if (not np.isfinite(values).all() or np.any(values < 0)
                or np.any(values != np.floor(values))):
            raise ValueError("Season counts must be finite nonnegative integers")
    if np.any(candidate > totals) or np.any(reference > totals):
        raise ValueError("Timely counts must not exceed shared real-alert counts")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValueError("Bootstrap replicates must be a positive integer")
    if not totals.sum():
        return None, None, None
    difference = candidate - reference
    estimate = float(100 * difference.sum() / totals.sum())
    if len(totals) < 2:
        return estimate, None, None
    draws = np.random.default_rng(seed).integers(0, len(totals), (replicates, len(totals)))
    denominators = totals[draws].sum(axis=1)
    valid = denominators > 0
    if not valid.any():
        return estimate, None, None
    ratios = 100 * difference[draws].sum(axis=1)[valid] / denominators[valid]
    low, high = np.quantile(ratios, [0.025, 0.975])
    return estimate, float(low), float(high)


def response_counts(response_s):
    values = np.asarray(response_s, dtype=float)
    if values.ndim != 1 or np.isnan(values).any() or (values < 0).any():
        raise ValueError("Expected a vector of nonnegative responses, including positive infinity")
    timely = int(np.count_nonzero(values <= TIMELY_THRESHOLD_S))
    rejected = int(np.count_nonzero(np.isinf(values)))
    return {
        "real_alerts": len(values), "within_15min": timely,
        "rejected": rejected, "served_late": len(values) - timely - rejected,
    }


def scenario_grid(protocol):
    scenarios = []
    for layout in protocol["layouts"]:
        actual_bases = len(base_grid(layout["nominal_spacing_km"], CONFIG["domain_km2"]))
        if actual_bases != layout["n_bases"]:
            raise ValueError("Protocol base count does not match grid geometry")
        for wind in protocol["wind_east_mps"]:
            for condition in protocol["conditions"]:
                scenarios.append({
                    "scenario": f"b{actual_bases}-w{wind:g}-{condition['name']}",
                    "condition": condition["name"],
                    "nominal_spacing_km": layout["nominal_spacing_km"],
                    "n_bases": actual_bases, "drones_per_base": layout["drones_per_base"],
                    "wind_east_mps": wind, "airspeed_mps": protocol["airspeed_mps"],
                    "endurance_min": condition["endurance_min"],
                    "reserve_fraction": condition["reserve_fraction"],
                    "launch_latency_s": condition["launch_latency_s"],
                })
    if len({row["scenario"] for row in scenarios}) != len(scenarios):
        raise ValueError("Scenario identifiers must be unique")
    return scenarios


def write_csv(path, rows):
    with Path(path).open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def comparison_rows(scenarios, counts, totals, seed, replicates):
    pairs = []
    for scenario in scenarios:
        identifier = scenario["scenario"]
        base = scenario["n_bases"]
        wind = scenario["wind_east_mps"]
        condition = scenario["condition"]
        if condition != "reference":
            pairs.append(("stress", identifier, f"b{base}-w{wind:g}-reference"))
        if base == 25:
            pairs.append(("density", identifier, f"b9-w{wind:g}-{condition}"))
    rows = []
    for kind, candidate, reference in pairs:
        delta, low, high = paired_interval(counts[candidate], counts[reference], totals,
                                           seed=seed, replicates=replicates)
        rows.append({
            "comparison": f"{candidate}_minus_{reference}", "kind": kind,
            "candidate": candidate, "reference": reference, "real_alerts": int(totals.sum()),
            "delta_within_15min_pp": delta, "mc_95ci_low_pp": low, "mc_95ci_high_pp": high,
        })
    return rows


def run_robustness(output, seasons=200, seed=20261108):
    if isinstance(seasons, bool) or not isinstance(seasons, int) or seasons < 2:
        raise ValueError("At least two integer seasons are required")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if (protocol["timely_threshold_s"] != TIMELY_THRESHOLD_S
            or protocol["bootstrap_quantiles"] != [0.025, 0.975]):
        raise ValueError("Protocol metric definitions do not match this runner")
    scenarios = scenario_grid(protocol)
    cfg = dict(CONFIG)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    captures = [
        generate_season(np.random.default_rng(np.random.SeedSequence([0, season, seed])),
                        cfg, protocol["ignitions_per_season"], protocol["false_alarm_fraction"])
        for season in range(seasons)
    ]
    np.savez_compressed(
        output / "alerts.npz",
        offsets=np.cumsum([0] + [len(c[0]) for c in captures]),
        times=np.concatenate([c[0] for c in captures]),
        points=np.concatenate([c[1] for c in captures]),
        is_real=np.concatenate([c[2] for c in captures]),
    )
    totals = np.array([int(c[2].sum()) for c in captures])
    bootstrap_seed = [1, seed]
    replicates = protocol["bootstrap_replicates"]
    summary, seasons_rows, counts, response_capture = [], [], {}, {}
    for scenario in scenarios:
        identifier = scenario["scenario"]
        bases = base_grid(scenario["nominal_spacing_km"], cfg["domain_km2"])
        mission = MissionConfig(
            airspeed_mps=scenario["airspeed_mps"],
            wind_mps=(scenario["wind_east_mps"], 0.0),
            endurance_min=scenario["endurance_min"],
            reserve_fraction=scenario["reserve_fraction"],
            max_wind_mps=protocol["max_wind_mps"],
        )
        responses, successes = [], []
        for season, (times, points, truth) in enumerate(captures):
            result = dispatch_physical(times, points, bases, scenario["drones_per_base"],
                                       scenario["launch_latency_s"], cfg, mission)
            real = result["response_s"][truth]
            season_counts = response_counts(real)
            responses.append(real)
            successes.append(season_counts["within_15min"])
            seasons_rows.append({"scenario": identifier, "season": season, **season_counts})
        combined = np.concatenate(responses)
        response_capture[identifier] = combined
        counts[identifier] = np.array(successes)
        aggregate = response_counts(combined)
        probability, low, high = success_interval(
            counts[identifier], totals, seed=bootstrap_seed, replicates=replicates,
        )
        p90 = nearest_rank(combined, 0.9)
        total = aggregate["real_alerts"]
        summary.append({
            **scenario, **aggregate, "within_15min_share": probability,
            "mc_95ci_low": low, "mc_95ci_high": high,
            "rejected_share": aggregate["rejected"] / total if total else None,
            "served_late_share": aggregate["served_late"] / total if total else None,
            "p90_s": p90 if p90 is not None and math.isfinite(p90) else None,
            "p90_unreachable": p90 is not None and math.isinf(p90),
            "eur_per_km2_yr": cost_per_km2_yr(scenario["n_bases"],
                                           scenario["drones_per_base"], cfg),
        })
    np.savez_compressed(output / "responses.npz", offsets=np.cumsum([0] + totals.tolist()),
                        **response_capture)
    write_csv(output / "summary.csv", summary)
    write_csv(output / "seasons.csv", seasons_rows)
    write_csv(output / "comparisons.csv",
              comparison_rows(scenarios, counts, totals, bootstrap_seed, replicates))
    source_paths = [Path(__file__), PROTOCOL_PATH, Path(__file__).with_name("research.py"),
                    Path(__file__).with_name("sweep.py"), Path(__file__).with_name("requirements.txt")]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, check=False)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=Path(__file__).parent,
                            capture_output=True, text=True, check=False)
    artifacts = ("alerts.npz", "responses.npz", "summary.csv", "seasons.csv", "comparisons.csv")
    manifest = {
        "schema_version": 1, "status": "complete", "protocol": protocol, "legacy_config": cfg,
        "seasons": seasons, "seed": seed, "real_alerts_per_scenario": int(totals.sum()),
        "python": platform.python_version(), "numpy": np.__version__,
        "git_parent_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "git_worktree_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        "artifact_sha256": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in artifacts
        },
        "interpretation": [
            "Stress values are hypothetical, not measured aircraft derating or operating advice.",
            "All scenarios share real and false alerts; false alerts consume fleet time.",
            "Intervals are pointwise season-cluster Monte Carlo intervals, not field uncertainty.",
            "Wind is fixed eastward throughout each season; no weather probabilities are inferred.",
            "Blank p90 with p90_unreachable=True denotes infinity; rejected alerts remain included.",
            "Historical proxy costs are unchanged, not supplier quotes or stress-adjusted economics.",
            "Launch consumes fleet busy time but not airborne endurance in the unchanged model.",
            "Source hashes identify executed files even when Git worktree is dirty.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Synthetic paired assumption stress study, not field validation")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seasons", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20261108)
    args = parser.parse_args()
    try:
        rows = run_robustness(args.output, seasons=args.seasons, seed=args.seed)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(f"Wrote {len(rows)} paired synthetic scenarios to {args.output}; not field evidence")


if __name__ == "__main__":
    main()
