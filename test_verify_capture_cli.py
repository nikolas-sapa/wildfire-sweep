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
VERIFY_CAPTURE_CLI = REPO_ROOT / "verify_capture.py"
RECEIPT_LIMITATIONS = [
    "Only listed file hashes are checked; not completeness, authenticity, labels, source-code identity, split independence or research performance."
]
SENTINEL_BYTES = b"sentinel: do not overwrite\n"


class VerifyCaptureCliTests(unittest.TestCase):
    def _run_cli(self, *arguments) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )

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

    def _expected_text(self, capture: Path) -> str:
        return json.dumps(self._expected_receipt(capture), indent=2) + "\n"

    def _write_valid_capture(self, directory: Path) -> Path:
        directory.mkdir()
        payload = b"synthetic artifact bytes\n"
        (directory / "data.bin").write_bytes(payload)
        manifest = {
            "schema_version": 1,
            "status": "complete",
            "artifact_sha256": {
                "data.bin": hashlib.sha256(payload).hexdigest(),
            },
        }
        (directory / "manifest.json").write_text(json.dumps(manifest))
        return directory

    def _tree_digests(self, root: Path, pattern: str) -> dict:
        return {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.glob(pattern))
            if path.is_file() and not path.is_symlink()
        }

    def test_help_exits_zero(self) -> None:
        result = self._run_cli(VERIFY_CAPTURE_CLI, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage", result.stdout)
        self.assertIn("--output", result.stdout)

    def test_missing_positional_input_exits_two(self) -> None:
        result = self._run_cli(VERIFY_CAPTURE_CLI)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_valid_capture_stdout_matches_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = self._write_valid_capture(Path(directory) / "capture")
            result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout), self._expected_receipt(capture)
            )
            self.assertEqual(result.stdout, self._expected_text(capture))

    def test_output_writes_fresh_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = self._write_valid_capture(root / "capture")
            output = root / "receipt.json"
            result = self._run_cli(
                VERIFY_CAPTURE_CLI, capture, "--output", output
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                {p.name for p in root.iterdir()}, {"capture", "receipt.json"}
            )
            raw = output.read_bytes()
            self.assertTrue(raw.endswith(b"\n"))
            self.assertFalse(raw.endswith(b"\n\n"))
            self.assertEqual(
                raw.decode("utf-8"), self._expected_text(capture)
            )

    def test_output_precheck_before_missing_input(self) -> None:
        missing_input_name = "missing-capture-dir"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing_input = root / missing_input_name

            file_output = root / "receipt.json"
            file_output.write_bytes(SENTINEL_BYTES)
            dir_output = root / "receipt-dir"
            dir_output.mkdir()
            (dir_output / "sentinel.txt").write_bytes(SENTINEL_BYTES)
            dangling = root / "dangling-receipt.json"
            dangling_target = root / "absent-target.json"
            dangling.symlink_to(dangling_target)

            cases = {
                "existing file": file_output,
                "existing directory": dir_output,
                "dangling symlink": dangling,
            }
            for label, output in cases.items():
                with self.subTest(output=label):
                    result = self._run_cli(
                        VERIFY_CAPTURE_CLI, missing_input, "--output", output
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertIn("output already exists", result.stderr)
                    self.assertNotIn(missing_input_name, result.stderr)
                    self.assertEqual(result.stdout, "")
            self.assertEqual(file_output.read_bytes(), SENTINEL_BYTES)
            self.assertEqual({p.name for p in dir_output.iterdir()}, {"sentinel.txt"})
            self.assertEqual(
                (dir_output / "sentinel.txt").read_bytes(), SENTINEL_BYTES
            )
            self.assertTrue(dangling.is_symlink())
            self.assertEqual(os.readlink(dangling), str(dangling_target))

    def test_invalid_inputs_exit_two_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            malformed = root / "malformed"
            malformed.mkdir()
            (malformed / "manifest.json").write_bytes(b'{"schema_version": ')

            mismatched = self._write_valid_capture(root / "mismatched")
            artifact = mismatched / "data.bin"
            tampered = bytearray(artifact.read_bytes())
            tampered[0] ^= 0xFF
            artifact.write_bytes(bytes(tampered))

            linked = root / "linked"
            linked.mkdir()
            target_payload = b"symlink target bytes\n"
            (linked / "target.bin").write_bytes(target_payload)
            (linked / "data.bin").symlink_to("target.bin")
            (linked / "manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "status": "complete",
                "artifact_sha256": {
                    "data.bin": hashlib.sha256(target_payload).hexdigest(),
                },
            }))

            real_capture = self._write_valid_capture(root / "real-capture")
            manifest_link = root / "manifest-link"
            manifest_link.mkdir()
            (manifest_link / "data.bin").write_bytes(
                (real_capture / "data.bin").read_bytes()
            )
            (manifest_link / "manifest.json").symlink_to(
                real_capture / "manifest.json"
            )

            cases = {
                "missing directory": root / "missing-capture",
                "malformed manifest": malformed,
                "mismatched artifact": mismatched,
                "symlink artifact": linked,
                "symlink manifest": manifest_link,
            }
            for label, capture in cases.items():
                with self.subTest(case=label):
                    result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
                    self.assertEqual(result.returncode, 2)
                    self.assertNotIn("Traceback", result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_deep_json_manifest_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = self._write_valid_capture(root / "capture")
            digest = hashlib.sha256(
                (capture / "data.bin").read_bytes()
            ).hexdigest()
            (capture / "manifest.json").write_text(
                '{"schema_version": 1, "status": "complete", '
                + '"artifact_sha256": {"data.bin": "' + digest + '"}, '
                + '"extra": '
                + "[" * 100000
                + "]" * 100000
                + "}"
            )
            result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(result.stdout, "")
            output = root / "receipt.json"
            result = self._run_cli(
                VERIFY_CAPTURE_CLI, capture, "--output", output
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(output.exists())

    def test_verification_has_no_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = self._write_valid_capture(Path(directory) / "capture")
            source_before = self._tree_digests(REPO_ROOT, "*.py")
            capture_before = self._tree_digests(capture, "*")
            result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                source_before, self._tree_digests(REPO_ROOT, "*.py")
            )
            self.assertEqual(
                capture_before, self._tree_digests(capture, "*")
            )

    def test_valid_capture_and_tampered_copy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = self._write_valid_capture(root / "capture")
            result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout), self._expected_receipt(capture)
            )
            copied = root / "capture-copy"
            shutil.copytree(capture, copied)
            target = copied / "data.bin"
            tampered = bytearray(target.read_bytes())
            tampered[0] ^= 0xFF
            target.write_bytes(bytes(tampered))
            result = self._run_cli(VERIFY_CAPTURE_CLI, copied)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(result.stdout, "")
            result = self._run_cli(VERIFY_CAPTURE_CLI, capture)
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
