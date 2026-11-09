import argparse
import csv
from datetime import date
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re

from event_evaluation import LABEL_FIELDS, _csv_rows, _indexed, _manifest, _verify_artifacts, sha256


ROOT = Path(__file__).resolve().parent
COHORT_FIELDS = ("recording_id", "cluster_id", "site_id", "capture_date", "split",
                 "packet_dir", "event_report_dir")
METRICS = ("event_recall", "alarm_precision", "false_alarms_per_nonfire_hour",
           "detected_delay_p50_s", "detected_delay_p90_s")
ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def load_protocol():
    content = (ROOT / "cohort_protocol.json").read_bytes()
    protocol = json.loads(content)
    if (not isinstance(protocol, dict) or protocol.get("schema_version") != 1
            or tuple(protocol.get("cohort_fields", ())) != COHORT_FIELDS
            or tuple(protocol.get("metrics", ())) != METRICS
            or protocol.get("bootstrap_replicates") != 1000
            or protocol.get("default_seed") != 20261109
            or protocol.get("bootstrap_quantiles") != [0.025, 0.975]
            or protocol.get("minimum_informative_clusters_for_interval") != 2):
        raise ValueError("Unsupported cohort protocol")
    return protocol, hashlib.sha256(content).hexdigest()


def _cohort_rows(content):
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    if (reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames))
            or set(reader.fieldnames) != set(COHORT_FIELDS)):
        raise ValueError("Cohort CSV requires exactly the seven protocol columns")
    rows = list(reader)
    if not rows or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("Cohort rows must be complete and nonempty")
    return rows


def _packet_identity(directory, recording_id, split):
    manifest, digest = _manifest(directory)
    if (manifest.get("purpose") != "blind annotation packet" or manifest.get("split") != split
            or manifest["recording_id"] != recording_id
            or tuple(manifest.get("label_fields", ())) != LABEL_FIELDS):
        raise ValueError("Packet identity, split or label schema disagrees with cohort row")
    sources = manifest.get("source_sha256")
    if (not isinstance(sources, dict) or not isinstance(sources.get("video_io.py"), str)
            or re.fullmatch(r"[0-9a-f]{64}", sources["video_io.py"]) is None):
        raise ValueError("Packet requires its captured decoder fingerprint")
    count, fps = manifest["decoded_frames"], manifest["sample_fps"]
    expected = {"labels.csv"} | {
        f"sheet-{page:04d}.png" for page in range(1, math.ceil(count/12)+1)
    }
    _verify_artifacts(directory, manifest, expected)
    rows, _ = _csv_rows(directory / "labels.csv", LABEL_FIELDS, exact=True,
                        expected_digest=manifest["artifact_sha256"]["labels.csv"])
    _indexed(rows, count, recording_id, fps)
    if any(row["fire"] != "" or row["split"] != split
           or row["input_sha256"] != manifest["input_sha256"] for row in rows):
        raise ValueError("Registry requires the unchanged blank annotation packet")
    return manifest, digest


def _normalise(rows, source_directory, registry_directory):
    identities, videos, groups, normalized = set(), set(), {}, []
    for row in rows:
        for key in ("recording_id", "cluster_id", "site_id"):
            if ID_PATTERN.fullmatch(row[key]) is None:
                raise ValueError(f"Invalid anonymous ID: {key}")
        recording_id, split = row["recording_id"], row["split"]
        if split not in ("train", "validation", "test"):
            raise ValueError("Unknown cohort split")
        if date.fromisoformat(row["capture_date"]).isoformat() != row["capture_date"]:
            raise ValueError("capture_date must be canonical YYYY-MM-DD")
        if recording_id in identities:
            raise ValueError("Duplicate recording ID")
        identities.add(recording_id)
        if not row["packet_dir"].strip():
            raise ValueError("Every recording requires an annotation packet")
        if (split == "test" and not row["event_report_dir"].strip()
                or split != "test" and row["event_report_dir"] != ""):
            raise ValueError("Only test rows require planned event report paths")
        if Path(row["packet_dir"]).is_absolute() or (
                split == "test" and Path(row["event_report_dir"]).is_absolute()):
            raise ValueError("Cohort paths must be relative to the source CSV directory")
        packet_dir = (source_directory / row["packet_dir"]).resolve()
        packet, digest = _packet_identity(packet_dir, recording_id, split)
        video = packet["input_sha256"]
        if video in videos:
            raise ValueError("Duplicate source-video hash, even within one split")
        videos.add(video)
        for key in ("cluster_id", "site_id", "capture_date"):
            identity = (key, row[key])
            if identity in groups and groups[identity] != split:
                raise ValueError(f"Cross-split leakage: {key}={row[key]}")
            groups[identity] = split
        report_dir = (source_directory / row["event_report_dir"]).resolve() if split == "test" else None
        normalized.append({
            **row, "packet_dir": os.path.relpath(packet_dir, registry_directory),
            "event_report_dir": os.path.relpath(report_dir, registry_directory) if report_dir else "",
            "input_sha256": video, "packet_manifest_sha256": digest,
            "decoder_sha256": packet["source_sha256"]["video_io.py"],
            "sample_fps": packet["sample_fps"], "decoded_frames": packet["decoded_frames"],
        })
    if not any(row["split"] == "test" for row in normalized):
        raise ValueError("Cohort requires at least one planned test recording")
    return normalized


def freeze_cohort(csv_path, output):
    csv_path, output = Path(csv_path), Path(output)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output}")
    protocol, protocol_digest = load_protocol()
    content = csv_path.read_bytes()
    rows = _cohort_rows(content)
    output = output.resolve()
    normalized = _normalise(rows, csv_path.resolve().parent, output)
    digest = hashlib.sha256(content).hexdigest()
    manifest = {
        "schema_version": 1, "status": "complete", "purpose": "frozen cohort registry",
        "protocol": protocol, "source_csv_sha256": digest,
        "source_csv_parent": os.path.relpath(csv_path.resolve().parent, output),
        "records": normalized, "artifact_sha256": {"cohort.csv": digest},
        "source_sha256": {"cohort_registry.py": sha256(ROOT / "cohort_registry.py"),
                          "cohort_protocol.json": protocol_digest,
                          "event_evaluation.py": sha256(ROOT / "event_evaluation.py")},
        "limitations": [
            "Group/site/date declarations and annotation independence are not authenticated.",
            "Hashes detect identical files, not re-encodings or overlapping clips.",
            "No field-performance or detector-accuracy evidence is added by registering a cohort.",
        ],
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "cohort.csv").open("xb") as handle:
        handle.write(content)
    with (output / "manifest.json").open("x") as handle:
        handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return manifest


def load_registry(directory):
    directory = Path(directory).resolve()
    content = (directory / "manifest.json").read_bytes()
    manifest = json.loads(content)
    protocol, protocol_digest = load_protocol()
    if (not isinstance(manifest, dict) or manifest.get("schema_version") != 1
            or manifest.get("status") != "complete"
            or manifest.get("purpose") != "frozen cohort registry"
            or manifest.get("protocol") != protocol):
        raise ValueError("A compatible complete cohort registry is required")
    sources = manifest.get("source_sha256")
    if (not isinstance(sources, dict)
            or set(sources) != {"cohort_registry.py", "cohort_protocol.json", "event_evaluation.py"}
            or any(not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
                   for value in sources.values())
            or sources["cohort_protocol.json"] != protocol_digest):
        raise ValueError("Registry source/protocol provenance is missing or incompatible")
    artifacts = manifest.get("artifact_sha256")
    raw = (directory / "cohort.csv").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if artifacts != {"cohort.csv": digest} or manifest.get("source_csv_sha256") != digest:
        raise ValueError("Frozen cohort CSV checksum mismatch")
    base = (directory / manifest["source_csv_parent"]).resolve()
    rows = _normalise(_cohort_rows(raw), base, directory)
    if rows != manifest.get("records"):
        raise ValueError("Frozen registry metadata or packet manifests changed")
    return manifest, hashlib.sha256(content).hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Freeze a declared cohort and reject split leakage")
    parser.add_argument("cohort_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        freeze_cohort(args.cohort_csv, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"{parser.prog}: {exc}\n")
    print(f"Frozen cohort at {args.output}; declarations are not verified independence")


if __name__ == "__main__":
    main()
