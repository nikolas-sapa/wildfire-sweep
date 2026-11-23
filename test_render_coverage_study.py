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

import matplotlib.pyplot as plt

from render_coverage_study import (
    HEADINGS,
    LAYOUTS,
    PROFILE_ORDER,
    create_direction_figure,
    create_stress_figure,
    main,
    matches_reference_row,
    panel_value,
    read_capture,
    select_one,
)


ROOT = Path(__file__).resolve().parent
CAPTURE = ROOT / "research_results" / "2026-11-10-coverage-analysis"
RENDER_CLI = ROOT / "render_coverage_study.py"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _stored_rows(capture: Path) -> dict:
    with (capture / "summary.csv").open(newline="", encoding="utf-8") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def _expected_column(rows: dict, layout: int, heading: int, column: str) -> list:
    return [
        float(rows[f"b{layout}-w12-h{heading:03d}-{profile}-offnone"][column])
        for profile in PROFILE_ORDER
    ]


class RenderCoverageStudyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.output = self.root / "figures"

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

    def _copy_capture(self) -> Path:
        copied = self.root / "capture"
        shutil.copytree(CAPTURE, copied)
        return copied

    def _rewrite_summary(self, capture: Path, rows: list) -> None:
        summary_path = capture / "summary.csv"
        with summary_path.open(newline="", encoding="utf-8") as handle:
            fieldnames = csv.DictReader(handle).fieldnames
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        data = buffer.getvalue().encode("utf-8")
        summary_path.write_bytes(data)
        manifest_path = capture / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["summary.csv"] = hashlib.sha256(data).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    def test_help_flag_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RENDER_CLI), "--help"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())
        self.assertIn("--capture", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_render_writes_both_pngs_deterministically(self) -> None:
        code, stdout, stderr = self._run(
            ["--capture", str(CAPTURE), "--output", str(self.output)])
        self.assertEqual((code, stdout, stderr), (0, "", ""))
        self.assertEqual(
            sorted(path.name for path in self.output.iterdir()),
            ["direction.png", "stress.png"])
        first = {name: (self.output / name).read_bytes()
                 for name in ("direction.png", "stress.png")}
        for name, data in first.items():
            self.assertTrue(data.startswith(PNG_MAGIC), f"{name} is not a PNG")
            self.assertGreater(len(data), 10000)
        second = self.root / "figures-again"
        code, _, _ = self._run(
            ["--capture", str(CAPTURE), "--output", str(second)])
        self.assertEqual(code, 0)
        for name, data in first.items():
            self.assertEqual((second / name).read_bytes(), data)

    def test_direction_figure_plots_stored_values(self) -> None:
        _, rows = read_capture(CAPTURE)
        stored = _stored_rows(CAPTURE)
        figure = create_direction_figure(rows, "deadbeef")
        self.addCleanup(plt.close, figure)
        axis = figure.axes[0]
        self.assertEqual(len(axis.lines), len(LAYOUTS))
        for line, layout in zip(axis.lines, LAYOUTS):
            expected = [
                float(stored[f"b{layout}-w12-h{heading:03d}-reference-offnone"]
                          ["timely_area_percent"])
                for heading in HEADINGS
            ]
            self.assertEqual(list(line.get_xdata()), list(HEADINGS))
            self.assertEqual(list(line.get_ydata()), expected)
        self.assertEqual(axis.get_ylim(), (0, 100))
        self.assertTrue(any(
            "Not field-validated" in text.get_text() and "deadbeef" in text.get_text()
            for text in figure.texts))

    def test_stress_figure_plots_stored_values(self) -> None:
        _, rows = read_capture(CAPTURE)
        stored = _stored_rows(CAPTURE)
        figure = create_stress_figure(rows, "deadbeef")
        self.addCleanup(plt.close, figure)
        area_axis, loss_axis = figure.axes
        for layout_index, layout in enumerate(LAYOUTS):
            area = [patch.get_height() for patch in
                    area_axis.patches[layout_index * len(PROFILE_ORDER):
                                      (layout_index + 1) * len(PROFILE_ORDER)]]
            loss = [patch.get_height() for patch in
                    loss_axis.patches[layout_index * len(PROFILE_ORDER):
                                      (layout_index + 1) * len(PROFILE_ORDER)]]
            self.assertEqual(
                area, _expected_column(stored, layout, 0, "timely_area_percent"))
            self.assertEqual(
                loss, _expected_column(stored, layout, 0, "timely_area_loss_pp"))
        self.assertEqual(area_axis.get_ylim(), (0, 100))
        self.assertTrue(any(
            "Not field-validated" in text.get_text() for text in figure.texts))

    def test_read_capture_rejects_manifest_mutations(self) -> None:
        capture = self._copy_capture()
        manifest_path = capture / "manifest.json"
        original = json.loads(manifest_path.read_text(encoding="utf-8"))
        for label, mutate in (
            ("kind", lambda m: m.update(kind="other")),
            ("files", lambda m: m["files"].pop("summary.csv")),
            ("capture_sha256", lambda m: m["capture_sha256"].pop("80")),
        ):
            manifest = json.loads(json.dumps(original))
            mutate(manifest)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(ValueError, msg=label):
                read_capture(capture)
        manifest_path.write_text(json.dumps(original), encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"]["summary.csv"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256 does not match"):
            read_capture(capture)

    def test_duplicate_reference_row_rejected(self) -> None:
        capture = self._copy_capture()
        with (capture / "summary.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        target = next(
            row for row in rows
            if row["case_id"] == "b9-w12-h000-reference-offnone")
        self._rewrite_summary(capture, rows + [dict(target)])
        code, stdout, stderr = self._run(
            ["--capture", str(capture), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("expected exactly one", stderr)
        self.assertFalse(self.output.exists())

    def test_out_of_range_stored_value_rejected(self) -> None:
        capture = self._copy_capture()
        with (capture / "summary.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if row["case_id"] == "b9-w12-h000-reference-offnone":
                row["timely_area_percent"] = "150"
        self._rewrite_summary(capture, rows)
        code, stdout, stderr = self._run(
            ["--capture", str(capture), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn("outside the panel range", stderr)
        self.assertFalse(self.output.exists())

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
        self.output.mkdir()
        sentinel = b"existing output\xff\x00must stay byte identical\n"
        (self.output / "keep.bin").write_bytes(sentinel)
        code, stdout, stderr = self._run(
            ["--capture", str(CAPTURE), "--output", str(self.output)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertNotIn("Traceback", stderr)
        self.assertEqual((self.output / "keep.bin").read_bytes(), sentinel)

    def test_matches_reference_row(self) -> None:
        row = {
            "n_bases": "9", "wind_speed_mps": "12.0", "heading_deg": "0",
            "profile": "reference", "offline_bases": "[]",
        }
        self.assertTrue(matches_reference_row(row, 9, 0, "reference"))
        self.assertFalse(matches_reference_row(row, 25, 0, "reference"))
        self.assertFalse(matches_reference_row(row, 9, 45, "reference"))
        self.assertFalse(matches_reference_row(row, 9, 0, "combined"))
        self.assertFalse(matches_reference_row({**row, "offline_bases": "[0]"}, 9, 0, "reference"))
        with self.assertRaises(ValueError):
            matches_reference_row({**row, "n_bases": "nine"}, 9, 0, "reference")
        with self.assertRaises(ValueError):
            matches_reference_row({**row, "offline_bases": "{}"}, 9, 0, "reference")

    def test_panel_value_bounds(self) -> None:
        self.assertEqual(panel_value({"c": "50.5"}, "c", 100), 50.5)
        self.assertEqual(panel_value({"c": "0"}, "c", 100), 0.0)
        with self.assertRaises(ValueError):
            panel_value({"c": "100.5"}, "c", 100)
        with self.assertRaises(ValueError):
            panel_value({"c": "-0.5"}, "c", 100)
        with self.assertRaises(ValueError):
            panel_value({"c": "nan"}, "c", 100)
        with self.assertRaises(ValueError):
            panel_value({"c": "abc"}, "c", 100)

    def test_select_one_requires_exactly_one(self) -> None:
        base = {
            "n_bases": "9", "wind_speed_mps": "12.0", "heading_deg": "0",
            "profile": "reference", "offline_bases": "[]",
        }
        self.assertIs(select_one([base], 9, 0, "reference"), base)
        with self.assertRaisesRegex(ValueError, "found 0"):
            select_one([], 9, 0, "reference")
        with self.assertRaisesRegex(ValueError, "found 2"):
            select_one([base, dict(base)], 9, 0, "reference")


if __name__ == "__main__":
    unittest.main()
