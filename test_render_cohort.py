import ast
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import render_cohort
from render_cohort import read_cohort_summary, render

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "render_cohort.py"

FIELDNAMES = (
    "metric",
    "estimate",
    "ci_95_low",
    "ci_95_high",
    "unit",
    "n_records",
    "n_clusters",
    "informative_clusters",
    "valid_bootstrap_draws",
    "ci_status",
)
METRIC_SPECS = (
    ("event_recall", "fraction", "0.5", "0.4", "0.6"),
    ("alarm_precision", "fraction", "0.7", "0.55", "0.82"),
    ("false_alarms_per_nonfire_hour", "per_nonfire_hour", "0.25", "0.1", "0.4"),
    ("detected_delay_p50_s", "seconds", "12", "8", "20"),
    ("detected_delay_p90_s", "seconds", "30", "20", "45"),
)
COUNT_COLUMNS = (
    "n_records",
    "n_clusters",
    "informative_clusters",
    "valid_bootstrap_draws",
)


def fixture_rows():
    return [
        {
            "metric": metric,
            "estimate": estimate,
            "ci_95_low": low,
            "ci_95_high": high,
            "unit": unit,
            "n_records": "4",
            "n_clusters": "3",
            "informative_clusters": "2",
            "valid_bootstrap_draws": "1000",
            "ci_status": "cluster_bootstrap",
        }
        for metric, unit, estimate, low, high in METRIC_SPECS
    ]


def mark_undefined(row):
    row.update(
        estimate="",
        ci_95_low="",
        ci_95_high="",
        informative_clusters="0",
        valid_bootstrap_draws="0",
        ci_status="undefined",
    )


def mark_insufficient(row):
    row.update(
        estimate="0.6",
        ci_95_low="",
        ci_95_high="",
        informative_clusters="1",
        valid_bootstrap_draws="1000",
        ci_status="insufficient_clusters",
    )


class CohortRendererTests(unittest.TestCase):
    def _write_summary(self, directory: str, rows) -> Path:
        path = Path(directory) / "summary.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=FIELDNAMES, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _assert_rejected(self, rows, pattern: str = ".*") -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, pattern):
                read_cohort_summary(summary)

    def test_valid_fixture_renders_nonempty_png(self) -> None:
        rows = fixture_rows()
        self.assertEqual(len(rows), 5)
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            original_bytes = summary.read_bytes()
            output = Path(directory) / "cohort.png"
            render(summary, output)
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(summary.read_bytes(), original_bytes)

    def test_null_and_unavailable_statuses_render(self) -> None:
        rows = fixture_rows()
        mark_undefined(rows[0])
        mark_insufficient(rows[1])
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            records = read_cohort_summary(summary)
            self.assertIsNone(records["event_recall"]["estimate"])
            self.assertIsNone(records["event_recall"]["ci_95_low"])
            self.assertIsNotNone(records["alarm_precision"]["estimate"])
            self.assertIsNone(records["alarm_precision"]["ci_95_low"])
            output = Path(directory) / "cohort.png"
            render(summary, output)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_missing_metric_row_is_rejected(self) -> None:
        self._assert_rejected(fixture_rows()[:4], "missing metrics")

    def test_unknown_metric_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["metric"] = "detected_delay_p99_s"
        self._assert_rejected(rows, "unknown metric")

    def test_duplicate_metric_is_rejected(self) -> None:
        rows = fixture_rows()
        rows.append(dict(rows[0]))
        self._assert_rejected(rows, "duplicate cohort metric")

    def test_header_must_be_exact(self) -> None:
        body = [[row[column] for column in FIELDNAMES] for row in fixture_rows()]
        variants = (
            FIELDNAMES[:-1],
            FIELDNAMES + ("extra",),
            tuple(reversed(FIELDNAMES)),
            ("metric",) + FIELDNAMES,
        )
        for header in variants:
            with self.subTest(header=header):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "summary.csv"
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(header)
                        writer.writerows(body)
                    with self.assertRaises(ValueError):
                        read_cohort_summary(path)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.csv"
            path.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "no header"):
                read_cohort_summary(path)

    def test_extra_and_missing_row_values_are_rejected(self) -> None:
        body = [[row[column] for column in FIELDNAMES] for row in fixture_rows()]
        for row_values in (body[0] + ["extra"], body[0][:-1]):
            with self.subTest(values=len(row_values)):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "summary.csv"
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(FIELDNAMES)
                        writer.writerow(row_values)
                        writer.writerows(body[1:])
                    with self.assertRaises(ValueError):
                        read_cohort_summary(path)

    def test_wrong_unit_is_rejected(self) -> None:
        for unit in ("seconds", "per_nonfire_hour", "furlongs", ""):
            with self.subTest(unit=unit):
                rows = fixture_rows()
                rows[0]["unit"] = unit
                self._assert_rejected(rows, "wrong unit")

    def test_unknown_status_is_rejected(self) -> None:
        for status in ("bayesian", "Cluster_Bootstrap", ""):
            with self.subTest(status=status):
                rows = fixture_rows()
                rows[0]["ci_status"] = status
                self._assert_rejected(rows, "unknown ci_status")

    def test_count_ranges_are_enforced(self) -> None:
        cases = (
            ("n_records", "0"),
            ("n_records", "-1"),
            ("n_clusters", "0"),
            ("n_clusters", "5"),
            ("informative_clusters", "-1"),
            ("informative_clusters", "4"),
            ("valid_bootstrap_draws", "-1"),
            ("valid_bootstrap_draws", "1001"),
        )
        for column, value in cases:
            with self.subTest(column=column, value=value):
                rows = fixture_rows()
                for row in rows:
                    row[column] = value
                self._assert_rejected(rows, f"invalid {column}")

    def test_counts_must_be_plain_integers(self) -> None:
        for column in COUNT_COLUMNS:
            for value in ("1.5", "x", "", "True", "1e2"):
                with self.subTest(column=column, value=value):
                    rows = fixture_rows()
                    for row in rows:
                        row[column] = value
                    self._assert_rejected(rows, f"invalid {column}")

    def test_n_records_and_n_clusters_agree_across_rows(self) -> None:
        rows = fixture_rows()
        rows[0]["n_records"] = "5"
        self._assert_rejected(rows, "disagree on n_records")
        rows = fixture_rows()
        rows[2]["n_clusters"] = "2"
        self._assert_rejected(rows, "disagree on n_clusters")

    def test_value_ranges_are_enforced(self) -> None:
        cases = [
            (0, column, value)
            for column in ("estimate", "ci_95_low", "ci_95_high")
            for value in ("nan", "inf", "-0.01", "1.01")
        ]
        cases += [
            (2, "estimate", "-0.25"),
            (3, "estimate", "-1"),
            (3, "ci_95_low", "-0.5"),
        ]
        for row_index, column, value in cases:
            with self.subTest(column=column, value=value):
                rows = fixture_rows()
                rows[row_index][column] = value
                self._assert_rejected(rows)

    def test_reversed_interval_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["ci_95_low"] = "0.7"
        rows[0]["ci_95_high"] = "0.6"
        self._assert_rejected(rows, "reversed confidence bounds")

    def test_partial_interval_is_rejected(self) -> None:
        for blank in ("ci_95_low", "ci_95_high"):
            with self.subTest(blank=blank):
                rows = fixture_rows()
                rows[0][blank] = ""
                self._assert_rejected(rows, "partial interval")

    def test_point_estimate_outside_interval_is_allowed(self) -> None:
        rows = fixture_rows()
        rows[0]["estimate"] = "0.9"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            records = read_cohort_summary(summary)
            self.assertEqual(records["event_recall"]["estimate"], 0.9)
            output = Path(directory) / "cohort.png"
            render(summary, output)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_undefined_status_requires_null_fields(self) -> None:
        mutations = (
            {"estimate": "0.5"},
            {"ci_95_low": "0.4", "ci_95_high": "0.6"},
            {"informative_clusters": "1"},
            {"valid_bootstrap_draws": "1"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                rows = fixture_rows()
                mark_undefined(rows[0])
                rows[0].update(mutation)
                self._assert_rejected(rows, "inconsistent undefined fields")

    def test_insufficient_status_requires_point_without_interval(self) -> None:
        mutations = (
            {"estimate": ""},
            {"ci_95_low": "0.4", "ci_95_high": "0.6"},
            {"informative_clusters": "0"},
            {"informative_clusters": "2"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                rows = fixture_rows()
                mark_insufficient(rows[0])
                rows[0].update(mutation)
                self._assert_rejected(
                    rows, "inconsistent insufficient_clusters fields"
                )

    def test_bootstrap_status_requires_estimate_and_interval(self) -> None:
        mutations = (
            {"estimate": ""},
            {"ci_95_low": "", "ci_95_high": ""},
            {"informative_clusters": "1"},
            {"valid_bootstrap_draws": "0"},
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                rows = fixture_rows()
                rows[0].update(mutation)
                self._assert_rejected(
                    rows, "inconsistent cluster_bootstrap fields"
                )

    def test_existing_output_is_refused_without_overwrite(self) -> None:
        original = b"existing artifact"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "cohort.png"
            output.write_bytes(original)
            with self.assertRaises(FileExistsError):
                render(summary, output)
            self.assertEqual(output.read_bytes(), original)

    def test_dangling_symlink_output_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "cohort.png"
            output.symlink_to("missing-target.png")
            with self.assertRaises(FileExistsError):
                render(summary, output)
            self.assertTrue(output.is_symlink())

    def test_figure_is_closed_when_rendering_fails(self) -> None:
        from matplotlib.figure import Figure

        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "cohort.png"
            with mock.patch.object(
                Figure, "savefig", side_effect=RuntimeError("save failed")
            ):
                with self.assertRaises(RuntimeError):
                    render(summary, output)
            self.assertEqual(render_cohort.plt.get_fignums(), [])
            self.assertFalse(output.exists())

    def test_renderer_imports_no_scientific_modules(self) -> None:
        tree = ast.parse(SCRIPT.read_text())
        forbidden = {
            "cohort_evaluation",
            "cohort_registry",
            "event_evaluation",
            "detection",
            "research",
            "robustness",
            "factorial",
            "sweep",
            "suppression",
            "sensitivity",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(forbidden & imported)

    def _run_cli(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_cli_help_exits_zero(self) -> None:
        result = self._run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_renders_png_from_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "cohort.png"
            result = self._run_cli(str(summary), "--output", str(output))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_cli_failure_is_code_2_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "missing.csv"
            output = Path(directory) / "cohort.png"
            result = self._run_cli(str(summary), "--output", str(output))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertTrue(result.stderr.strip())
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_cli_existing_output_is_code_2(self) -> None:
        original = b"existing artifact"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "cohort.png"
            output.write_bytes(original)
            result = self._run_cli(str(summary), "--output", str(output))
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
