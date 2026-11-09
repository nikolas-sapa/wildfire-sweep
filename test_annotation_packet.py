import ast
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import annotation_packet
import matplotlib.pyplot as plt
import numpy as np
from annotation_packet import LABEL_FIELDS, create_packet

REPO = Path(__file__).resolve().parent
ALLOWED_IMPORTS = {
    "argparse",
    "collections",
    "contextlib",
    "csv",
    "hashlib",
    "io",
    "json",
    "math",
    "numbers",
    "os",
    "pathlib",
    "re",
    "stat",
    "sys",
    "typing",
    "matplotlib",
    "video_io",
}
FORBIDDEN_IMPORTS = {
    "detection",
    "event_evaluation",
    "simulation",
    "sweep",
    "suppression",
    "sensitivity",
    "factorial",
    "robustness",
    "research",
    "render_study",
    "render_factorial",
    "render_robustness",
}
MANIFEST_KEYS = {
    "schema_version",
    "status",
    "purpose",
    "recording_id",
    "split",
    "input_name",
    "input_sha256",
    "sample_fps",
    "max_frames",
    "decoded_frames",
    "geometry",
    "sample_limit_reached",
    "label_fields",
    "source_sha256",
    "artifact_sha256",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_frames(count: int, fail_at: int | None = None):
    closed = {"value": False}

    def generator(path, sample_fps, max_frames):
        try:
            for index in range(count):
                if fail_at is not None and index == fail_at:
                    raise RuntimeError("decoder failure")
                yield index, index / sample_fps, np.zeros((36, 64, 3), np.uint8)
        finally:
            closed["value"] = True

    return generator, closed


class AnnotationPacketTests(unittest.TestCase):
    def _create_black_video(self, directory: str) -> Path:
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            self.fail("ffmpeg is required for the integration test")
        path = Path(directory) / "black.mkv"
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=16x16:r=2:d=2",
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

    def test_blinded_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = self._create_black_video(directory)
            output = Path(directory) / "packet"
            manifest = create_packet(
                video, output, "rec-black-01", "test", sample_fps=2
            )

            self.assertEqual(plt.get_fignums(), [])
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"labels.csv", "sheet-0001.png", "manifest.json"},
            )

            with (output / "labels.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(rows[0], list(LABEL_FIELDS))
            self.assertEqual(len(rows), 5)
            video_sha256 = _sha256(video)
            for index, row in enumerate(rows[1:]):
                self.assertEqual(
                    row,
                    [
                        "rec-black-01",
                        "test",
                        video_sha256,
                        str(index),
                        str(index / 2),
                        "",
                    ],
                )

            sheet = output / "sheet-0001.png"
            self.assertTrue(sheet.read_bytes().startswith(b"\x89PNG"))

            self.assertEqual(
                json.loads((output / "manifest.json").read_text()), manifest
            )
            self.assertEqual(set(manifest), MANIFEST_KEYS)
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["purpose"], "blind annotation packet")
            self.assertEqual(manifest["recording_id"], "rec-black-01")
            self.assertEqual(manifest["split"], "test")
            self.assertEqual(manifest["input_name"], "black.mkv")
            self.assertEqual(manifest["input_sha256"], video_sha256)
            self.assertEqual(manifest["sample_fps"], 2.0)
            self.assertEqual(manifest["max_frames"], 600)
            self.assertEqual(manifest["decoded_frames"], 4)
            self.assertEqual(
                manifest["geometry"],
                "640x360 resampled RGB; aspect ratio normalized",
            )
            self.assertFalse(manifest["sample_limit_reached"])
            self.assertEqual(manifest["label_fields"], list(LABEL_FIELDS))
            self.assertEqual(
                manifest["source_sha256"],
                {
                    "annotation_packet.py": _sha256(REPO / "annotation_packet.py"),
                    "video_io.py": _sha256(REPO / "video_io.py"),
                },
            )
            self.assertEqual(
                manifest["artifact_sha256"],
                {
                    "labels.csv": _sha256(output / "labels.csv"),
                    "sheet-0001.png": _sha256(sheet),
                },
            )

    def test_packet_streaming_and_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            generator, closed = _fake_frames(13)
            with patch("annotation_packet.iter_video_frames", new=generator):
                manifest = create_packet(
                    video, output, "rec13", "validation", sample_fps=1, max_frames=13
                )

            self.assertTrue(closed["value"])
            self.assertEqual(plt.get_fignums(), [])
            self.assertEqual(
                sorted(path.name for path in output.glob("sheet-*.png")),
                ["sheet-0001.png", "sheet-0002.png"],
            )
            with (output / "labels.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.reader(handle))
            self.assertEqual(len(rows), 14)
            for index, row in enumerate(rows[1:]):
                self.assertEqual(int(row[3]), index)
                self.assertEqual(float(row[4]), index / 1)
                self.assertEqual(row[5], "")
            self.assertEqual(manifest["decoded_frames"], 13)
            self.assertTrue(manifest["sample_limit_reached"])
            self.assertEqual(
                set(manifest["artifact_sha256"]),
                {"labels.csv", "sheet-0001.png", "sheet-0002.png"},
            )

            manifest_bytes = (output / "manifest.json").read_bytes()
            with self.assertRaises(FileExistsError):
                create_packet(video, output, "rec13", "validation")
            self.assertEqual((output / "manifest.json").read_bytes(), manifest_bytes)

    def test_existing_output_preserves_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                create_packet(video, output, "rec13", "test")
            self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_decoder_and_figure_close_on_render_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            generator, closed = _fake_frames(13)
            with (
                patch("annotation_packet.iter_video_frames", new=generator),
                patch(
                    "matplotlib.figure.Figure.savefig",
                    side_effect=RuntimeError("render failure"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "render failure"):
                    create_packet(video, output, "rec13", "test")
            self.assertTrue(closed["value"])
            self.assertEqual(plt.get_fignums(), [])
            self.assertFalse((output / "manifest.json").exists())
            self.assertEqual(
                {path.name for path in output.iterdir()}, {"labels.csv"}
            )

    def test_decoder_closes_when_it_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            generator, closed = _fake_frames(13, fail_at=4)
            with patch("annotation_packet.iter_video_frames", new=generator):
                with self.assertRaisesRegex(RuntimeError, "decoder failure"):
                    create_packet(video, output, "rec13", "test")
            self.assertTrue(closed["value"])
            self.assertFalse((output / "manifest.json").exists())

    def test_empty_decode_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            generator, closed = _fake_frames(0)
            with patch("annotation_packet.iter_video_frames", new=generator):
                with self.assertRaisesRegex(RuntimeError, "No decoded samples"):
                    create_packet(video, output, "rec-01", "test")
            self.assertTrue(closed["value"])
            self.assertFalse((output / "manifest.json").exists())

    def test_source_change_during_decode_fails(self) -> None:
        closed = {"value": False}

        def mutating_generator(path, sample_fps, max_frames):
            try:
                yield 0, 0.0, np.zeros((36, 64, 3), np.uint8)
                Path(path).write_bytes(b"mutated source bytes")
                yield 1, 1.0, np.zeros((36, 64, 3), np.uint8)
            finally:
                closed["value"] = True

        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            with patch("annotation_packet.iter_video_frames", new=mutating_generator):
                with self.assertRaisesRegex(RuntimeError, "changed while decoding"):
                    create_packet(video, output, "rec-01", "test")
            self.assertTrue(closed["value"])
            self.assertFalse((output / "manifest.json").exists())

    def test_invalid_requests_fail_before_output(self) -> None:
        cases = [
            {"recording_id": value}
            for value in ("", "bad id", "-abc", "_abc", ".abc", "x" * 129, "a/b")
        ]
        cases += [{"split": value} for value in ("", "eval", "TEST", "holdout")]
        cases += [
            {"sample_fps": value}
            for value in (0, -1, 31, float("nan"), float("inf"), "2", True)
        ]
        cases += [
            {"max_frames": value}
            for value in (0, -1, 100001, 1.5, True, "5")
        ]
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            for position, overrides in enumerate(cases):
                output = Path(directory) / f"packet-{position}"
                request = {
                    "recording_id": "rec-01",
                    "split": "test",
                    "sample_fps": 1.0,
                    "max_frames": 600,
                    **overrides,
                }
                with self.subTest(**overrides):
                    with self.assertRaises(ValueError):
                        create_packet(video, output, **request)
                    self.assertFalse(output.exists())

    def test_missing_input_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "missing.mkv"
            output = Path(directory) / "packet"
            with self.assertRaises(FileNotFoundError):
                create_packet(video, output, "rec-01", "test")
            self.assertFalse(output.exists())

    def test_no_scientific_imports(self) -> None:
        tree = ast.parse((REPO / "annotation_packet.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertFalse(imported & FORBIDDEN_IMPORTS)
        self.assertLessEqual(imported, ALLOWED_IMPORTS)

    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        stderr = io.StringIO()
        with patch.object(sys, "argv", argv), redirect_stderr(stderr):
            try:
                result = annotation_packet.main()
            except SystemExit as exit_:
                result = exit_.code
        return result, stderr.getvalue()

    def test_cli_errors_exit_2_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            base_argv = [
                "annotation_packet.py",
                str(video),
                "--recording-id",
                "rec-01",
                "--split",
                "test",
                "--output",
                str(output),
            ]

            bad_id = base_argv.copy()
            bad_id[3] = "bad id"
            code, stderr = self._run_cli(bad_id)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", stderr)

            missing = base_argv.copy()
            missing[1] = str(Path(directory) / "missing.mkv")
            code, stderr = self._run_cli(missing)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", stderr)

            output.mkdir()
            code, stderr = self._run_cli(base_argv)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", stderr)

            bad_split = base_argv.copy()
            bad_split[5] = "eval"
            code, stderr = self._run_cli(bad_split)
            self.assertEqual(code, 2)
            self.assertNotIn("Traceback", stderr)

    def test_cli_success_returns_0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.bin"
            video.write_bytes(b"synthetic fixture")
            output = Path(directory) / "packet"
            argv = [
                "annotation_packet.py",
                str(video),
                "--recording-id",
                "rec-01",
                "--split",
                "test",
                "--output",
                str(output),
                "--sample-fps",
                "1",
                "--max-frames",
                "4",
            ]
            generator, closed = _fake_frames(4)
            stderr = io.StringIO()
            with (
                patch.object(sys, "argv", argv),
                patch("annotation_packet.iter_video_frames", new=generator),
                redirect_stderr(stderr),
            ):
                self.assertEqual(annotation_packet.main(), 0)
            self.assertTrue(closed["value"])
            self.assertTrue((output / "manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
