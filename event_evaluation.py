import argparse
import csv
import hashlib
import io
import json
import math
from numbers import Real
from pathlib import Path
import platform
import re

from detection import validate_labels
from video_io import FRAME_GEOMETRY


ROOT = Path(__file__).resolve().parent
PROTOCOL_PATH = ROOT / "event_protocol.json"
LABEL_FIELDS = ("recording_id", "split", "input_sha256", "sample_index", "sample_time_s", "fire")
LIMITATIONS = [
    "Sampled visible-fire episodes are not independent wildfire incidents or smoke detection.",
    "No independently labelled real footage or generalization is established by this software.",
    "Exposure is nominal sampled-bin time; an observed prefix may truncate the source recording.",
    "Episodes at prefix edges are censored; reported delays start at sampled visible-fire onset, not ignition.",
    "Delay quantiles include detected episodes only. Always inspect misses beside delay estimates.",
    "One recording supplies no confidence interval, target-acceptance verdict or field-performance guarantee.",
    "Annotator identity is self-reported; hashes and a blank packet do not verify independent annotation.",
    "Freeze thresholds on validation data; group related recordings, incidents, sites and dates outside this tool.",
]


def _validate_rate(sample_fps):
    if (isinstance(sample_fps, bool) or not isinstance(sample_fps, Real)
            or not math.isfinite(sample_fps) or not 0 < sample_fps <= 30):
        raise ValueError("sample_fps must be finite and in (0, 30]")
    return float(sample_fps)


def _runs(values, fps):
    episodes, start = [], None
    for index, positive in enumerate(values + [False]):
        if positive and start is None:
            start = index
        elif not positive and start is not None:
            episodes.append({"start_sample": start, "end_sample": index,
                             "start_time_s": start/fps, "end_time_s": index/fps})
            start = None
    return episodes


def episode_metrics(truth, alarms, sample_fps):
    fps = _validate_rate(sample_fps)
    truth, alarms = list(truth), list(alarms)
    if not truth or len(truth) != len(alarms):
        raise ValueError("Expected aligned nonempty truth and alarm sequences")
    if any(value not in (0, 1) for value in truth + alarms):
        raise ValueError("Truth and alarms must be binary")
    if not math.isfinite(len(truth)/fps):
        raise ValueError("Sampled exposure must be finite")
    fires, predictions = _runs(truth, fps), _runs(alarms, fps)
    for fire in fires:
        fire.update({"left_censored": fire["start_sample"] == 0,
                     "right_censored": fire["end_sample"] == len(truth),
                     "detected": False, "alarm_episode_index": None, "delay_s": None})
    fire_index, duplicates, false_alarms = 0, 0, 0
    delays = []
    for alarm_index, alarm in enumerate(predictions):
        onset = alarm["start_sample"]
        while fire_index < len(fires) and fires[fire_index]["end_sample"] <= onset:
            fire_index += 1
        inside = fire_index < len(fires) and fires[fire_index]["start_sample"] <= onset
        if not inside:
            alarm.update({"status": "false", "fire_episode_index": None})
            false_alarms += 1
        elif fires[fire_index]["detected"]:
            alarm.update({"status": "duplicate", "fire_episode_index": fire_index})
            duplicates += 1
        else:
            delay = (onset - fires[fire_index]["start_sample"]) / fps
            fires[fire_index].update({"detected": True, "alarm_episode_index": alarm_index,
                                      "delay_s": delay})
            alarm.update({"status": "matched", "fire_episode_index": fire_index})
            delays.append(delay)
    delays.sort()
    detected = len(delays)
    negative_exposure = truth.count(0) / fps
    return {
        "n_samples": len(truth), "sample_fps": fps, "sampled_exposure_s": len(truth)/fps,
        "nonfire_exposure_s": negative_exposure,
        "fire_episodes": len(fires), "alarm_episodes": len(predictions),
        "detected_fire_episodes": detected, "missed_fire_episodes": len(fires)-detected,
        "matched_alarm_episodes": detected, "duplicate_alarm_episodes": duplicates,
        "false_alarm_episodes": false_alarms, "unmatched_alarm_episodes": duplicates+false_alarms,
        "event_recall": detected / len(fires) if fires else None,
        "alarm_precision": detected / len(predictions) if predictions else None,
        "false_alarms_per_nonfire_hour": false_alarms*3600/negative_exposure if negative_exposure else None,
        "detected_delay_p50_s": delays[math.ceil(0.5*detected)-1] if detected else None,
        "detected_delay_p90_s": delays[math.ceil(0.9*detected)-1] if detected else None,
        "left_censored_fire_episodes": sum(fire["left_censored"] for fire in fires),
        "right_censored_fire_episodes": sum(fire["right_censored"] for fire in fires),
        "fire_episode_details": fires, "alarm_episode_details": predictions,
    }


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_rows(path, required, exact=False, expected_digest=None):
    content = path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError(f"Capture changed before parsing: {path.name}")
    with io.StringIO(content.decode("utf-8"), newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames
        if (header is None or len(header) != len(set(header))
                or not set(required).issubset(header)
                or (exact and set(header) != set(required))):
            raise ValueError(f"Invalid CSV header: {path.name}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Incomplete or overlong CSV row: {path.name}")
    return rows, digest


def _manifest(directory):
    content = (directory / "manifest.json").read_bytes()
    manifest = json.loads(content)
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "complete"):
        raise ValueError("A complete schema-1 capture is required")
    count = manifest.get("decoded_frames")
    if type(count) is not int or not 1 <= count <= 100000:
        raise ValueError("Capture sample count must be an integer in [1, 100000]")
    _validate_rate(manifest.get("sample_fps"))
    if (not isinstance(manifest.get("input_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["input_sha256"])
            or manifest.get("geometry") != FRAME_GEOMETRY
            or not isinstance(manifest.get("recording_id"), str)
            or not manifest["recording_id"]):
        raise ValueError("Invalid capture identity or geometry")
    return manifest, hashlib.sha256(content).hexdigest()


def _verify_artifacts(directory, manifest, expected):
    artifacts = manifest.get("artifact_sha256")
    if not isinstance(artifacts, dict) or set(artifacts) != expected:
        raise ValueError("Capture artifact inventory does not match this protocol")
    for name, digest in artifacts.items():
        if sha256(directory / name) != digest:
            raise ValueError(f"Capture artifact checksum mismatch: {name}")


def _indexed(rows, count, recording_id, fps):
    indexed = {}
    for row in rows:
        index, time_s = int(row["sample_index"]), float(row["sample_time_s"])
        if (index in indexed or not 0 <= index < count or row["recording_id"] != recording_id
                or not math.isfinite(time_s) or not math.isfinite(index/fps)
                or not math.isclose(time_s, index/fps, rel_tol=0, abs_tol=1e-9)):
            raise ValueError("Duplicate, out-of-range or mismatched sample identity/time")
        indexed[index] = row
    if set(indexed) != set(range(count)):
        raise ValueError("Samples must cover the decoded prefix exactly once")
    return indexed


def run_evaluation(predictions, packet, labels, output, annotator_id):
    predictions, packet, labels, output = map(Path, (predictions, packet, labels, output))
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output}")
    if not isinstance(annotator_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", annotator_id):
        raise ValueError("Supply an anonymous annotator ID using letters, digits, dot, dash or underscore")
    protocol = json.loads(PROTOCOL_PATH.read_text())
    if (protocol["schema_version"] != 1 or protocol["tolerance_samples"] != 0
            or tuple(protocol["label_fields"]) != LABEL_FIELDS):
        raise ValueError("Unsupported event protocol")
    annotation, annotation_digest = _manifest(packet)
    prediction, prediction_digest = _manifest(predictions)
    if (annotation.get("purpose") != "blind annotation packet"
            or annotation.get("split") != "test"
            or tuple(annotation.get("label_fields", ())) != LABEL_FIELDS):
        raise ValueError("Evaluation requires an original test-split annotation packet")
    for key in ("recording_id", "input_sha256", "geometry", "sample_fps", "decoded_frames"):
        if annotation[key] != prediction[key]:
            raise ValueError(f"Annotation and prediction captures disagree: {key}")
    source_maps = [capture.get("source_sha256") for capture in (annotation, prediction)]
    if any(not isinstance(value, dict) for value in source_maps):
        raise ValueError("Annotation and predictions must use the same captured decoder source")
    decoder_hashes = [value.get("video_io.py") for value in source_maps]
    if (any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in decoder_hashes) or decoder_hashes[0] != decoder_hashes[1]):
        raise ValueError("Annotation and predictions must use the same captured decoder source")
    count, fps = annotation["decoded_frames"], float(annotation["sample_fps"])
    expected_packet_artifacts = {"labels.csv"} | {
        f"sheet-{page:04d}.png" for page in range(1, math.ceil(count/12)+1)
    }
    _verify_artifacts(packet, annotation, expected_packet_artifacts)
    _verify_artifacts(predictions, prediction, {"predictions.csv"})
    recording_id = annotation["recording_id"]
    template_rows, template_digest = _csv_rows(
        packet / "labels.csv", LABEL_FIELDS, exact=True,
        expected_digest=annotation["artifact_sha256"]["labels.csv"],
    )
    template = _indexed(template_rows, count, recording_id, fps)
    completed_rows, labels_digest = _csv_rows(labels, LABEL_FIELDS, exact=True)
    completed = _indexed(completed_rows, count, recording_id, fps)
    for index in range(count):
        original, filled = template[index], completed[index]
        if (original["fire"] != "" or original["split"] != "test"
                or original["input_sha256"] != annotation["input_sha256"]):
            raise ValueError("Packet template must contain blank labels and consistent identity/split")
        for key in LABEL_FIELDS:
            if key != "fire" and original[key] != filled[key]:
                raise ValueError("Completed labels may change only fire cells, not packet metadata")
    truth = validate_labels(completed_rows, recording_id, count)
    prediction_rows, predictions_digest = _csv_rows(
        predictions / "predictions.csv", ("recording_id", "sample_index", "sample_time_s", "alarm"),
        expected_digest=prediction["artifact_sha256"]["predictions.csv"],
    )
    indexed_predictions = _indexed(prediction_rows, count, recording_id, fps)
    if any(row["alarm"] not in ("True", "False") for row in prediction_rows):
        raise ValueError("Captured alarms must be literal True or False")
    alarms = [indexed_predictions[i]["alarm"] == "True" for i in range(count)]
    report = {"schema_version": 1, "metrics": episode_metrics(truth, alarms, fps),
              "limitations": LIMITATIONS}
    output.mkdir(parents=True, exist_ok=False)
    with (output / "report.json").open("x") as handle:
        handle.write(json.dumps(report, indent=2, allow_nan=False) + "\n")
    manifest = {
        "schema_version": 1, "status": "complete", "protocol": protocol,
        "recording_id": recording_id, "split": "test", "input_sha256": annotation["input_sha256"],
        "sample_fps": fps, "decoded_frames": count, "annotator_id": annotator_id,
        "annotator_identity": "self-reported; independence is not verified by this tool",
        "python": platform.python_version(), "prediction_config": prediction.get("config"),
        "input_manifest_sha256": {"annotation": annotation_digest, "predictions": prediction_digest},
        "input_artifact_sha256": {"predictions.csv": predictions_digest,
                                 "packet_labels.csv": template_digest,
                                 "completed_labels.csv": labels_digest},
        "source_sha256": {name: sha256(ROOT / name) for name in
                          ("event_evaluation.py", "event_protocol.json", "detection.py")},
        "artifact_sha256": {"report.json": sha256(output / "report.json")},
    }
    with (output / "manifest.json").open("x") as handle:
        handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate sampled visible-fire episodes, not incident or field accuracy")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--annotator-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        run_evaluation(args.predictions, args.packet, args.labels, args.output, args.annotator_id)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(f"Wrote sampled-episode report to {args.output}; not independent or field validation")


if __name__ == "__main__":
    main()
