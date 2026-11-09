import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
ANNOTATION_PACKET_CLI = REPO_ROOT / "annotation_packet.py"
DETECTION_CLI = REPO_ROOT / "detection.py"
VERIFY_CAPTURE_CLI = REPO_ROOT / "verify_capture.py"
RECORDING_ID = "rec-stream-01"
SENTINEL_BYTES = b"sentinel: do not overwrite\n"
RECEIPT_LIMITATIONS = [
    "Only listed file hashes are checked; not completeness, authenticity, labels, source-code identity, split independence or research performance."
]


class StreamWorkflowCliTests(unittest.TestCase):
    def _run_cli(self, *arguments, timeout=30) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout,
        )

    def _create_black_clip(self, directory: str) -> Path:
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
                "color=c=black:s=16x16:r=1:d=3",
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

    def _expected_receipt(self, capture: Path) -> dict:
        manifest_bytes = (capture / "manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
        return {
            "schema_version": 1,
            "status": "artifact_checksums_verified",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "artifact_sha256": {
                name: hashlib.sha256((capture / name).read_bytes()).hexdigest()
                for name in sorted(manifest["artifact_sha256"])
            },
            "limitations": RECEIPT_LIMITATIONS,
        }

    def test_real_packet_prediction_and_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = self._create_black_clip(directory)
            packet = root / "packet-out"
            detections = root / "detection-out"
            packet_result = self._run_cli(
                ANNOTATION_PACKET_CLI,
                video,
                "--recording-id",
                RECORDING_ID,
                "--split",
                "test",
                "--output",
                packet,
                "--sample-fps",
                "1",
                "--max-frames",
                "3",
            )
            self.assertEqual(packet_result.returncode, 0, packet_result.stderr)
            detection_result = self._run_cli(
                DETECTION_CLI,
                video,
                "--output",
                detections,
                "--recording-id",
                RECORDING_ID,
                "--sample-fps",
                "1",
                "--max-frames",
                "3",
            )
            self.assertEqual(
                detection_result.returncode, 0, detection_result.stderr
            )

            with (packet / "labels.csv").open(newline="") as handle:
                label_rows = list(csv.DictReader(handle))
            self.assertEqual(len(label_rows), 3)
            self.assertEqual({row["fire"] for row in label_rows}, {""})
            self.assertEqual(
                {row["recording_id"] for row in label_rows}, {RECORDING_ID}
            )
            with (detections / "predictions.csv").open(newline="") as handle:
                prediction_rows = list(csv.DictReader(handle))
            self.assertEqual(len(prediction_rows), 3)
            self.assertEqual(
                {row["recording_id"] for row in prediction_rows},
                {RECORDING_ID},
            )

            video_digest = hashlib.sha256(video.read_bytes()).hexdigest()
            packet_manifest = json.loads(
                (packet / "manifest.json").read_text()
            )
            self.assertEqual(packet_manifest["recording_id"], RECORDING_ID)
            self.assertEqual(packet_manifest["sample_fps"], 1)
            self.assertEqual(packet_manifest["max_frames"], 3)
            self.assertEqual(packet_manifest["decoded_frames"], 3)
            self.assertEqual(packet_manifest["input_sha256"], video_digest)
            detection_manifest = json.loads(
                (detections / "manifest.json").read_text()
            )
            self.assertEqual(detection_manifest["recording_id"], RECORDING_ID)
            self.assertEqual(detection_manifest["sample_fps"], 1)
            self.assertEqual(detection_manifest["max_frames"], 3)
            self.assertEqual(detection_manifest["decoded_frames"], 3)
            self.assertEqual(detection_manifest["input_sha256"], video_digest)
            self.assertIsNone(detection_manifest["metrics"])

            for capture in (packet, detections):
                with self.subTest(capture=capture.name):
                    result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        json.loads(result.stdout),
                        self._expected_receipt(capture),
                    )

    def test_annotation_fifo_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "fifo-video.mkv"
            os.mkfifo(fifo)
            output = root / "packet-out"
            result = self._run_cli(
                ANNOTATION_PACKET_CLI,
                fifo,
                "--recording-id",
                RECORDING_ID,
                "--split",
                "test",
                "--output",
                output,
                "--sample-fps",
                "1",
                "--max-frames",
                "3",
                timeout=5,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(output.exists())
            self.assertEqual({p.name for p in root.iterdir()}, {fifo.name})

    def test_annotation_existing_output_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "packet-out"
            output.write_bytes(SENTINEL_BYTES)
            missing = root / "missing-video.mkv"
            result = self._run_cli(
                ANNOTATION_PACKET_CLI,
                missing,
                "--recording-id",
                RECORDING_ID,
                "--split",
                "test",
                "--output",
                output,
                "--sample-fps",
                "1",
                "--max-frames",
                "3",
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertIn("Refusing existing output", result.stderr)
            self.assertNotIn(missing.name, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(output.read_bytes(), SENTINEL_BYTES)
            self.assertEqual({p.name for p in root.iterdir()}, {output.name})


if __name__ == "__main__":
    unittest.main()
