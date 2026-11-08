import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
DETECTION_CLI = REPO_ROOT / "detection.py"
ANNOTATION_PACKET_CLI = REPO_ROOT / "annotation_packet.py"
EVENT_EVALUATION_CLI = REPO_ROOT / "event_evaluation.py"
NEW_CLIS = (ANNOTATION_PACKET_CLI, EVENT_EVALUATION_CLI)


class VideoWorkflowCliTests(unittest.TestCase):
    def _run_cli(self, *arguments) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )

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
            timeout=60,
        )
        return path

    def test_detection_cli_captures_black_fixture_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = self._create_black_video(directory)
            output = Path(directory) / "detection-out"
            result = self._run_cli(
                DETECTION_CLI,
                video,
                "--output",
                output,
                "--recording-id",
                "rec-cli-01",
                "--sample-fps",
                "2",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            predictions = output / "predictions.csv"
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(manifest["recording_id"], "rec-cli-01")
            self.assertEqual(manifest["sample_fps"], 2)
            self.assertEqual(manifest["decoded_frames"], 4)
            self.assertEqual(
                manifest["input_sha256"],
                hashlib.sha256(video.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["artifact_sha256"]["predictions.csv"],
                hashlib.sha256(predictions.read_bytes()).hexdigest(),
            )
            self.assertIsNone(manifest["metrics"])
            with predictions.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), manifest["decoded_frames"])
            self.assertEqual({row["recording_id"] for row in rows}, {"rec-cli-01"})

    def test_new_cli_help_exits_zero(self) -> None:
        for cli in NEW_CLIS:
            with self.subTest(cli=cli.name):
                result = self._run_cli(cli, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout)

    def test_new_cli_missing_arguments_exit_two(self) -> None:
        for cli in NEW_CLIS:
            with self.subTest(cli=cli.name):
                result = self._run_cli(cli)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_event_evaluation_missing_inputs_fail_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evaluation-out"
            result = self._run_cli(
                EVENT_EVALUATION_CLI,
                "--predictions",
                root / "missing-predictions",
                "--packet",
                root / "missing-packet",
                "--labels",
                root / "missing-labels.csv",
                "--annotator-id",
                "reviewer-01",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_event_evaluation_existing_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evaluation-out"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel_bytes = b"sentinel: do not overwrite\n"
            sentinel.write_bytes(sentinel_bytes)
            result = self._run_cli(
                EVENT_EVALUATION_CLI,
                "--predictions",
                root / "missing-predictions",
                "--packet",
                root / "missing-packet",
                "--labels",
                root / "missing-labels.csv",
                "--annotator-id",
                "reviewer-01",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual({p.name for p in output.iterdir()}, {"sentinel.txt"})
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)


if __name__ == "__main__":
    unittest.main()
