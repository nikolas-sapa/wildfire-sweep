import csv
import tempfile
import unittest
from pathlib import Path

from render_study import read_physical_summary, validate_output_path

PUBLISHED_SUMMARY = (
    Path(__file__).parent / "research_results" / "2026-11-07-anchor" / "summary.csv"
)
SHARE_COLUMNS = (
    "within_15min_share",
    "mc_95ci_low",
    "mc_95ci_high",
    "rejected_share",
)


class RenderStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with PUBLISHED_SUMMARY.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise RuntimeError("published summary has no header")
            cls.fieldnames = reader.fieldnames
            cls.rows = list(reader)

    def _copy_summary(self, directory: str, rows: list[dict[str, str]]) -> Path:
        path = Path(directory) / "summary.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def _rows_copy(self) -> list[dict[str, str]]:
        return [row.copy() for row in self.rows]

    def _physical_row_index(self, rows: list[dict[str, str]]) -> int:
        return next(index for index, row in enumerate(rows) if row["mode"] == "physical")

    def test_valid_published_summary_has_32_physical_groups(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, self._rows_copy())
            rows = read_physical_summary(path)
        self.assertEqual(len(rows), 32)

    def test_missing_physical_group_is_rejected(self) -> None:
        rows = self._rows_copy()
        rows.pop(self._physical_row_index(rows))
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "missing="):
                read_physical_summary(path)

    def test_duplicate_physical_group_is_rejected(self) -> None:
        rows = self._rows_copy()
        rows.append(rows[self._physical_row_index(rows)].copy())
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "duplicate physical scenario group"):
                read_physical_summary(path)

    def test_extra_physical_wind_is_rejected(self) -> None:
        rows = self._rows_copy()
        extra = rows[self._physical_row_index(rows)].copy()
        extra["wind_east_mps"] = "16"
        rows.append(extra)
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "extra="):
                read_physical_summary(path)

    def test_share_bounds_and_finiteness_are_enforced(self) -> None:
        for column in SHARE_COLUMNS:
            for value in ("-0.01", "1.01", "nan"):
                with self.subTest(column=column, value=value):
                    rows = self._rows_copy()
                    rows[self._physical_row_index(rows)][column] = value
                    with tempfile.TemporaryDirectory() as directory:
                        path = self._copy_summary(directory, rows)
                        with self.assertRaises(ValueError):
                            read_physical_summary(path)

    def test_reversed_confidence_bounds_are_rejected(self) -> None:
        rows = self._rows_copy()
        physical = rows[self._physical_row_index(rows)]
        physical["mc_95ci_low"] = "0.9"
        physical["mc_95ci_high"] = "0.8"
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "reversed confidence bounds"):
                read_physical_summary(path)

    def test_estimate_is_not_required_to_fall_inside_interval(self) -> None:
        rows = self._rows_copy()
        physical = rows[self._physical_row_index(rows)]
        physical["within_15min_share"] = "0.1"
        physical["rejected_share"] = "0"
        physical["mc_95ci_low"] = "0.3"
        physical["mc_95ci_high"] = "0.8"
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            self.assertEqual(len(read_physical_summary(path)), 32)

    def test_timely_and_rejected_shares_cannot_exceed_one(self) -> None:
        rows = self._rows_copy()
        physical = rows[self._physical_row_index(rows)]
        physical["within_15min_share"] = "0.9"
        physical["rejected_share"] = "0.2"
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "shares exceeding one"):
                read_physical_summary(path)

    def test_negative_cost_is_rejected(self) -> None:
        rows = self._rows_copy()
        rows[self._physical_row_index(rows)]["eur_per_km2_yr"] = "-0.01"
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "negative cost"):
                read_physical_summary(path)

    def test_inconsistent_configuration_cost_is_rejected(self) -> None:
        rows = self._rows_copy()
        physical = rows[self._physical_row_index(rows)]
        physical["eur_per_km2_yr"] = str(float(physical["eur_per_km2_yr"]) + 1)
        with tempfile.TemporaryDirectory() as directory:
            path = self._copy_summary(directory, rows)
            with self.assertRaisesRegex(ValueError, "inconsistent cost"):
                read_physical_summary(path)

    def test_existing_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "service.png"
            output_path.touch()
            with self.assertRaises(FileExistsError):
                validate_output_path(output_path)


if __name__ == "__main__":
    unittest.main()
