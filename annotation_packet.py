import argparse
import contextlib
import csv
import hashlib
import io
import json
import math
import os
import re
import stat
from numbers import Integral, Real
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from video_io import FRAME_GEOMETRY, iter_video_frames

LABEL_FIELDS = (
    "recording_id",
    "split",
    "input_sha256",
    "sample_index",
    "sample_time_s",
    "fire",
)
SPLITS = ("train", "validation", "test")
RECORDING_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHEET_COLUMNS = 4
SHEET_ROWS = 3
FRAMES_PER_SHEET = SHEET_COLUMNS * SHEET_ROWS
SOURCE_FILES = ("annotation_packet.py", "video_io.py")
PURPOSE = "blind annotation packet"


def _sha256_path(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"An existing regular input file is required: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Input is not a regular file: {path.name}")
        signature = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        remaining = info.st_size
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError(f"Input changed while reading: {path.name}")
            digest.update(block)
            remaining -= len(block)
        if handle.read(1):
            raise ValueError(f"Input grew while reading: {path.name}")
        for after in (os.fstat(handle.fileno()), path.stat()):
            actual = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            if actual != signature:
                raise ValueError(f"Input changed while reading: {path.name}")
    return digest.hexdigest()


def _write_exclusive(path: Path, data: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def _validate_request(
    recording_id: object,
    split: object,
    sample_fps: object,
    max_frames: object,
) -> None:
    if not isinstance(recording_id, str) or RECORDING_ID_PATTERN.fullmatch(recording_id) is None:
        raise ValueError(
            "recording_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
        )
    if split not in SPLITS:
        raise ValueError(f"split must be one of {SPLITS}")
    if (
        isinstance(sample_fps, bool)
        or not isinstance(sample_fps, Real)
        or not math.isfinite(sample_fps)
        or not 0 < sample_fps <= 30
    ):
        raise ValueError("sample_fps must be finite and in (0, 30]")
    if (
        isinstance(max_frames, bool)
        or not isinstance(max_frames, Integral)
        or not 0 < max_frames <= 100000
    ):
        raise ValueError("max_frames must be an integer in [1, 100000]")


def _write_sheet(
    sheet_path: Path,
    page_frames: list,
    recording_id: str,
    split: str,
    page_number: int,
) -> None:
    figure, axes = plt.subplots(
        SHEET_ROWS, SHEET_COLUMNS, figsize=(12, 7)
    )
    try:
        figure.suptitle(
            f"{recording_id} | {split} | sheet {page_number:04d}",
            fontsize=13,
            fontweight="semibold",
            color="#111827",
        )
        for position, axis in enumerate(axes.flat):
            if position >= len(page_frames):
                axis.axis("off")
                continue
            index, time_s, frame = page_frames[position]
            axis.imshow(frame)
            axis.set_xticks([])
            axis.set_yticks([])
            for spine in axis.spines.values():
                spine.set_color("#d1d5db")
            axis.set_title(
                f"index {index} | t = {time_s:g} s",
                loc="left",
                fontsize=9,
                color="#475569",
            )
        figure.tight_layout(rect=(0.02, 0.02, 0.98, 0.93))
        image = io.BytesIO()
        figure.savefig(image, format="png", dpi=150, facecolor="white")
        _write_exclusive(sheet_path, image.getvalue())
    finally:
        plt.close(figure)


def create_packet(
    video,
    output,
    recording_id,
    split,
    sample_fps=1.0,
    max_frames=600,
):
    _validate_request(recording_id, split, sample_fps, max_frames)
    video_path = Path(video)
    output_path = Path(output)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"Refusing existing output: {output_path}")
    input_sha256 = _sha256_path(video_path)
    output_path.mkdir(parents=True, exist_ok=False)

    sample_rate = float(sample_fps)
    frame_limit = int(max_frames)
    labels_path = output_path / "labels.csv"
    sheet_paths = []
    page_frames = []
    page_number = 0
    decoded_frames = 0

    with labels_path.open("x", newline="", encoding="utf-8") as labels_file:
        writer = csv.writer(labels_file)
        writer.writerow(LABEL_FIELDS)
        frames = iter_video_frames(video_path, sample_rate, frame_limit)
        with contextlib.closing(frames):
            for index, _time_s, frame in frames:
                page_frames.append((index, index / sample_rate, frame))
                writer.writerow(
                    [
                        recording_id,
                        split,
                        input_sha256,
                        index,
                        index / sample_rate,
                        "",
                    ]
                )
                decoded_frames += 1
                if len(page_frames) == FRAMES_PER_SHEET:
                    page_number += 1
                    sheet_path = output_path / f"sheet-{page_number:04d}.png"
                    _write_sheet(
                        sheet_path, page_frames, recording_id, split, page_number
                    )
                    sheet_paths.append(sheet_path)
                    page_frames = []
            if page_frames:
                page_number += 1
                sheet_path = output_path / f"sheet-{page_number:04d}.png"
                _write_sheet(
                    sheet_path, page_frames, recording_id, split, page_number
                )
                sheet_paths.append(sheet_path)

    if decoded_frames == 0:
        raise RuntimeError("No decoded samples")
    if _sha256_path(video_path) != input_sha256:
        raise RuntimeError("input video changed while decoding")

    artifact_sha256 = {"labels.csv": _sha256_path(labels_path)}
    for sheet_path in sheet_paths:
        artifact_sha256[sheet_path.name] = _sha256_path(sheet_path)

    manifest = {
        "schema_version": 1,
        "status": "complete",
        "purpose": PURPOSE,
        "recording_id": recording_id,
        "split": split,
        "input_name": video_path.name,
        "input_sha256": input_sha256,
        "sample_fps": sample_rate,
        "max_frames": frame_limit,
        "decoded_frames": decoded_frames,
        "geometry": FRAME_GEOMETRY,
        "sample_limit_reached": decoded_frames == frame_limit,
        "label_fields": list(LABEL_FIELDS),
        "source_sha256": {
            name: _sha256_path(Path(__file__).with_name(name))
            for name in SOURCE_FILES
        },
        "artifact_sha256": artifact_sha256,
    }
    with (output_path / "manifest.json").open("x", encoding="utf-8") as manifest_file:
        manifest_file.write(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a blind annotation packet from a sampled video. "
            "The packet is a labelling aid, not a scientific results plot."
        )
    )
    parser.add_argument("video", type=Path)
    parser.add_argument("--recording-id", required=True)
    parser.add_argument("--split", required=True, choices=SPLITS)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=600)
    arguments = parser.parse_args()
    try:
        create_packet(
            arguments.video,
            arguments.output,
            arguments.recording_id,
            arguments.split,
            sample_fps=arguments.sample_fps,
            max_frames=arguments.max_frames,
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
