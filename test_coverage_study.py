import contextlib
import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coverage_study import analyze, main


ROOT = Path(__file__).resolve().parent
CAPTURE_40 = ROOT / "research_results" / "2026-11-10-coverage-grid40"
CAPTURE_80 = ROOT / "research_results" / "2026-11-10-coverage-atlas-v1"
CAPTURE_160 = ROOT / "research_results" / "2026-11-10-coverage-grid160"
PUBLISHED = ROOT / "research_results" / "2026-11-10-coverage-analysis"
STUDY_CLI = ROOT / "coverage_study.py"
ANALYSIS_FILES = ("summary.csv", "resolution.csv", "analysis.json", "manifest.json")
HEADLINE_ROWS = (
    ("b9-w12-h000-reference-offnone", 60.3),
    ("b25-w12-h000-reference-offnone", 97.3),
    ("b9-w12-h000-combined-offnone", 33.8),
    ("b25-w12-h000-combined-offnone", 78.1),
)


class CoverageStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.output = self.root / "analysis"

    def _run(self, arguments: list[str]) -> tuple:
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = None
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = main(arguments)
            except SystemExit as error:
                code = 0 if error.code is None else error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def _arguments(self) -> list[str]:
        return [
            "--capture40", str(CAPTURE_40),
            "--capture80", str(CAPTURE_80),
            "--capture160", str(CAPTURE_160),
            "--output", str(self.output),
        ]

    def test_help_flag_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(STUDY_CLI), "--help"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())
        for flag in ("--capture40", "--capture80", "--capture160", "--output"):
            self.assertIn(flag, result.stdout)
        self.assertEqual(result.stderr, "")

    def test_analyze_reproduces_published_capture_bytes(self) -> None:
        analyze(CAPTURE_40, CAPTURE_80, CAPTURE_160, self.output)
        self.assertEqual(
            {path.name for path in self.output.iterdir()}, set(ANALYSIS_FILES))
        for name in ANALYSIS_FILES:
            self.assertEqual(
                (self.output / name).read_bytes(),
                (PUBLISHED / name).read_bytes(),
                f"generated {name} differs from the published frozen analysis")

    def test_manifest_hashes_generated_files(self) -> None:
        analyze(CAPTURE_40, CAPTURE_80, CAPTURE_160, self.output)
        manifest = json.loads((self.output / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["kind"], "coverage-analysis-receipt")
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(set(manifest["files"]), set(ANALYSIS_FILES) - {"manifest.json"})
        for name, expected in manifest["files"].items():
            self.assertEqual(
                hashlib.sha256((self.output / name).read_bytes()).hexdigest(), expected)
        for resolution, expected in manifest["capture_sha256"].items():
            self.assertRegex(expected, r"^[0-9a-f]{64}$")
            self.assertIn(int(resolution), (40, 80, 160))

    def test_analysis_json_counts_resolution_and_limits(self) -> None:
        analyze(CAPTURE_40, CAPTURE_80, CAPTURE_160, self.output)
        analysis = json.loads((self.output / "analysis.json").read_text(encoding="utf-8"))
        self.assertEqual(analysis["scenario_count"], 388)
        self.assertEqual(analysis["default_grid_n"], 80)
        self.assertEqual(len(analysis["networks"]), 2)
        self.assertEqual({row["n_bases"] for row in analysis["networks"]}, {9, 25})
        for network in analysis["networks"]:
            self.assertEqual(len(network["by_heading"]), 8)
        resolution = analysis["resolution"]
        self.assertEqual(resolution["comparison_grid_n"], 160)
        self.assertTrue(resolution["not_an_error_bound"])
        self.assertGreater(resolution["max_abs_g40_minus_g160_pp"],
                           resolution["max_abs_g80_minus_g160_pp"])
        self.assertTrue(analysis["limitations"])
        with (self.output / "summary.csv").open(newline="", encoding="utf-8") as handle:
            summary = list(csv.DictReader(handle))
        with (self.output / "resolution.csv").open(newline="", encoding="utf-8") as handle:
            resolutions = list(csv.DictReader(handle))
        self.assertEqual(len(summary), 388)
        self.assertEqual(len(resolutions), 388)
        self.assertEqual(
            sorted(row["case_id"] for row in summary),
            sorted(row["case_id"] for row in resolutions))

    def test_summary_stores_published_headline_values(self) -> None:
        analyze(CAPTURE_40, CAPTURE_80, CAPTURE_160, self.output)
        with (self.output / "summary.csv").open(newline="", encoding="utf-8") as handle:
            rows = {row["case_id"]: row for row in csv.DictReader(handle)}
        for case_id, expected in HEADLINE_ROWS:
            self.assertEqual(
                round(float(rows[case_id]["timely_area_percent"]), 1), expected,
                f"stored {case_id} no longer rounds to the published {expected}%")

    def test_cli_prints_resolution_summary(self) -> None:
        code, stdout, stderr = self._run(self._arguments())
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        payload = json.loads(stdout)
        self.assertEqual(payload["scenario_count"], 388)
        self.assertEqual(payload["resolution"]["comparison_grid_n"], 160)

    def test_tampered_capture_rejected(self) -> None:
        forged = self.root / "grid40"
        shutil.copytree(CAPTURE_40, forged)
        summary = forged / "summary.csv"
        data = bytearray(summary.read_bytes())
        data[-10] ^= 0x01
        summary.write_bytes(bytes(data))
        with self.assertRaises(ValueError):
            analyze(forged, CAPTURE_80, CAPTURE_160, self.output)
        self.assertFalse(self.output.exists())

    def test_reordered_scenarios_rejected(self) -> None:
        forged = self.root / "grid40"
        shutil.copytree(CAPTURE_40, forged)
        scenarios_path = forged / "scenarios.json"
        scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
        scenarios_path.write_text(
            json.dumps(list(reversed(scenarios)), indent=2) + "\n", encoding="utf-8")
        manifest_path = forged / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["scenarios.json"] = hashlib.sha256(
            scenarios_path.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            analyze(forged, CAPTURE_80, CAPTURE_160, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_replaced(self) -> None:
        self.output.mkdir()
        sentinel = b"existing output\xff\x00must stay byte identical\n"
        (self.output / "keep.bin").write_bytes(sentinel)
        with self.assertRaises(FileExistsError):
            analyze(CAPTURE_40, CAPTURE_80, CAPTURE_160, self.output)
        self.assertEqual((self.output / "keep.bin").read_bytes(), sentinel)


if __name__ == "__main__":
    unittest.main()
