import ast
import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from render_factorial import read_factorial_summary, render

ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "render_factorial.py"

FACTOR_CELLS = {
    (0, 0, 0): ("reference", "reused"),
    (1, 0, 0): ("shorter_endurance", "reused"),
    (0, 1, 0): ("slower_launch", "reused"),
    (0, 0, 1): ("larger_reserve", "reused"),
    (1, 1, 0): ("endurance_launch", "simulated"),
    (1, 0, 1): ("endurance_reserve", "simulated"),
    (0, 1, 1): ("launch_reserve", "simulated"),
    (1, 1, 1): ("combined", "reused"),
}
CELL_ORDER = (
    (0, 0, 0),
    (1, 0, 0),
    (0, 1, 0),
    (0, 0, 1),
    (1, 1, 0),
    (1, 0, 1),
    (0, 1, 1),
    (1, 1, 1),
)
LAYOUTS = {9: 16.0, 25: 12.0}
WINDS = (8, 12)
FIELDNAMES = (
    "scenario",
    "condition",
    "provenance",
    "nominal_spacing_km",
    "n_bases",
    "drones_per_base",
    "wind_east_mps",
    "airspeed_mps",
    "endurance_min",
    "reserve_fraction",
    "launch_latency_s",
    "endurance_stress",
    "launch_stress",
    "reserve_stress",
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
)


def fixture_rows():
    rows = []
    for n_bases, spacing in LAYOUTS.items():
        for wind in WINDS:
            for bits in CELL_ORDER:
                endurance_stress, launch_stress, reserve_stress = bits
                condition, provenance = FACTOR_CELLS[bits]
                rows.append(
                    {
                        "scenario": (
                            f"b{n_bases}-w{wind}"
                            f"-e{endurance_stress}-l{launch_stress}-r{reserve_stress}"
                        ),
                        "condition": condition,
                        "provenance": provenance,
                        "nominal_spacing_km": str(spacing),
                        "n_bases": str(n_bases),
                        "drones_per_base": "1",
                        "wind_east_mps": str(wind),
                        "airspeed_mps": "18",
                        "endurance_min": "34.5" if endurance_stress else "46",
                        "reserve_fraction": "0.35" if reserve_stress else "0.25",
                        "launch_latency_s": "180" if launch_stress else "60",
                        "endurance_stress": str(endurance_stress),
                        "launch_stress": str(launch_stress),
                        "reserve_stress": str(reserve_stress),
                        "within_15min_share": "0.5",
                        "mc_95ci_low": "0.4",
                        "mc_95ci_high": "0.6",
                    }
                )
    return rows


class FactorialRendererTests(unittest.TestCase):
    def _write_summary(self, directory: str, rows: list[dict[str, str]]) -> Path:
        path = Path(directory) / "summary.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_valid_32_row_fixture_renders_nonempty_png(self) -> None:
        rows = fixture_rows()
        self.assertEqual(len(rows), 32)
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            output = Path(directory) / "factorial.png"
            render(summary, output)
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_duplicate_scenario_id_is_rejected(self) -> None:
        rows = fixture_rows()
        rows.append(rows[0].copy())
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "duplicate factorial scenario"):
                read_factorial_summary(summary)

    def test_missing_cell_is_rejected(self) -> None:
        rows = fixture_rows()
        rows.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "grid mismatch"):
                read_factorial_summary(summary)

    def test_unknown_condition_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["condition"] = "unlisted_condition"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "unknown condition"):
                read_factorial_summary(summary)

    def test_condition_must_match_stress_bits(self) -> None:
        rows = fixture_rows()
        rows[0]["condition"] = "combined"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "inconsistent condition"):
                read_factorial_summary(summary)

    def test_unknown_bit_value_is_rejected(self) -> None:
        for column in ("endurance_stress", "launch_stress", "reserve_stress"):
            for value in ("2", "-1", "x"):
                with self.subTest(column=column, value=value):
                    rows = fixture_rows()
                    rows[0][column] = value
                    with tempfile.TemporaryDirectory() as directory:
                        summary = self._write_summary(directory, rows)
                        with self.assertRaises(ValueError):
                            read_factorial_summary(summary)

    def test_unknown_provenance_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["provenance"] = "guessed"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "unknown provenance"):
                read_factorial_summary(summary)

    def test_provenance_must_match_stress_bits(self) -> None:
        rows = fixture_rows()
        for row in rows:
            if row["condition"] == "endurance_launch":
                row["provenance"] = "reused"
                break
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "inconsistent provenance"):
                read_factorial_summary(summary)

    def test_scenario_id_must_match_bits(self) -> None:
        rows = fixture_rows()
        rows[0]["scenario"] = "b9-w8-reference"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "inconsistent scenario ID"):
                read_factorial_summary(summary)

    def test_metadata_must_match_protocol(self) -> None:
        for column, value in (
            ("nominal_spacing_km", "12"),
            ("drones_per_base", "2"),
            ("airspeed_mps", "20"),
            ("endurance_min", "40"),
            ("reserve_fraction", "0.5"),
            ("launch_latency_s", "90"),
        ):
            with self.subTest(column=column):
                rows = fixture_rows()
                rows[0][column] = value
                with tempfile.TemporaryDirectory() as directory:
                    summary = self._write_summary(directory, rows)
                    with self.assertRaisesRegex(ValueError, f"inconsistent {column}"):
                        read_factorial_summary(summary)

    def test_share_and_interval_values_must_be_finite_and_in_range(self) -> None:
        for column in ("within_15min_share", "mc_95ci_low", "mc_95ci_high"):
            for value in ("nan", "inf", "-0.01", "1.01"):
                with self.subTest(column=column, value=value):
                    rows = fixture_rows()
                    rows[0][column] = value
                    with tempfile.TemporaryDirectory() as directory:
                        summary = self._write_summary(directory, rows)
                        with self.assertRaises(ValueError):
                            read_factorial_summary(summary)

    def test_reversed_interval_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["mc_95ci_low"] = "0.7"
        rows[0]["mc_95ci_high"] = "0.6"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "reversed confidence bounds"):
                read_factorial_summary(summary)

    def test_point_estimate_outside_interval_is_allowed(self) -> None:
        rows = fixture_rows()
        rows[0]["within_15min_share"] = "0.9"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            read_factorial_summary(summary)

    def test_missing_metric_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["within_15min_share"] = ""
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "invalid within_15min_share"):
                read_factorial_summary(summary)

    def test_existing_output_is_refused_without_overwrite(self) -> None:
        original = b"existing artifact"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "factorial.png"
            output.write_bytes(original)
            with self.assertRaises(FileExistsError):
                render(summary, output)
            self.assertEqual(output.read_bytes(), original)

    def test_cli_failure_is_code_2_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "missing.csv"
            output = Path(directory) / "factorial.png"
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(summary), "--output", str(output)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertTrue(result.stderr.strip())
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(output.exists())

    def test_renderer_imports_no_scientific_modules(self) -> None:
        path = Path(__file__).with_name("render_factorial.py")
        tree = ast.parse(path.read_text())
        forbidden = {
            "research",
            "sweep",
            "suppression",
            "sensitivity",
            "robustness",
            "factorial",
        }
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(forbidden & imported)


if __name__ == "__main__":
    unittest.main()
