import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import video_io
from video_io import FRAME_GEOMETRY, iter_video_frames


class ShortReadStream:
    def __init__(self, data: bytes, chunk_size: int) -> None:
        self.data = data
        self.chunk_size = chunk_size
        self.offset = 0

    def read(self, size: int) -> bytes:
        read_size = min(size, self.chunk_size, len(self.data) - self.offset)
        chunk = self.data[self.offset : self.offset + read_size]
        self.offset += read_size
        return chunk

    def close(self) -> None:
        pass


class FakeProcess:
    def __init__(self, output: bytes, chunk_size: int = 8192) -> None:
        self.stdout = ShortReadStream(output, chunk_size)
        self.returncode = 0

    def poll(self) -> int:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = -15

    def kill(self) -> None:
        self.returncode = -9


class VideoIOTests(unittest.TestCase):
    def _create_red_video(self, directory: str) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.fail("ffmpeg is required for the integration test")
        path = Path(directory) / "red.mkv"
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=16x16:r=2:d=2",
                "-c:v",
                "ffv1",
                "-pix_fmt",
                "yuv420p",
                str(path),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            shell=False,
        )
        return path

    def test_invalid_sample_fps(self) -> None:
        invalid_values = (
            math.nan,
            math.inf,
            -math.inf,
            0,
            -1,
            30.01,
            True,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.mkv"
            path.touch()
            for value in invalid_values:
                with self.subTest(sample_fps=value):
                    with self.assertRaises(ValueError):
                        list(iter_video_frames(path, sample_fps=value))

    def test_invalid_max_frames(self) -> None:
        invalid_values = (True, 0, -1, 100001, 1.5)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.mkv"
            path.touch()
            for value in invalid_values:
                with self.subTest(max_frames=value):
                    with self.assertRaises(ValueError):
                        list(iter_video_frames(path, max_frames=value))

    def test_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.mkv"
            with self.assertRaises(FileNotFoundError):
                list(iter_video_frames(path))

    def test_corrupted_input_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corrupted.mkv"
            path.write_bytes(b"not a video")
            with self.assertRaisesRegex(RuntimeError, "ffmpeg exited with status"):
                list(iter_video_frames(path))

    def test_short_reads_and_truncated_final_frame(self) -> None:
        frame_size = 640 * 360 * 3
        process = FakeProcess(bytes(frame_size + 7), chunk_size=8191)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.mkv"
            path.touch()
            with patch("video_io.subprocess.Popen", return_value=process) as popen:
                with self.assertRaisesRegex(RuntimeError, "truncated final frame"):
                    list(iter_video_frames(path, sample_fps=2))
            self.assertIsInstance(popen.call_args.args[0], list)
            self.assertFalse(popen.call_args.kwargs["shell"])
            self.assertEqual(process.stdout.offset, frame_size + 7)

    def test_empty_output_is_rejected(self) -> None:
        process = FakeProcess(b"")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.mkv"
            path.touch()
            with patch("video_io.subprocess.Popen", return_value=process):
                with self.assertRaisesRegex(RuntimeError, "produced no frames"):
                    list(iter_video_frames(path))

    def test_real_ffmpeg_resampling_and_frame_shape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._create_red_video(directory)
            frames = list(iter_video_frames(path, sample_fps=2))

        self.assertEqual(FRAME_GEOMETRY, "640x360 resampled RGB; aspect ratio normalized")
        self.assertEqual(len(frames), 4)
        for index, (sample_index, sample_time_s, frame) in enumerate(frames):
            self.assertEqual(sample_index, index)
            self.assertEqual(sample_time_s, index / 2)
            self.assertEqual(frame.shape, (360, 640, 3))
            self.assertEqual(frame.dtype, np.uint8)
            means = frame.mean(axis=(0, 1))
            self.assertGreater(means[0], 240)
            self.assertLess(means[1], 15)
            self.assertLess(means[2], 15)

    def test_closing_generator_reaps_ffmpeg_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._create_red_video(directory)
            original_popen = subprocess.Popen
            processes = []

            def capture_process(*args, **kwargs):
                process = original_popen(*args, **kwargs)
                processes.append(process)
                return process

            with patch("video_io.subprocess.Popen", side_effect=capture_process):
                frames = iter_video_frames(path, sample_fps=2)
                next(frames)
                frames.close()

        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())


if __name__ == "__main__":
    unittest.main()
