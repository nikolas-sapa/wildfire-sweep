import math
import os
import subprocess
import tempfile
from collections.abc import Iterator
from numbers import Integral, Real
from pathlib import Path
from typing import BinaryIO

import numpy as np

FRAME_GEOMETRY = "640x360 resampled RGB; aspect ratio normalized"
_FRAME_SIZE = 640 * 360 * 3
_STDERR_LIMIT = 4096


def _read_exact(stream: BinaryIO, size: int) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data) if data else None


def _stderr_message(stderr_file: BinaryIO) -> str:
    stderr_file.flush()
    stderr_file.seek(0, os.SEEK_END)
    end = stderr_file.tell()
    stderr_file.seek(max(0, end - _STDERR_LIMIT))
    return stderr_file.read(_STDERR_LIMIT).decode("utf-8", errors="replace").strip()


def _reap_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait()
    if process.stdout is not None:
        process.stdout.close()


def iter_video_frames(
    path: str | os.PathLike[str],
    sample_fps: float = 1.0,
    max_frames: int = 600,
) -> Iterator[tuple[int, float, np.ndarray]]:
    if (
        isinstance(sample_fps, bool)
        or not isinstance(sample_fps, Real)
        or not 0 < sample_fps <= 30
        or not math.isfinite(sample_fps)
    ):
        raise ValueError("sample_fps must be finite and in (0, 30]")
    if (
        isinstance(max_frames, bool)
        or not isinstance(max_frames, Integral)
        or not 0 < max_frames <= 100000
    ):
        raise ValueError("max_frames must be an integer in [1, 100000]")

    input_path = Path(path).resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"input video is not an existing file: {input_path}")

    sample_rate = float(sample_fps)
    frame_limit = int(max_frames)
    command = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(input_path),
        "-vf",
        f"fps=fps={sample_rate}:start_time=0,scale=640:360",
        "-frames:v",
        str(frame_limit),
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]

    with tempfile.TemporaryFile() as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            shell=False,
        )
        frame_count = 0
        truncated_frame = False
        try:
            if process.stdout is None:
                raise RuntimeError("ffmpeg stdout pipe was not created")
            while frame_count < frame_limit:
                frame_data = _read_exact(process.stdout, _FRAME_SIZE)
                if frame_data is None:
                    break
                if len(frame_data) != _FRAME_SIZE:
                    truncated_frame = True
                    break
                sample_index = frame_count
                frame_count += 1
                frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((360, 640, 3))
                yield sample_index, sample_index / sample_rate, frame

            return_code = process.wait()
            if return_code != 0:
                stderr = _stderr_message(stderr_file)
                raise RuntimeError(f"ffmpeg exited with status {return_code}: {stderr}")
            if truncated_frame:
                raise RuntimeError("ffmpeg produced a truncated final frame")
            if frame_count == 0:
                raise RuntimeError("ffmpeg produced no frames")
        finally:
            _reap_process(process)
