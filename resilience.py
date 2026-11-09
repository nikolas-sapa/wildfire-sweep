import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np

from research import MissionConfig, dispatch_physical
from robustness import response_counts
from sweep import CONFIG, base_grid, generate_season


PROTOCOL_PATH = Path(__file__).with_name("resilience_protocol.json")
SOURCE_FILES = ("resilience.py", "research.py", "robustness.py", "sweep.py", "requirements.txt")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_csv(path, rows):
    with Path(path).open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def save_arrays(path, **arrays):
    with Path(path).open("xb") as handle:
        np.savez_compressed(handle, **arrays)


def geometry(case, cfg):
    bases = base_grid(case["nominal_spacing_km"], cfg["domain_km2"])
    if len(bases) != case["n_bases"] or not -1 <= case["offline_base"] < len(bases):
        raise ValueError("Case geometry disagrees with declared base count or outage")
    return np.delete(bases, case["offline_base"], axis=0) if case["offline_base"] >= 0 else bases


def case_grid(protocol, selection=None):
    cases = []
    for layout in protocol["layouts"]:
        for wind in protocol["wind_east_mps"]:
            if selection is None:
                missing = [-1] + list(range(layout["n_bases"]))
            else:
                matches = [row["offline_base"] for row in selection
                           if row["n_bases"] == layout["n_bases"] and row["wind_east_mps"] == wind]
                if len(matches) != 1:
                    raise ValueError("Exactly one frozen outage per layout/wind is required")
                missing = [-1, matches[0]]
            for site in missing:
                cases.append({**layout, "wind_east_mps": wind, "offline_base": site,
                              "case_id": f"b{layout['n_bases']}-w{wind:g}-off{site}"})
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("Case IDs must be unique")
    return cases


def select_sites(cases, timely):
    counts = np.asarray(timely)
    if counts.ndim != 2 or counts.shape[0] != len(cases) or np.any(counts < 0):
        raise ValueError("Aligned nonnegative training season counts required")
    groups = sorted({(case["n_bases"], case["wind_east_mps"]) for case in cases})
    selected = []
    for bases, wind in groups:
        eligible = [i for i, case in enumerate(cases)
                    if case["n_bases"] == bases and case["wind_east_mps"] == wind
                    and case["offline_base"] >= 0]
        winner = min(eligible, key=lambda i: (int(counts[i].sum()), cases[i]["offline_base"]))
        selected.append({**cases[winner], "training_timely": int(counts[winner].sum())})
    return selected


def percent_interval(numerator, totals, draws):
    numerator, totals = np.asarray(numerator, dtype=float), np.asarray(totals, dtype=float)
    indices = np.asarray(draws)
    if (totals.ndim != 1 or numerator.shape != totals.shape or not len(totals)
            or not np.isfinite(totals).all() or not np.isfinite(numerator).all()
            or np.any(totals < 0) or np.any(totals != np.floor(totals))
            or np.any(numerator != np.floor(numerator))):
        raise ValueError("Aligned finite integer counts required")
    if (indices.ndim != 2 or indices.shape[1] != len(totals) or not len(indices)
            or not np.issubdtype(indices.dtype, np.integer)
            or np.any(indices < 0) or np.any(indices >= len(totals))):
        raise ValueError("Aligned in-range integer season draws required")
    if not totals.sum():
        return None, None, None
    estimate = float(100 * numerator.sum() / totals.sum())
    denominators = totals[indices].sum(axis=1)
    valid = denominators > 0
    if len(totals) < 2 or not valid.any():
        return estimate, None, None
    values = 100 * numerator[indices].sum(axis=1)[valid] / denominators[valid]
    low, high = np.quantile(values, [0.025, 0.975])
    return estimate, float(low), float(high)


def capture_alerts(output, phase, count, protocol, cfg):
    stream = 0 if phase == "training" else 1
    captures = [generate_season(
        np.random.default_rng(np.random.SeedSequence([stream, i, protocol["seed"]])),
        cfg, protocol["ignitions_per_season"], protocol["false_alarm_fraction"],
    ) for i in range(count)]
    save_arrays(output / f"{phase}_alerts.npz",
                offsets=np.cumsum([0] + [len(row[0]) for row in captures]),
                times=np.concatenate([row[0] for row in captures]),
                points=np.concatenate([row[1] for row in captures]),
                is_real=np.concatenate([row[2] for row in captures]))
    return captures


def evaluate_phase(output, phase, captures, cases, protocol, cfg):
    responses, rows, summaries, timely = [], [], [], []
    totals = np.array([int(capture[2].sum()) for capture in captures])
    for number, case in enumerate(cases):
        bases = geometry(case, cfg)
        mission = MissionConfig(
            airspeed_mps=protocol["airspeed_mps"], wind_mps=(case["wind_east_mps"], 0.0),
            endurance_min=protocol["endurance_min"], reserve_fraction=protocol["reserve_fraction"],
            max_wind_mps=protocol["max_wind_mps"])
        all_responses, counts = [], []
        for season, (times, points, real) in enumerate(captures):
            result = dispatch_physical(times, points, bases, case["drones_per_base"],
                                       protocol["launch_latency_s"], cfg, mission)
            values = result["response_s"]
            count = response_counts(values[real])
            rows.append({"case_id": case["case_id"], "season": season, **count})
            counts.append(count)
            all_responses.append(values)
        responses.append(np.concatenate(all_responses))
        timely.append([row["within_15min"] for row in counts])
        pooled = {key: sum(row[key] for row in counts) for key in counts[0]}
        summaries.append({**case, "active_bases": len(bases), **pooled})
        print(f"{phase}: {number + 1}/{len(cases)} {case['case_id']}", flush=True)
    save_arrays(output / f"{phase}_responses.npz",
                case_ids=np.array([case["case_id"] for case in cases]),
                responses_s=np.array(responses))
    write_csv(output / f"{phase}_counts.csv", rows)
    return np.array(timely), totals, summaries


def contrast_rows(cases, timely, totals, draws, winds):
    lookup = {case["case_id"]: timely[i] for i, case in enumerate(cases)}
    rows, losses = [], {}
    for case in cases:
        if case["offline_base"] < 0:
            continue
        healthy = f"b{case['n_bases']}-w{case['wind_east_mps']:g}-off-1"
        difference = lookup[case["case_id"]] - lookup[healthy]
        losses[(case["n_bases"], case["wind_east_mps"])] = difference
        estimate, low, high = percent_interval(difference, totals, draws)
        rows.append({"contrast": f"{case['case_id']}_minus_healthy", "kind": "outage",
                     "n_bases": case["n_bases"], "wind_east_mps": case["wind_east_mps"],
                     "candidate": case["case_id"], "reference": healthy,
                     "delta_timely_pp": estimate, "mc95_low_pp": low, "mc95_high_pp": high})
    for wind in winds:
        difference = losses[(25, wind)] - losses[(9, wind)]
        estimate, low, high = percent_interval(difference, totals, draws)
        rows.append({"contrast": f"loss25_minus_loss9-w{wind:g}", "kind": "loss_difference",
                     "n_bases": "", "wind_east_mps": wind,
                     "candidate": "outage25_minus_healthy25",
                     "reference": "outage9_minus_healthy9",
                     "delta_timely_pp": estimate, "mc95_low_pp": low, "mc95_high_pp": high})
    return rows


def source_fingerprints():
    return {name: digest(Path(__file__).with_name(name)) for name in SOURCE_FILES}


def load_protocol(path):
    raw = Path(path).read_bytes()
    protocol = json.loads(raw)
    for name in ("seed", "training_seasons", "heldout_seasons", "bootstrap_replicates"):
        value = protocol[name]
        if type(value) is not int or value < (0 if name == "seed" else 2):
            raise ValueError(f"{name} must be an integer in range")
    if (type(protocol["schema_version"]) is not int or protocol["schema_version"] != 1
            or protocol["timely_threshold_s"] != 900
            or protocol["bootstrap_quantiles"] != [0.025, 0.975]
            or protocol["wind_east_mps"] != [8.0, 12.0]
            or sorted(row["n_bases"] for row in protocol["layouts"]) != [9, 25]):
        raise ValueError("Protocol structure or fixed comparison definitions disagree")
    if (not math.isfinite(protocol["ignitions_per_season"]) or protocol["ignitions_per_season"] <= 0
            or not 0 <= protocol["false_alarm_fraction"] < 1
            or not math.isfinite(protocol["launch_latency_s"]) or protocol["launch_latency_s"] < 0):
        raise ValueError("Invalid alert or launch assumptions")
    return protocol, raw


def run_resilience(output, protocol_path=PROTOCOL_PATH):
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output}")
    protocol, protocol_bytes = load_protocol(protocol_path)
    sources = source_fingerprints()
    cfg = dict(CONFIG)
    training_cases = case_grid(protocol)
    for case in training_cases:
        geometry(case, cfg)
    output.mkdir(parents=True, exist_ok=False)
    with (output / "protocol.json").open("xb") as handle:
        handle.write(protocol_bytes)
    write_json(output / "config.json", cfg)
    sites = []
    for layout in protocol["layouts"]:
        for site, (x, y) in enumerate(base_grid(layout["nominal_spacing_km"], cfg["domain_km2"])):
            sites.append({"n_bases": layout["n_bases"], "site_id": site,
                          "x_km": float(x), "y_km": float(y)})
    write_csv(output / "base_sites.csv", sites)
    training = capture_alerts(output, "training", protocol["training_seasons"], protocol, cfg)
    train_counts, train_totals, train_summary = evaluate_phase(
        output, "training", training, training_cases, protocol, cfg)
    write_csv(output / "training_summary.csv", train_summary)
    selection = select_sites(training_cases, train_counts)
    for row in selection:
        row["training_real_alerts"] = int(train_totals.sum())
        row["selection_rule"] = protocol["selection"]
    write_csv(output / "selection.csv", selection)
    selection_digest = digest(output / "selection.csv")
    heldout_cases = case_grid(protocol, selection)
    if digest(output / "selection.csv") != selection_digest:
        raise ValueError("Frozen selection changed before held-out generation")
    heldout = capture_alerts(output, "heldout", protocol["heldout_seasons"], protocol, cfg)
    counts, totals, summary = evaluate_phase(output, "heldout", heldout, heldout_cases, protocol, cfg)
    draws = np.random.default_rng([2, protocol["seed"]]).integers(
        0, len(totals), (protocol["bootstrap_replicates"], len(totals)))
    save_arrays(output / "bootstrap_draws.npz", season_indices=draws)
    for row, numerator in zip(summary, counts):
        estimate, low, high = percent_interval(numerator, totals, draws)
        row.update(timely_percent=estimate, mc95_low_percent=low, mc95_high_percent=high)
    write_csv(output / "summary.csv", summary)
    contrasts = contrast_rows(heldout_cases, counts, totals, draws, protocol["wind_east_mps"])
    write_csv(output / "contrasts.csv", contrasts)
    if (source_fingerprints() != sources or Path(protocol_path).read_bytes() != protocol_bytes
            or digest(output / "selection.csv") != selection_digest):
        raise ValueError("Study source, protocol or frozen selection changed during run")
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                         capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=Path(__file__).parent,
                           capture_output=True, text=True, check=True).stdout.strip() != ""
    write_json(output / "manifest.json", {
        "schema_version": 1, "status": "complete", "study_type": protocol["study_type"],
        "protocol": protocol, "protocol_sha256": hashlib.sha256(protocol_bytes).hexdigest(),
        "config": cfg, "source_sha256": sources, "selection_sha256": selection_digest,
        "training_cases": len(training_cases), "heldout_cases": len(heldout_cases),
        "contrasts": len(contrasts), "training_real_alerts": int(train_totals.sum()),
        "heldout_real_alerts": int(totals.sum()), "git_commit": git, "git_dirty": dirty,
        "python": platform.python_version(), "numpy": np.__version__,
        "artifact_sha256": {path.name: digest(path) for path in sorted(output.iterdir())},
        "limitations": [
            "Synthetic uniform alerts, square geometry, fixed hypothetical winds and aircraft inputs.",
            "One base and its drone are unavailable throughout a season; no observed failure probabilities.",
            "Selected sites are worst in training, not guaranteed worst on held-out data.",
            "Pointwise Monte Carlo intervals condition on selection; no input, selection or field uncertainty.",
            "Layouts use different infrastructure amounts; not equal-budget optimization.",
            "No detector accuracy, ignition-to-alert latency, autonomous flight or deployment evidence.",
        ],
    })
    return output


def main():
    parser = argparse.ArgumentParser(description="Held-out synthetic single-base outage study")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        run_resilience(args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
