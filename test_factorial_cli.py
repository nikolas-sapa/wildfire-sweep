from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "factorial.py"


class FactorialCliTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, arguments)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_help_lists_output_and_source(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--output", result.stdout)
        self.assertIn("--source", result.stdout)

    def test_no_arguments_reports_usage(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("usage:", result.stderr.lower())
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_source_fails_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            source = Path(directory) / "missing-source"
            result = self.run_cli("--output", output, "--source", source)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertTrue(result.stderr.strip())
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_existing_output_preserves_sentinel(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            output.mkdir()
            sentinel = output / "sentinel.bin"
            original = b"existing capture\x00must remain unchanged\n"
            sentinel.write_bytes(original)
            result = self.run_cli("--output", output)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertTrue(result.stderr.strip())
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(sentinel.read_bytes(), original)
            self.assertEqual(list(output.iterdir()), [sentinel])


if __name__ == "__main__":
    unittest.main()
