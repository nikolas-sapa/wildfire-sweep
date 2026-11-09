import csv
import hashlib
import io
import inspect
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import detection
import video_io


REPO_ROOT = Path(__file__).resolve().parent


def _make_clip(path, rate, duration):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise AssertionError("ffmpeg is required for the capture tests")
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s=16x16:r={rate}:d={duration}",
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
        timeout=60,
    )
    return path


def _labels_csv(path, recording_id, count):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["recording_id", "split", "sample_index", "fire"])
        for index in range(count):
            writer.writerow([recording_id, "test", index, 0])
    return path


def _run_main(argv):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        try:
            return detection.main([str(argument) for argument in argv])
        except SystemExit as error:
            return error.code


class DetectionCaptureTests(unittest.TestCase):
    def test_stable_capture_records_consumed_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = _make_clip(root / "black3.mkv", 3, 1)
            labels = _labels_csv(root / "labels.csv", "rec-cap-1", 3)
            output = root / "out"
            code = _run_main(
                [
                    video,
                    "--output",
                    output,
                    "--recording-id",
                    "rec-cap-1",
                    "--sample-fps",
                    "3",
                    "--labels",
                    labels,
                ]
            )
            self.assertEqual(code, 0)
            predictions = output / "predictions.csv"
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["decoded_frames"], 3)
            self.assertEqual(
                manifest["input_sha256"], hashlib.sha256(video.read_bytes()).hexdigest()
            )
            self.assertEqual(
                manifest["labels_sha256"], hashlib.sha256(labels.read_bytes()).hexdigest()
            )
            self.assertEqual(
                manifest["artifact_sha256"]["predictions.csv"],
                hashlib.sha256(predictions.read_bytes()).hexdigest(),
            )
            self.assertEqual(manifest["metrics"]["n_samples"], 3)
            with predictions.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 3)
            self.assertEqual({row["recording_id"] for row in rows}, {"rec-cap-1"})

    def test_input_replaced_after_decode_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = _make_clip(root / "black3.mkv", 3, 1)
            replacement = _make_clip(root / "black4.mkv", 2, 2)
            replacement_bytes = replacement.read_bytes()
            output = root / "out"
            real_iter = video_io.iter_video_frames

            def swapped(path, *args, **kwargs):
                real = real_iter(path, *args, **kwargs)
                try:
                    yield from real
                finally:
                    real.close()
                video.write_bytes(replacement_bytes)

            with mock.patch.object(video_io, "iter_video_frames", swapped):
                code = _run_main(
                    [
                        video,
                        "--output",
                        output,
                        "--recording-id",
                        "rec-cap-2",
                        "--sample-fps",
                        "3",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
            self.assertEqual(video.read_bytes(), replacement_bytes)

    def test_labels_mutated_after_validation_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = _make_clip(root / "black3.mkv", 3, 1)
            labels = _labels_csv(root / "labels.csv", "rec-cap-3", 3)
            output = root / "out"
            real_validate = detection.validate_labels

            def mutating_validate(rows, recording_id, sample_count):
                result = real_validate(rows, recording_id, sample_count)
                labels.write_bytes(labels.read_bytes() + b"# mutated after validation\n")
                return result

            with mock.patch.object(detection, "validate_labels", mutating_validate):
                code = _run_main(
                    [
                        video,
                        "--output",
                        output,
                        "--recording-id",
                        "rec-cap-3",
                        "--sample-fps",
                        "3",
                        "--labels",
                        labels,
                    ]
                )
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())

    def test_copied_source_mutated_during_capture_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = _make_clip(root / "black3.mkv", 3, 1)
            copies = {}
            for name in ("detection.py", "video_io.py"):
                copies[name] = root / name
                copies[name].write_bytes((REPO_ROOT / name).read_bytes())
            repo_detection_bytes = (REPO_ROOT / "detection.py").read_bytes()
            output = root / "out"
            real_iter = video_io.iter_video_frames

            def swapped(path, *args, **kwargs):
                real = real_iter(path, *args, **kwargs)
                try:
                    yield from real
                finally:
                    real.close()
                with copies["detection.py"].open("ab") as handle:
                    handle.write(b"# mutated during capture\n")

            with mock.patch.object(video_io, "iter_video_frames", swapped):
                with mock.patch.object(detection, "__file__", str(copies["detection.py"])):
                    code = _run_main(
                        [
                            video,
                            "--output",
                            output,
                            "--recording-id",
                            "rec-cap-4",
                            "--sample-fps",
                            "3",
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertFalse(output.exists())
            self.assertEqual((REPO_ROOT / "detection.py").read_bytes(), repo_detection_bytes)
            self.assertNotEqual(copies["detection.py"].read_bytes(), repo_detection_bytes)

    def test_existing_output_refused_before_input_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel_bytes = b"sentinel: do not overwrite\n"
            sentinel.write_bytes(sentinel_bytes)

            def fail_snapshot(*args, **kwargs):
                raise AssertionError("_file_snapshot must not run before output check")

            with mock.patch.object(detection, "_file_snapshot", fail_snapshot):
                code = _run_main(
                    [
                        root / "missing.mkv",
                        "--output",
                        output,
                        "--recording-id",
                        "rec-cap-5",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)
            self.assertEqual({p.name for p in output.iterdir()}, {"sentinel.txt"})

    def test_invalid_sampling_limits_rejected_before_snapshot(self):
        cases = (
            ["--sample-fps", "nan"],
            ["--sample-fps", "0"],
            ["--sample-fps", "31"],
            ["--max-frames", "0"],
            ["--max-frames", "100001"],
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    output = root / "out"

                    def fail_snapshot(*args, **kwargs):
                        raise AssertionError("_file_snapshot must not run for invalid limits")

                    with mock.patch.object(detection, "_file_snapshot", fail_snapshot):
                        code = _run_main(
                            [
                                root / "missing.mkv",
                                "--output",
                                output,
                                "--recording-id",
                                "rec-cap-6",
                                *arguments,
                            ]
                        )
                    self.assertEqual(code, 2)
                    self.assertFalse(output.exists())

    def test_consumer_failure_closes_frame_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = _make_clip(root / "black3.mkv", 3, 1)
            output = root / "out"
            state = {"closed": False, "real": None}
            real_iter = video_io.iter_video_frames

            def tracked(path, *args, **kwargs):
                real = real_iter(path, *args, **kwargs)
                state["real"] = real
                try:
                    yield from real
                finally:
                    state["closed"] = True
                    real.close()

            def failing_predict(frames, config):
                for index, time_s, frame in frames:
                    yield {
                        "sample_index": index,
                        "sample_time_s": time_s,
                        "candidate_pixel_fraction": 0.0,
                        "candidate": False,
                        "alarm": False,
                    }
                    raise ValueError("injected consumer failure")

            with mock.patch.object(video_io, "iter_video_frames", tracked):
                with mock.patch.object(detection, "predict_frames", failing_predict):
                    code = _run_main(
                        [
                            video,
                            "--output",
                            output,
                            "--recording-id",
                            "rec-cap-7",
                            "--sample-fps",
                            "3",
                        ]
                    )
            self.assertEqual(code, 2)
            self.assertTrue(state["closed"])
            self.assertEqual(inspect.getgeneratorstate(state["real"]), "GEN_CLOSED")
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
