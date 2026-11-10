import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from coverage_capture import load_capture
from coverage_data import CoverageData
from coverage_engine import OUTCOME_CODES
from coverage_test_fixture import create_fixture
from simulator_engine import layout_bases


OUTCOME_NAMES = {code: name for name, code in OUTCOME_CODES.items()}
CATALOG_KEYS = {
    "schema_version", "mode", "study_id", "capture_sha256", "grid_n",
    "domain_side_km", "timely_threshold_s", "outcome_codes", "source_sha256",
    "grid", "limitations", "layouts", "cases",
}
CASE_KEYS = CATALOG_KEYS - {"layouts", "cases"} | {"case", "bases", "cells"}
CELL_KEYS = {
    "index", "row", "column", "x_km", "y_km", "outcome", "response_s",
    "selected_base_id",
}


class CoverageDataTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name) / "capture"
        create_fixture(self.root)
        self.loaded = load_capture(self.root)
        self.data = CoverageData(self.root)
        self.grid_n = self.loaded["manifest"]["grid_n"]
        self.case_ids = [case["case_id"] for case in self.loaded["scenarios"]]
        self.scenarios = {case["case_id"]: case for case in self.loaded["scenarios"]}
        self.summary_rows = {row["case_id"]: row for row in self.loaded["summary_rows"]}

    def tearDown(self):
        self._temporary.cleanup()

    def _case_index(self, case_id):
        return self.loaded["arrays"]["case_ids"].tolist().index(case_id)

    @staticmethod
    def _tamper_manifest(path):
        manifest = json.loads(path.read_bytes())
        manifest["kind"] = "tampered-capture"
        path.write_bytes(json.dumps(manifest).encode("utf-8"))

    @staticmethod
    def _tamper_bytes(path):
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0xFF
        path.write_bytes(bytes(data))

    def test_catalog_lists_fixture_cases_on_grid4(self):
        catalog = self.data.catalog()
        self.assertEqual(set(catalog), CATALOG_KEYS)
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["mode"], "coverage_catalog")
        self.assertEqual(catalog["grid_n"], 4)
        self.assertEqual(catalog["capture_sha256"], self.loaded["capture_sha256"])
        manifest = self.loaded["manifest"]
        for key in ("study_id", "domain_side_km", "timely_threshold_s",
                    "outcome_codes", "source_sha256", "grid", "limitations"):
            self.assertEqual(catalog[key], manifest[key])
        self.assertEqual([case["case_id"] for case in catalog["cases"]], self.case_ids)
        self.assertEqual(len(catalog["cases"]), 2)
        for case in catalog["cases"]:
            descriptor = {key: value for key, value in case.items() if key != "summary"}
            self.assertEqual(descriptor, self.scenarios[case["case_id"]])
            self.assertEqual(case["summary"], self.summary_rows[case["case_id"]])
            self.assertEqual(case["summary"]["total_cells"], 16)
        self.assertEqual(set(catalog["layouts"]), {"9", "25"})
        for count in ("9", "25"):
            self.assertEqual(catalog["layouts"][count], layout_bases(int(count)))
            for position, base in enumerate(catalog["layouts"][count]):
                self.assertEqual(base["id"], position)
                self.assertTrue(base["available"])

    def test_case_cells_match_stored_coordinates_and_codes(self):
        case_id = self.case_ids[0]
        payload = self.data.case(case_id)
        self.assertEqual(set(payload), CASE_KEYS)
        self.assertEqual(payload["mode"], "coverage")
        self.assertEqual(payload["case"]["case_id"], case_id)
        self.assertEqual(len(payload["cells"]), 16)
        index = self._case_index(case_id)
        arrays = self.loaded["arrays"]
        centers_x = arrays["x_km"]
        centers_y = arrays["y_km"]
        response_s = arrays["response_s"][index]
        selected_base_id = arrays["selected_base_id"][index]
        outcome_code = arrays["outcome_code"][index]
        ordering = []
        for cell in payload["cells"]:
            self.assertEqual(set(cell), CELL_KEYS)
            row, column = cell["row"], cell["column"]
            self.assertEqual(cell["index"], row * self.grid_n + column)
            ordering.append(cell["index"])
            self.assertEqual(cell["x_km"], float(centers_x[column]))
            self.assertEqual(cell["y_km"], float(centers_y[row]))
            self.assertEqual(cell["outcome"], OUTCOME_NAMES[int(outcome_code[row][column])])
            stored_response = float(response_s[row][column])
            if math.isfinite(stored_response):
                self.assertEqual(cell["response_s"], stored_response)
                self.assertEqual(
                    cell["selected_base_id"], int(selected_base_id[row][column]))
            else:
                self.assertIsNone(cell["response_s"])
                self.assertIsNone(cell["selected_base_id"])
        self.assertEqual(ordering, list(range(self.grid_n * self.grid_n)))

    def test_case_descriptor_and_metadata_match_catalog(self):
        catalog = self.data.catalog()
        for case_id in self.case_ids:
            payload = self.data.case(case_id)
            expected = next(
                case for case in catalog["cases"] if case["case_id"] == case_id)
            self.assertEqual(payload["case"], expected)
            for key in CATALOG_KEYS - {"mode", "layouts", "cases"}:
                self.assertEqual(payload[key], catalog[key])

    def test_case_bases_preserve_original_ids_and_availability(self):
        for case_id in self.case_ids:
            payload = self.data.case(case_id)
            layout = layout_bases(payload["case"]["n_bases"])
            offline = payload["case"]["offline_bases"]
            self.assertEqual(len(payload["bases"]), len(layout))
            for base, reference in zip(payload["bases"], layout):
                self.assertEqual(base["id"], reference["id"])
                self.assertEqual(base["x_km"], reference["x_km"])
                self.assertEqual(base["y_km"], reference["y_km"])
                self.assertEqual(base["available"], base["id"] not in offline)

    def test_unknown_case_id_fails(self):
        for case_id in ("no-such-case", self.case_ids[0] + "-extra", ""):
            with self.subTest(case_id=case_id):
                with self.assertRaises((ValueError, KeyError)):
                    self.data.case(case_id)

    def test_editing_returned_objects_changes_no_later_output(self):
        catalog = self.data.catalog()
        pristine_catalog = copy.deepcopy(catalog)
        catalog["cases"][0]["summary"]["timely_cells"] = -1
        catalog["cases"][0]["offline_bases"].append(0)
        catalog["layouts"]["9"][0]["available"] = False
        catalog["limitations"].append("edited")
        case_id = self.case_ids[0]
        payload = self.data.case(case_id)
        pristine_payload = copy.deepcopy(payload)
        payload["cells"][0]["response_s"] = "edited"
        payload["case"]["offline_bases"].append(0)
        payload["bases"][0]["available"] = False
        payload["grid"]["north"] = "edited"
        self.assertEqual(self.data.catalog(), pristine_catalog)
        self.assertEqual(self.data.case(case_id), pristine_payload)

    def test_missing_capture_fails_lazily_not_at_construction(self):
        missing = Path(self._temporary.name) / "absent"
        data = CoverageData(missing)
        with self.assertRaises((ValueError, OSError)):
            data.catalog()
        with self.assertRaises((ValueError, OSError)):
            data.case(self.case_ids[0])

    def test_tampered_manifest_and_archive_fail(self):
        mutations = (
            ("manifest.json", self._tamper_manifest),
            ("coverage.npz", self._tamper_bytes),
            ("summary.csv", self._tamper_bytes),
            ("scenarios.json", self._tamper_bytes),
        )
        for name, mutate in mutations:
            with self.subTest(component=name):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary) / "capture"
                    create_fixture(root)
                    mutate(root / name)
                    with self.assertRaises((ValueError, OSError)):
                        CoverageData(root).catalog()

    def test_weather_closed_case_serializes_unserved_cells_as_null(self):
        payload = self.data.case(self.case_ids[-1])
        self.assertEqual(payload["case"]["wind_speed_mps"], 13.0)
        self.assertEqual(payload["case"]["summary"]["weather_closed_cells"], 16)
        self.assertEqual(payload["case"]["summary"]["timely_cells"], 0)
        self.assertEqual(payload["case"]["summary"]["timely_area_fraction"], 0)
        for cell in payload["cells"]:
            self.assertEqual(cell["outcome"], "weather_closed")
            self.assertIsNone(cell["response_s"])
            self.assertIsNone(cell["selected_base_id"])
        json.dumps(payload, allow_nan=False)

    def test_payloads_are_json_safe_independent_and_repeatable(self):
        catalog = self.data.catalog()
        json.dumps(catalog, allow_nan=False)
        for case_id in self.case_ids:
            payload = self.data.case(case_id)
            json.dumps(payload, allow_nan=False)
            for cell in payload["cells"]:
                if cell["response_s"] is not None:
                    self.assertTrue(math.isfinite(cell["response_s"]))
        repeated = self.data.catalog()
        self.assertIsNot(repeated, catalog)
        self.assertEqual(repeated, catalog)


if __name__ == "__main__":
    unittest.main()
