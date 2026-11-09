import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat

import numpy as np


@dataclass(frozen=True)
class CandidateConfig:
    min_fraction: float = 0.002
    consecutive_frames: int = 3
    red_min: int = 150
    green_min: int = 60
    red_green_gap: int = 20
    red_blue_gap: int = 60

    def __post_init__(self):
        if not math.isfinite(self.min_fraction) or not 0 < self.min_fraction <= 1:
            raise ValueError("Candidate fraction must be finite and in (0, 1]")
        if isinstance(self.consecutive_frames, bool) or not isinstance(self.consecutive_frames, int) or self.consecutive_frames < 1:
            raise ValueError("Consecutive frame count must be a positive integer")
        for value in (self.red_min, self.green_min, self.red_green_gap, self.red_blue_gap):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError("Color thresholds must be integers in [0, 255]")


def candidate_fraction(rgb, config=None):
    config = CandidateConfig() if config is None else config
    rgb = np.asarray(rgb)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size:
        raise ValueError("Expected a nonempty uint8 RGB image")
    red, green, blue = np.moveaxis(rgb.astype(np.int16), -1, 0)
    mask = ((red >= config.red_min) & (green >= config.green_min)
            & (red - green >= config.red_green_gap) & (green > blue)
            & (red - blue >= config.red_blue_gap))
    return float(mask.mean())


def predict_frames(frames, config):
    streak = 0
    for index, time_s, frame in frames:
        fraction = candidate_fraction(frame, config)
        candidate = fraction >= config.min_fraction
        streak = streak + 1 if candidate else 0
        yield {
            "sample_index": index, "sample_time_s": time_s,
            "candidate_pixel_fraction": fraction, "candidate": candidate,
            "alarm": streak >= config.consecutive_frames,
        }


def frame_metrics(truth, predicted):
    truth, predicted = np.asarray(truth), np.asarray(predicted)
    if truth.ndim != 1 or truth.shape != predicted.shape or not truth.size:
        raise ValueError("Expected aligned nonempty labels and predictions")
    if not np.isin(truth, [0, 1]).all() or not np.isin(predicted, [0, 1]).all():
        raise ValueError("Labels and predictions must be binary")
    truth, predicted = truth.astype(bool), predicted.astype(bool)
    tp = int(np.count_nonzero(truth & predicted))
    fn = int(np.count_nonzero(truth & ~predicted))
    fp = int(np.count_nonzero(~truth & predicted))
    tn = int(np.count_nonzero(~truth & ~predicted))
    return {
        "tp": tp, "fn": fn, "fp": fp, "tn": tn, "n_samples": len(truth),
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "false_positive_frame_share": fp / (fp + tn) if fp + tn else None,
        "scope": "sampled-frame metrics on one recording, not incident-level or independent samples",
    }


def validate_labels(rows, recording_id, sample_count):
    groups, selected = {}, {}
    for row in rows:
        group, split = row["recording_id"], row["split"]
        if not group or split not in ("train", "validation", "test"):
            raise ValueError("Each label needs a recording_id and train/validation/test split")
        if group in groups and groups[group] != split:
            raise ValueError(f"Recording leakage across splits: {group}")
        groups[group] = split
        if group == recording_id:
            index, label = int(row["sample_index"]), int(row["fire"])
            if index in selected or index < 0 or label not in (0, 1):
                raise ValueError("Duplicate/invalid sample index or nonbinary fire label")
            selected[index] = label
    if groups.get(recording_id) != "test":
        raise ValueError("Evaluation requires this recording to be assigned to test")
    if set(selected) != set(range(sample_count)):
        raise ValueError("Test labels must cover every decoded sample exactly once")
    return [selected[index] for index in range(sample_count)]


def _file_signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _file_snapshot(path, keep_bytes=False):
    if not path.is_file():
        raise FileNotFoundError(f"An existing regular input file is required: {path.name}")
    with path.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Input is not a regular file: {path.name}")
        signature = _file_signature(info)
        digest, chunks = hashlib.sha256(), []
        remaining = info.st_size
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError(f"Input changed while reading: {path.name}")
            digest.update(block)
            if keep_bytes:
                chunks.append(block)
            remaining -= len(block)
        if handle.read(1):
            raise ValueError(f"Input grew while reading: {path.name}")
        if (_file_signature(os.fstat(handle.fileno())) != signature
                or _file_signature(path.stat()) != signature):
            raise ValueError(f"Input changed while reading: {path.name}")
    return digest.hexdigest(), signature, b"".join(chunks) if keep_bytes else None


def main(argv=None):
    from video_io import FRAME_GEOMETRY, iter_video_frames

    parser = argparse.ArgumentParser(description="Exploratory RGB fire-color baseline, not a smoke or safety detector")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args(argv)
    if args.output.exists() or args.output.is_symlink():
        parser.error(f"Refusing existing output: {args.output}")
    if not args.recording_id.strip():
        parser.error("Supply a nonempty recording ID")
    if not math.isfinite(args.sample_fps) or not 0 < args.sample_fps <= 30:
        parser.error("sample_fps must be finite and in (0, 30]")
    if not 1 <= args.max_frames <= 100000:
        parser.error("max_frames must be an integer in [1, 100000]")
    try:
        video = args.video.resolve()
        video_snapshot = _file_snapshot(video)
        source_paths = {name: Path(__file__).with_name(name).resolve()
                        for name in ("detection.py", "video_io.py")}
        source_snapshots = {name: _file_snapshot(path) for name, path in source_paths.items()}
        labels_path = args.labels.resolve() if args.labels is not None else None
        labels_snapshot = _file_snapshot(labels_path, keep_bytes=True) if labels_path else None
        config = CandidateConfig()
        frames = iter_video_frames(video, args.sample_fps, args.max_frames)
        try:
            rows = list(predict_frames(frames, config))
        finally:
            frames.close()
        metrics = None
        if labels_snapshot is not None:
            try:
                with io.StringIO(labels_snapshot[2].decode("utf-8"), newline="") as handle:
                    labels = validate_labels(list(csv.DictReader(handle)), args.recording_id, len(rows))
            except (csv.Error, KeyError, TypeError) as error:
                raise ValueError("Malformed completed-label CSV") from error
            metrics = frame_metrics(labels, [row["alarm"] for row in rows])
        checks = [(video, video_snapshot)]
        checks.extend((source_paths[name], snapshot) for name, snapshot in source_snapshots.items())
        if labels_snapshot is not None:
            checks.append((labels_path, labels_snapshot))
        for path, original in checks:
            if _file_snapshot(path)[:2] != original[:2]:
                raise ValueError(f"Input changed during capture: {path.name}")
        args.output.mkdir(parents=True, exist_ok=False)
        with (args.output / "predictions.csv").open("x", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["recording_id"] + list(rows[0]))
            writer.writeheader()
            writer.writerows({"recording_id": args.recording_id, **row} for row in rows)
        manifest = {
            "schema_version": 1, "status": "complete",
            "baseline": "exploratory RGB color + consecutive-sample persistence",
            "config": asdict(config), "input_name": args.video.name, "input_sha256": video_snapshot[0],
            "recording_id": args.recording_id, "sample_fps": args.sample_fps,
            "max_frames": args.max_frames, "decoded_frames": len(rows), "geometry": FRAME_GEOMETRY,
            "numpy": np.__version__,
            "source_sha256": {name: snapshot[0] for name, snapshot in source_snapshots.items()},
            "labels_sha256": labels_snapshot[0] if labels_snapshot else None,
            "artifact_sha256": {
                "predictions.csv": hashlib.sha256((args.output / "predictions.csv").read_bytes()).hexdigest(),
            },
            "metrics": metrics,
            "limitations": [
                "Thresholds are declared engineering assumptions, not fitted or validated on drone data.",
                "Pixel fraction is not probability/confidence. Orange objects and sunlight can trigger it.",
                "Smoke, obscured flames, thermal imagery, tiny distant fires and camera motion are not modelled.",
                "Persistence delays alarms and does not track spatially consistent fire regions.",
                "No labels means no accuracy claim. One recording cannot establish generalisation.",
                "Sample times use the resampled video timeline, not source sensor capture timestamps.",
                "No autonomous dispatch, camera control, network service or flight integration.",
            ],
        }
        with (args.output / "manifest.json").open("x") as handle:
            handle.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
        print(f"Wrote {len(rows)} sampled-frame predictions to {args.output}; labels {'evaluated' if metrics else 'not supplied'}")
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
