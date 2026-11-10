import contextlib
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from coverage_test_fixture import create_fixture
from render_coverage import main


RENDER_CLI = Path(__file__).resolve().parent / "render_coverage.py"
COUNT_FIELDS = (
    "unreachable_cells", "late_cells", "timely_cells",
    "weather_closed_cells", "total_cells",
)
FRACTION_FIELDS = ("timely_area_fraction", "reachable_area_fraction")
INPUT_FIELDS = (
    "n_bases", "wind_speed_mps", "heading_deg", "airspeed_mps",
    "endurance_min", "reserve_fraction", "launch_latency_s",
)


def _stored_capture(capture: Path) -> tuple[dict, list, dict, str]:
    manifest_bytes = (capture / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    scenarios = json.loads((capture / "scenarios.json").read_text(encoding="utf-8"))
    with (capture / "summary.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for name in COUNT_FIELDS:
            row[name] = int(row[name])
        for name in FRACTION_FIELDS:
            row[name] = float(row[name])
    capture_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest, scenarios, {row["case_id"]: row for row in rows}, capture_sha256


def _forms(value) -> set:
    forms = {str(value)}
    if isinstance(value, float):
        forms.add(f"{value:g}")
    return forms


def _markdown_table_rows(text: str, heading: str) -> tuple[list[str], list[dict[str, str]]]:
    lines = text.splitlines()
    start = lines.index(heading) + 1
    while start < len(lines) and not lines[start].startswith("|"):
        start += 1
    if start + 1 >= len(lines):
        raise AssertionError(f"table after {heading!r} is missing")
    columns = [value.strip() for value in lines[start].strip("|").split("|")]
    rows = []
    for line in lines[start + 2:]:
        if not line.startswith("|"):
            break
        values = [value.strip() for value in line.strip("|").split("|")]
        if len(values) != len(columns):
            raise AssertionError(f"table after {heading!r} has a malformed row")
        rows.append(dict(zip(columns, values)))
    return columns, rows


class RenderCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.capture = create_fixture(self.root / "capture")
        self.output = self.root / "rendered.md"

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

    def _assert_stored(self, text: str, value) -> None:
        self.assertTrue(
            any(form in text for form in _forms(value)),
            f"stored value {value!r} missing from rendered output")

    def test_help_flag_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RENDER_CLI), "--help"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())
        self.assertIn("--capture", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_render_writes_stored_inputs_counts_provenance_limits(self) -> None:
        code, _, _ = self._run(
            ["--capture", str(self.capture), "--output", str(self.output)])
        self.assertEqual(code, 0)
        text = self.output.read_text(encoding="utf-8")
        manifest, scenarios, summaries, capture_sha256 = _stored_capture(self.capture)
        self._assert_stored(text, manifest["study_id"])
        self._assert_stored(text, capture_sha256)
        self._assert_stored(text, manifest["grid_n"])
        self._assert_stored(text, manifest["domain_side_km"])
        self._assert_stored(text, manifest["timely_threshold_s"])
        for limitation in manifest["limitations"]:
            self._assert_stored(text, limitation)
        for outcome in manifest["outcome_codes"]:
            self._assert_stored(text, outcome)
        for case in scenarios:
            self._assert_stored(text, case["case_id"])
            self._assert_stored(text, case["profile"])
            for name in INPUT_FIELDS:
                self._assert_stored(text, case[name])
        columns, rows = _markdown_table_rows(text, "### Stored cell outcomes")
        self.assertEqual(len(rows), len(scenarios))
        self.assertEqual(
            [row["case_id"].replace("\\_", "_") for row in rows],
            [case["case_id"] for case in scenarios],
        )
        self.assertEqual(
            len({row["case_id"].replace("\\_", "_") for row in rows}),
            len(rows),
        )
        stored_columns = ("case_id",) + COUNT_FIELDS + FRACTION_FIELDS
        self.assertTrue(set(stored_columns) <= set(columns))
        expected_rows = []
        for case in scenarios:
            summary = summaries[case["case_id"]]
            expected = {"case_id": case["case_id"]}
            for name in COUNT_FIELDS:
                expected[name] = str(summary[name])
            for name in FRACTION_FIELDS:
                expected[name] = repr(summary[name])
            expected_rows.append({name: expected[name] for name in stored_columns})
        actual_rows = [
            {
                name: row[name].replace("\\_", "_") if name == "case_id" else row[name]
                for name in stored_columns
            }
            for row in rows
        ]
        self.assertEqual(actual_rows, expected_rows)

    def test_missing_capture_exits_two_without_output(self) -> None:
        code, stdout, stderr = self._run(
            ["--capture", str(self.root / "absent"), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.strip())
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(self.output.exists())

    def test_invalid_capture_exits_two_without_output(self) -> None:
        invalid = self.root / "not-a-capture"
        invalid.mkdir()
        code, stdout, stderr = self._run(
            ["--capture", str(invalid), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.strip())
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(self.output.exists())

    def test_existing_output_is_never_replaced(self) -> None:
        sentinel = b"existing output\xff\x00must stay byte identical\n"
        self.output.write_bytes(sentinel)
        code, stdout, stderr = self._run(
            ["--capture", str(self.capture), "--output", str(self.output)])
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(self.output.read_bytes(), sentinel)

    def test_missing_output_parent_fails_cleanly(self) -> None:
        target = self.root / "no-such-dir" / "rendered.md"
        code, stdout, stderr = self._run(
            ["--capture", str(self.capture), "--output", str(target)])
        self.assertNotEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertTrue(stderr.strip())
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(target.parent.exists())
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
