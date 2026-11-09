import argparse
from bisect import bisect_right
import csv
import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import platform

import numpy as np

from cohort_registry import ID_PATTERN, METRICS, ROOT, load_protocol, load_registry
from event_evaluation import sha256


COUNT_FIELDS = (
    "n_samples", "fire_episodes", "alarm_episodes", "detected_fire_episodes",
    "missed_fire_episodes", "matched_alarm_episodes", "duplicate_alarm_episodes",
    "false_alarm_episodes", "unmatched_alarm_episodes", "left_censored_fire_episodes",
    "right_censored_fire_episodes",
)
UNITS = {"event_recall": "fraction", "alarm_precision": "fraction",
         "false_alarms_per_nonfire_hour": "per_nonfire_hour",
         "detected_delay_p50_s": "seconds", "detected_delay_p90_s": "seconds"}
SUMMARY_FIELDS = ("metric", "estimate", "ci_95_low", "ci_95_high", "unit", "n_records",
                  "n_clusters", "informative_clusters", "valid_bootstrap_draws", "ci_status")
LIMITATIONS = [
    "Sampled visible-fire episodes are not wildfire incidents or ignition-to-detection measurements.",
    "No independently labelled real footage or field accuracy is established by this software.",
    "Exposure is nominal sampled-bin time; prefix-edge censoring remains in the reported counts.",
    "Detected-only delay quantiles exclude misses; inspect recall and missed counts alongside delays.",
    "Cluster/site/date declarations are self-reported; file hashes cannot detect re-encodings or overlapping clips.",
    "Pointwise nominal 95% cluster-bootstrap coverage is not guaranteed, especially with small cohorts.",
    "Two informative clusters are a computational minimum, not an adequate empirical sample size.",
    "Intervals assume declared clusters are independent; they exclude label, model and input uncertainty.",
    "Undefined bootstrap denominators are omitted per metric and valid draw counts are reported.",
    "No acceptance verdict, tuning, physical-incident recall or flight authorization is produced.",
]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite nonnegative numeric metric")
    return float(value)


def _close(actual, expected):
    if expected is None:
        if actual is not None:
            raise ValueError("An undefined metric must be null")
    elif not math.isclose(_number(actual), expected, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("Captured metric disagrees with counts, exposure or event details")


def _nearest(delays, probability):
    return delays[math.ceil(probability*len(delays))-1] if delays else None


def _episodes(values, count, fps):
    if not isinstance(values, list):
        raise ValueError("Captured episode details must be lists")
    previous_end = -1
    for row in values:
        if not isinstance(row, dict):
            raise ValueError("Invalid captured episode detail")
        start, end = row.get("start_sample"), row.get("end_sample")
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= count or start <= previous_end):
            raise ValueError("Episode runs must be maximal, ordered and within the sampled prefix")
        _close(row.get("start_time_s"), start/fps)
        _close(row.get("end_time_s"), end/fps)
        previous_end = end
    return values


def _validated_metrics(metrics):
    required = set(COUNT_FIELDS) | set(METRICS) | {
        "sample_fps", "sampled_exposure_s", "nonfire_exposure_s",
        "fire_episode_details", "alarm_episode_details",
    }
    if not isinstance(metrics, dict) or not required.issubset(metrics):
        raise ValueError("Incomplete captured episode metrics")
    if any(type(metrics[key]) is not int or metrics[key] < 0 for key in COUNT_FIELDS):
        raise ValueError("Captured event/sample counts must be nonnegative integers")
    count, fps = metrics["n_samples"], _number(metrics["sample_fps"])
    if not 1 <= count <= 100000 or not 0 < fps <= 30 or not math.isfinite(count/fps):
        raise ValueError("Invalid sampled prefix or rate")
    fires = _episodes(metrics["fire_episode_details"], count, fps)
    alarms = _episodes(metrics["alarm_episode_details"], count, fps)
    delays = []
    for index, fire in enumerate(fires):
        if any(type(fire.get(key)) is not bool for key in ("detected", "left_censored", "right_censored")):
            raise ValueError("Fire detection/censor flags must be boolean")
        if (fire["left_censored"] != (fire["start_sample"] == 0)
                or fire["right_censored"] != (fire["end_sample"] == count)):
            raise ValueError("Censor flags disagree with prefix edges")
        alarm_index = fire.get("alarm_episode_index")
        if fire["detected"]:
            if type(alarm_index) is not int or not 0 <= alarm_index < len(alarms):
                raise ValueError("Detected fire has no valid matched alarm")
            alarm = alarms[alarm_index]
            if (alarm.get("status") != "matched" or alarm.get("fire_episode_index") != index
                    or not fire["start_sample"] <= alarm["start_sample"] < fire["end_sample"]):
                raise ValueError("Matched alarm does not bind to this fire")
            delay = _number(fire.get("delay_s"))
            _close(delay, (alarm["start_sample"]-fire["start_sample"])/fps)
            delays.append(delay)
        elif fire.get("delay_s") is not None or alarm_index is not None:
            raise ValueError("Missed fires cannot carry a detected delay or alarm")
    starts = [fire["start_sample"] for fire in fires]
    statuses = {"matched": 0, "duplicate": 0, "false": 0}
    for index, alarm in enumerate(alarms):
        onset, status = alarm["start_sample"], alarm.get("status")
        if status not in statuses:
            raise ValueError("Unknown alarm matching status")
        candidate = bisect_right(starts, onset)-1
        inside = candidate >= 0 and onset < fires[candidate]["end_sample"]
        if status == "false":
            if inside or alarm.get("fire_episode_index") is not None:
                raise ValueError("False alarm must start on a negative sample")
        elif not inside or alarm.get("fire_episode_index") != candidate:
            raise ValueError("Alarm onset does not belong to its declared fire")
        else:
            fire = fires[candidate]
            if (not fire["detected"] or (status == "matched" and fire["alarm_episode_index"] != index)
                    or (status == "duplicate" and fire["alarm_episode_index"] >= index)):
                raise ValueError("Alarm first-match/duplicate ordering is inconsistent")
        statuses[status] += 1
    expected = {
        "fire_episodes": len(fires), "alarm_episodes": len(alarms),
        "detected_fire_episodes": len(delays), "missed_fire_episodes": len(fires)-len(delays),
        "matched_alarm_episodes": len(delays), "duplicate_alarm_episodes": statuses["duplicate"],
        "false_alarm_episodes": statuses["false"],
        "unmatched_alarm_episodes": statuses["duplicate"]+statuses["false"],
        "left_censored_fire_episodes": sum(fire["left_censored"] for fire in fires),
        "right_censored_fire_episodes": sum(fire["right_censored"] for fire in fires),
    }
    if any(metrics[key] != value for key, value in expected.items()) or statuses["matched"] != len(delays):
        raise ValueError("Captured event counts do not close against episode details")
    negative_exposure = (count-sum(fire["end_sample"]-fire["start_sample"] for fire in fires))/fps
    _close(metrics["sampled_exposure_s"], count/fps)
    _close(metrics["nonfire_exposure_s"], negative_exposure)
    delays.sort()
    _close(metrics["event_recall"], len(delays)/len(fires) if fires else None)
    _close(metrics["alarm_precision"], len(delays)/len(alarms) if alarms else None)
    _close(metrics["false_alarms_per_nonfire_hour"],
           statuses["false"]*3600/negative_exposure if negative_exposure else None)
    _close(metrics["detected_delay_p50_s"], _nearest(delays, 0.5))
    _close(metrics["detected_delay_p90_s"], _nearest(delays, 0.9))
    return {**{key: metrics[key] for key in COUNT_FIELDS}, "sample_fps": fps,
            "sampled_exposure_s": _number(metrics["sampled_exposure_s"]),
            "nonfire_exposure_s": _number(metrics["nonfire_exposure_s"]),
            "detected_delays_s": delays}


def _prepare(records):
    if not records:
        raise ValueError("At least one captured test recording is required")
    prepared, identities = [], set()
    for record in records:
        for key in ("recording_id", "cluster_id"):
            if not isinstance(record.get(key), str) or ID_PATTERN.fullmatch(record[key]) is None:
                raise ValueError("Invalid recording/cluster identity")
        if record["recording_id"] in identities:
            raise ValueError("Duplicate recording identity")
        identities.add(record["recording_id"])
        prepared.append({**_validated_metrics(record["metrics"]),
                         "recording_id": record["recording_id"], "cluster_id": record["cluster_id"]})
    if len({row["sample_fps"] for row in prepared}) != 1:
        raise ValueError("Sampling rates must match to preserve persistence semantics")
    return sorted(prepared, key=lambda row: row["recording_id"])


def _pool(records):
    pooled = {key: sum(row[key] for row in records) for key in COUNT_FIELDS}
    for key in ("sampled_exposure_s", "nonfire_exposure_s"):
        try:
            pooled[key] = math.fsum(row[key] for row in records)
        except OverflowError as exc:
            raise ValueError("Pooled exposure exceeds finite numeric range") from exc
    delays = sorted(value for row in records for value in row["detected_delays_s"])
    pooled["detected_delays_s"] = delays
    pooled["n_records"] = sum(row.get("n_records", 1) for row in records)
    pooled["event_recall"] = pooled["detected_fire_episodes"]/pooled["fire_episodes"] if pooled["fire_episodes"] else None
    pooled["alarm_precision"] = pooled["matched_alarm_episodes"]/pooled["alarm_episodes"] if pooled["alarm_episodes"] else None
    pooled["false_alarms_per_nonfire_hour"] = (
        pooled["false_alarm_episodes"]*3600/pooled["nonfire_exposure_s"] if pooled["nonfire_exposure_s"] else None
    )
    pooled["detected_delay_p50_s"] = _nearest(delays, 0.5)
    pooled["detected_delay_p90_s"] = _nearest(delays, 0.9)
    return pooled


def cohort_metrics(records):
    prepared = _prepare(records)
    return {**_pool(prepared), "n_clusters": len({row["cluster_id"] for row in prepared})}


def cohort_intervals(records, seed=20261109, replicates=1000):
    if type(seed) is not int or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    if type(replicates) is not int or not 1 <= replicates <= 10000:
        raise ValueError("Bootstrap replicates must be an integer in [1, 10000]")
    prepared = _prepare(records)
    members = {}
    for record in prepared:
        members.setdefault(record["cluster_id"], []).append(record)
    cluster_ids = sorted(members)
    groups = [_pool(members[key]) for key in cluster_ids]
    aggregate = {**_pool(prepared), "n_clusters": len(groups)}
    informative = {metric: sum(group[metric] is not None for group in groups) for metric in METRICS}
    draws = np.random.default_rng(seed).integers(0, len(groups), size=(replicates, len(groups)))
    samples = {metric: [] for metric in METRICS}
    for draw in draws:
        result = _pool([groups[int(index)] for index in draw])
        for metric in METRICS:
            if result[metric] is not None:
                samples[metric].append(result[metric])
    intervals = {}
    for metric in METRICS:
        point, values = aggregate[metric], samples[metric]
        if point is None:
            status, bounds = "undefined", (None, None)
        elif informative[metric] < 2:
            status, bounds = "insufficient_clusters", (None, None)
        else:
            if not values:
                raise ValueError(f"No defined bootstrap draws for interval-eligible metric: {metric}")
            status = "cluster_bootstrap"
            bounds = tuple(float(value) for value in np.quantile(values, [0.025, 0.975], method="linear"))
        intervals[metric] = {
            "estimate": point, "ci_95_low": bounds[0], "ci_95_high": bounds[1],
            "unit": UNITS[metric], "informative_clusters": informative[metric],
            "valid_bootstrap_draws": len(values), "ci_status": status,
        }
    return {"aggregate": aggregate, "intervals": intervals, "cluster_ids": cluster_ids,
            "draws": draws, "seed": seed, "replicates": replicates, "records": prepared}


def _digest_bytes(content):
    return hashlib.sha256(content).hexdigest()


def _hash_map(value, required):
    if (not isinstance(value, dict) or not set(required).issubset(value)
            or any(not isinstance(digest, str) or len(digest) != 64
                   or any(character not in "0123456789abcdef" for character in digest)
                   for digest in value.values())):
        raise ValueError("Missing or malformed capture provenance fingerprints")
    return value


def _read_report(registry, row, event_protocol, event_protocol_digest):
    directory = registry / row["event_report_dir"]
    manifest_content = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_content)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "complete" or manifest.get("split") != "test"
            or manifest.get("recording_id") != row["recording_id"]
            or manifest.get("input_sha256") != row["input_sha256"]
            or manifest.get("protocol") != event_protocol):
        raise ValueError("Test report identity, status or event protocol disagrees with registry")
    inputs = _hash_map(manifest.get("input_manifest_sha256"), ("annotation", "predictions"))
    _hash_map(manifest.get("input_artifact_sha256"),
              ("predictions.csv", "packet_labels.csv", "completed_labels.csv"))
    if inputs["annotation"] != row["packet_manifest_sha256"]:
        raise ValueError("Event report does not bind to the registered annotation packet")
    sources = _hash_map(manifest.get("source_sha256"),
                        ("event_evaluation.py", "event_protocol.json", "detection.py"))
    if sources["event_protocol.json"] != event_protocol_digest:
        raise ValueError("Captured event protocol fingerprint disagrees")
    config = manifest.get("prediction_config")
    if not isinstance(config, dict) or not config:
        raise ValueError("A captured detector configuration is required")
    rate = _number(manifest.get("sample_fps"))
    if (rate != row["sample_fps"] or type(manifest.get("decoded_frames")) is not int
            or manifest["decoded_frames"] != row["decoded_frames"]):
        raise ValueError("Report sampling settings disagree with the registered packet")
    report_content = (directory / "report.json").read_bytes()
    digest = _digest_bytes(report_content)
    if manifest.get("artifact_sha256") != {"report.json": digest}:
        raise ValueError("Event report artifact checksum mismatch")
    report = json.loads(report_content)
    if (not isinstance(report, dict) or report.get("schema_version") != 1
            or not isinstance(report.get("metrics"), dict)):
        raise ValueError("Malformed captured episode report")
    metrics = report["metrics"]
    if metrics.get("sample_fps") != rate or metrics.get("n_samples") != row["decoded_frames"]:
        raise ValueError("Captured metrics and report sampling settings disagree")
    compatibility = json.dumps({
        "source_sha256": sources, "decoder_sha256": row["decoder_sha256"],
        "config": config, "sample_fps": rate,
    }, sort_keys=True, allow_nan=False)
    return {
        "recording_id": row["recording_id"], "cluster_id": row["cluster_id"], "metrics": metrics,
        "input_sha256": row["input_sha256"], "report_manifest_sha256": _digest_bytes(manifest_content),
        "report_sha256": digest,
    }, compatibility


def run_cohort(registry, output, seed=20261109):
    registry, output = Path(registry).resolve(), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output}")
    frozen, registry_digest = load_registry(registry)
    protocol, protocol_digest = load_protocol()
    event_bytes = (ROOT / "event_protocol.json").read_bytes()
    event_protocol, event_digest = json.loads(event_bytes), _digest_bytes(event_bytes)
    records, compatibility = [], None
    for row in sorted(frozen["records"], key=lambda item: item["recording_id"]):
        if row["split"] != "test":
            continue
        record, signature = _read_report(registry, row, event_protocol, event_digest)
        if compatibility is not None and signature != compatibility:
            raise ValueError("Cohort test reports use incompatible detector/configuration/decoder/sampling sources")
        compatibility = signature
        records.append(record)
    result = cohort_intervals(records, seed=seed, replicates=protocol["bootstrap_replicates"])
    summary = [
        {"metric": metric, **result["intervals"][metric],
         "n_records": result["aggregate"]["n_records"], "n_clusters": result["aggregate"]["n_clusters"]}
        for metric in METRICS
    ]
    provenance = [{key: record[key] for key in
                   ("recording_id", "cluster_id", "input_sha256", "report_manifest_sha256", "report_sha256")}
                  for record in records]
    report = {
        "schema_version": 1, "aggregate": result["aggregate"], "intervals": result["intervals"],
        "cluster_ids": result["cluster_ids"], "seed": seed, "replicates": result["replicates"],
        "recordings": result["records"], "input_reports": provenance, "limitations": LIMITATIONS,
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "summary.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary)
    record_fields = ("recording_id", "cluster_id", "input_sha256") + COUNT_FIELDS + (
        "sampled_exposure_s", "nonfire_exposure_s", "report_manifest_sha256", "report_sha256",
    )
    with (output / "records.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=record_fields, lineterminator="\n")
        writer.writeheader()
        source_by_id = {source["recording_id"]: source for source in provenance}
        for stats in result["records"]:
            source = source_by_id[stats["recording_id"]]
            writer.writerow({key: (source[key] if key in source else stats[key]) for key in record_fields})
    with (output / "cluster_draws.npz").open("xb") as handle:
        np.savez_compressed(handle, cluster_indices=result["draws"], cluster_ids=np.asarray(result["cluster_ids"]))
    with (output / "report.json").open("x") as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    names = ("summary.csv", "records.csv", "cluster_draws.npz", "report.json")
    manifest = {
        "schema_version": 1, "status": "complete", "purpose": "captured cohort episode evaluation",
        "protocol": protocol, "seed": seed, "bootstrap_replicates": result["replicates"],
        "python": platform.python_version(), "numpy": np.__version__,
        "input_registry_manifest_sha256": registry_digest,
        "input_cohort_csv_sha256": frozen["source_csv_sha256"],
        "compatible_capture_settings": json.loads(compatibility),
        "source_sha256": {name: sha256(ROOT / name) for name in
                          ("cohort_evaluation.py", "cohort_registry.py", "event_evaluation.py")},
        "protocol_sha256": {"cohort_protocol.json": protocol_digest, "event_protocol.json": event_digest},
        "artifact_sha256": {name: sha256(output / name) for name in names},
        "limitations": LIMITATIONS,
    }
    with (output / "manifest.json").open("x") as handle:
        handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Pool captured sampled episodes with declared-cluster bootstrap uncertainty")
    parser.add_argument("registry", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261109)
    args = parser.parse_args()
    try:
        run_cohort(args.registry, args.output, args.seed)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(f"Wrote cohort capture to {args.output}; declared groups are not verified independence")


if __name__ == "__main__":
    main()
