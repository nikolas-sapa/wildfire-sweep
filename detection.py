import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

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


def main():
    from video_io import FRAME_GEOMETRY, iter_video_frames

    parser = argparse.ArgumentParser(description="Exploratory RGB fire-color baseline, not a smoke or safety detector")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=600)
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()
    config = CandidateConfig()
    frames = iter_video_frames(args.video, args.sample_fps, args.max_frames)
    rows = list(predict_frames(frames, config))
    metrics = None
    if args.labels is not None:
        with args.labels.open(newline="") as handle:
            labels = validate_labels(list(csv.DictReader(handle)), args.recording_id, len(rows))
        metrics = frame_metrics(labels, [r["alarm"] for r in rows])
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / "predictions.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["recording_id"] + list(rows[0]))
        writer.writeheader()
        writer.writerows({"recording_id": args.recording_id, **row} for row in rows)
    digest = hashlib.sha256()
    with args.video.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    manifest = {
        "schema_version": 1, "status": "complete",
        "baseline": "exploratory RGB color + consecutive-sample persistence",
        "config": asdict(config), "input_name": args.video.name, "input_sha256": digest.hexdigest(),
        "recording_id": args.recording_id, "sample_fps": args.sample_fps,
        "max_frames": args.max_frames, "decoded_frames": len(rows), "geometry": FRAME_GEOMETRY,
        "numpy": np.__version__,
        "source_sha256": {
            name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("detection.py", "video_io.py")
        },
        "labels_sha256": hashlib.sha256(args.labels.read_bytes()).hexdigest() if args.labels else None,
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
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    print(f"Wrote {len(rows)} sampled-frame predictions to {args.output}; labels {'evaluated' if metrics else 'not supplied'}")


if __name__ == "__main__":
    main()
