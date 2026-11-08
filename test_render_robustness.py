import ast
import csv
import tempfile
import unittest
from pathlib import Path

from render_robustness import read_robustness_summary, render_robustness

CONDITIONS = (
    "reference",
    "shorter_endurance",
    "slower_launch",
    "larger_reserve",
    "combined",
)
CONDITION_SETTINGS = {
    "reference": (46.0, 0.25, 60.0),
    "shorter_endurance": (34.5, 0.25, 60.0),
    "slower_launch": (46.0, 0.25, 180.0),
    "larger_reserve": (46.0, 0.35, 60.0),
    "combined": (34.5, 0.35, 180.0),
}
LAYOUTS = {9: 16.0, 25: 12.0}
WINDS = (8, 12)
FIELDNAMES = (
    "scenario",
    "condition",
    "nominal_spacing_km",
    "n_bases",
    "drones_per_base",
    "wind_east_mps",
    "airspeed_mps",
    "endurance_min",
    "reserve_fraction",
    "launch_latency_s",
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
)


def fixture_rows():
    rows = []
    for n_bases, spacing in LAYOUTS.items():
        for wind in WINDS:
            for condition in CONDITIONS:
                endurance, reserve, launch_latency = CONDITION_SETTINGS[condition]
                rows.append(
                    {
                        "scenario": f"b{n_bases}-w{wind}-{condition}",
                        "condition": condition,
                        "nominal_spacing_km": str(spacing),
                        "n_bases": str(n_bases),
                        "drones_per_base": "1",
                        "wind_east_mps": str(wind),
                        "airspeed_mps": "18",
                        "endurance_min": str(endurance),
                        "reserve_fraction": str(reserve),
                        "launch_latency_s": str(launch_latency),
                        "within_15min_share": "0.5",
                        "mc_95ci_low": "0.4",
                        "mc_95ci_high": "0.6",
                    }
                )
    return rows


class RobustnessRendererTests(unittest.TestCase):
    def _write_summary(self, directory: str, rows: list[dict[str, str]]) -> Path:
        path = Path(directory) / "summary.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_valid_20_row_fixture_renders_nonempty_png(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "robustness.png"
            render_robustness(summary, output)
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(output.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_duplicate_scenario_id_is_rejected(self) -> None:
        rows = fixture_rows()
        rows.append(rows[0].copy())
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "duplicate robustness scenario"):
                read_robustness_summary(summary)

    def test_missing_scenario_id_is_rejected(self) -> None:
        rows = fixture_rows()
        rows.pop(0)
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "grid mismatch"):
                read_robustness_summary(summary)

    def test_unknown_condition_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["condition"] = "unlisted_condition"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "unknown condition"):
                read_robustness_summary(summary)

    def test_metadata_must_match_protocol(self) -> None:
        rows = fixture_rows()
        rows[0]["reserve_fraction"] = "0.5"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "inconsistent reserve_fraction"):
                read_robustness_summary(summary)

    def test_share_and_interval_values_must_be_finite_and_in_range(self) -> None:
        for column in ("within_15min_share", "mc_95ci_low", "mc_95ci_high"):
            for value in ("nan", "inf", "-0.01", "1.01"):
                with self.subTest(column=column, value=value):
                    rows = fixture_rows()
                    rows[0][column] = value
                    with tempfile.TemporaryDirectory() as directory:
                        summary = self._write_summary(directory, rows)
                        with self.assertRaises(ValueError):
                            read_robustness_summary(summary)

    def test_reversed_interval_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["mc_95ci_low"] = "0.7"
        rows[0]["mc_95ci_high"] = "0.6"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "reversed confidence bounds"):
                read_robustness_summary(summary)

    def test_missing_metric_is_rejected(self) -> None:
        rows = fixture_rows()
        rows[0]["within_15min_share"] = ""
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "invalid within_15min_share"):
                read_robustness_summary(summary)

    def test_existing_output_is_refused_without_overwrite(self) -> None:
        original = b"existing artifact"
        with tempfile.TemporaryDirectory() as directory:
            summary = self._write_summary(directory, fixture_rows())
            output = Path(directory) / "robustness.png"
            output.write_bytes(original)
            with self.assertRaises(FileExistsError):
                render_robustness(summary, output)
            self.assertEqual(output.read_bytes(), original)

    def test_renderer_imports_no_scientific_modules(self) -> None:
        path = Path(__file__).with_name("render_robustness.py")
        tree = ast.parse(path.read_text())
        forbidden = {"research", "sweep", "suppression", "sensitivity", "robustness"}
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(forbidden & imported)


if __name__ == "__main__":
    unittest.main()
