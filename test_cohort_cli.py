import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
COHORT_REGISTRY_CLI = REPO_ROOT / "cohort_registry.py"
COHORT_EVALUATION_CLI = REPO_ROOT / "cohort_evaluation.py"
RENDER_COHORT_CLI = REPO_ROOT / "render_cohort.py"
NEW_CLIS = (COHORT_REGISTRY_CLI, COHORT_EVALUATION_CLI, RENDER_COHORT_CLI)
DECLARED_FLAGS = {
    COHORT_REGISTRY_CLI.name: ("--output",),
    COHORT_EVALUATION_CLI.name: ("--output", "--seed"),
    RENDER_COHORT_CLI.name: ("--output",),
}


class CohortCliTests(unittest.TestCase):
    def _run_cli(self, *arguments) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, *(str(argument) for argument in arguments)],
            capture_output=True,
            text=True,
            shell=False,
            timeout=30,
        )

    def test_new_cli_help_exits_zero(self) -> None:
        for cli in NEW_CLIS:
            with self.subTest(cli=cli.name):
                result = self._run_cli(cli, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage", result.stdout)
                for flag in DECLARED_FLAGS[cli.name]:
                    self.assertIn(flag, result.stdout)

    def test_new_cli_missing_arguments_exit_two(self) -> None:
        for cli in NEW_CLIS:
            with self.subTest(cli=cli.name):
                result = self._run_cli(cli)
                self.assertEqual(result.returncode, 2)
                self.assertIn("usage", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_registry_missing_csv_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "registry-out"
            result = self._run_cli(
                COHORT_REGISTRY_CLI,
                root / "missing-cohort.csv",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_evaluation_missing_registry_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evaluation-out"
            result = self._run_cli(
                COHORT_EVALUATION_CLI,
                root / "missing-registry",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_registry_existing_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "registry-out"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel_bytes = b"sentinel: do not overwrite\n"
            sentinel.write_bytes(sentinel_bytes)
            result = self._run_cli(
                COHORT_REGISTRY_CLI,
                root / "missing-cohort.csv",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual({p.name for p in output.iterdir()}, {"sentinel.txt"})
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

    def test_evaluation_existing_output_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evaluation-out"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel_bytes = b"sentinel: do not overwrite\n"
            sentinel.write_bytes(sentinel_bytes)
            result = self._run_cli(
                COHORT_EVALUATION_CLI,
                root / "missing-registry",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual({p.name for p in output.iterdir()}, {"sentinel.txt"})
            self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

    def test_render_cohort_missing_csv_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "cohort.png"
            result = self._run_cli(
                RENDER_COHORT_CLI,
                root / "missing-summary.csv",
                "--output",
                output,
            )
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
