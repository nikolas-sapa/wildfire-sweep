import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from coverage_capture import load_capture
from coverage_test_fixture import create_fixture
from simulator_engine import layout_bases
from simulator_server import make_server

HASH = re.compile(r"^[0-9a-f]{64}$")
META_KEYS = {
    "schema_version", "mode", "study_id", "capture_sha256", "grid_n",
    "domain_side_km", "timely_threshold_s", "outcome_codes", "source_sha256",
    "grid", "limitations",
}
CASE_KEYS = {
    "case_id", "n_bases", "wind_mps", "wind_speed_mps", "heading_deg", "profile",
    "offline_bases", "airspeed_mps", "endurance_min", "reserve_fraction",
    "launch_latency_s", "summary",
}
SUMMARY_KEYS = {
    "case_id", "unreachable_cells", "late_cells", "timely_cells",
    "weather_closed_cells", "total_cells", "timely_area_fraction",
    "reachable_area_fraction",
}
CELL_KEYS = {
    "index", "row", "column", "x_km", "y_km", "outcome", "response_s",
    "selected_base_id",
}
BASE_KEYS = {"id", "x_km", "y_km", "available"}


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


class RealHTTPCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fixture_root = create_fixture(Path(cls.tmp.name) / "capture")
        cls.loaded = load_capture(cls.fixture_root)
        cls.server = make_server(port=0, coverage_root=cls.fixture_root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.host = host
        cls.port = port
        cls.base_url = f"http://{host}:{port}"
        status, _, body = cls.request("/api/coverage/catalog")
        if status != 200:
            raise AssertionError(f"coverage catalog returned HTTP {status}: {body!r}")
        cls.catalog = cls.parse_json(body)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path, method="GET", body=None, headers=None, base_url=None):
        request = urllib.request.Request(
            (base_url or cls.base_url) + path,
            data=body,
            headers=headers or {},
            method=method,
        )
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    @staticmethod
    def parse_json(body):
        return json.loads(body, parse_constant=reject_constant)

    def assert_error_body(self, body) -> None:
        self.assertEqual(set(self.parse_json(body)), {"error"})

    def fetch_case(self, case_id):
        query = urllib.parse.urlencode({"case": case_id})
        status, headers, body = self.request(f"/api/coverage?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        return self.parse_json(body)

    def expected_bases(self, scenario):
        bases = layout_bases(scenario["n_bases"])
        offline = set(scenario["offline_bases"])
        for base in bases:
            base["available"] = base["id"] not in offline
        return bases

    def test_catalog_schema_and_provenance_match_capture(self) -> None:
        catalog = self.catalog
        manifest = self.loaded["manifest"]
        self.assertEqual(set(catalog), META_KEYS | {"layouts", "cases"})
        self.assertEqual(catalog["schema_version"], 1)
        self.assertEqual(catalog["mode"], "coverage_catalog")
        self.assertEqual(catalog["study_id"], manifest["study_id"])
        self.assertIsInstance(catalog["capture_sha256"], str)
        self.assertRegex(catalog["capture_sha256"], HASH)
        self.assertEqual(catalog["capture_sha256"], self.loaded["capture_sha256"])
        self.assertEqual(catalog["grid_n"], manifest["grid_n"])
        self.assertEqual(catalog["grid_n"], 4)
        self.assertEqual(catalog["domain_side_km"], manifest["domain_side_km"])
        self.assertEqual(catalog["timely_threshold_s"], manifest["timely_threshold_s"])
        self.assertEqual(catalog["outcome_codes"], manifest["outcome_codes"])
        self.assertEqual(catalog["outcome_codes"], {
            "unreachable": 0, "late": 1, "timely": 2, "weather_closed": 3,
        })
        self.assertEqual(catalog["source_sha256"], manifest["source_sha256"])
        self.assertEqual(catalog["grid"], manifest["grid"])
        self.assertEqual(catalog["limitations"], manifest["limitations"])
        self.assertEqual(set(catalog["layouts"]), {"9", "25"})
        for count in (9, 25):
            self.assertEqual(catalog["layouts"][str(count)], layout_bases(count))
        self.assertEqual(len(catalog["cases"]), 2)
        expected = [
            {**scenario, "summary": row}
            for scenario, row in zip(
                self.loaded["scenarios"], self.loaded["summary_rows"])
        ]
        self.assertEqual(catalog["cases"], expected)
        for entry, scenario, row in zip(
                catalog["cases"], self.loaded["scenarios"], self.loaded["summary_rows"]):
            self.assertEqual(set(entry), CASE_KEYS)
            self.assertEqual(set(row), SUMMARY_KEYS)
            self.assertEqual(row["case_id"], scenario["case_id"])
            self.assertEqual(row["total_cells"], 16)
            self.assertEqual(
                row["unreachable_cells"] + row["late_cells"]
                + row["timely_cells"] + row["weather_closed_cells"], 16)

    def test_case_payload_echoes_descriptor_and_stored_cells(self) -> None:
        catalog = self.catalog
        arrays = self.loaded["arrays"]
        names = {code: name for name, code in catalog["outcome_codes"].items()}
        for case_index, (scenario, row) in enumerate(zip(
                self.loaded["scenarios"], self.loaded["summary_rows"])):
            with self.subTest(case_id=scenario["case_id"]):
                payload = self.fetch_case(scenario["case_id"])
                self.assertEqual(set(payload), META_KEYS | {"case", "bases", "cells"})
                self.assertEqual(payload["mode"], "coverage")
                for key in META_KEYS - {"mode"}:
                    self.assertEqual(payload[key], catalog[key])
                entry = next(
                    item for item in catalog["cases"]
                    if item["case_id"] == scenario["case_id"])
                self.assertEqual(payload["case"], entry)
                self.assertEqual(payload["case"], {**scenario, "summary": row})
                self.assertEqual(
                    payload["bases"], self.expected_bases(scenario))
                grid_n = catalog["grid_n"]
                cells = payload["cells"]
                self.assertEqual(len(cells), grid_n * grid_n)
                counts = {name: 0 for name in catalog["outcome_codes"]}
                for index, cell in enumerate(cells):
                    self.assertEqual(set(cell), CELL_KEYS)
                    row_i, column_i = divmod(index, grid_n)
                    self.assertEqual(cell["index"], index)
                    self.assertEqual(cell["row"], row_i)
                    self.assertEqual(cell["column"], column_i)
                    self.assertEqual(
                        cell["x_km"], float(arrays["x_km"][column_i]))
                    self.assertEqual(
                        cell["y_km"], float(arrays["y_km"][row_i]))
                    outcome = names[int(arrays["outcome_code"][case_index, row_i, column_i])]
                    self.assertEqual(cell["outcome"], outcome)
                    counts[outcome] += 1
                    if outcome in ("timely", "late"):
                        self.assertEqual(
                            cell["response_s"],
                            float(arrays["response_s"][case_index, row_i, column_i]))
                        self.assertEqual(
                            cell["selected_base_id"],
                            int(arrays["selected_base_id"][case_index, row_i, column_i]))
                        self.assertTrue(
                            payload["bases"][cell["selected_base_id"]]["available"])
                        self.assertEqual(
                            outcome == "timely",
                            cell["response_s"] <= payload["timely_threshold_s"])
                    else:
                        self.assertIsNone(cell["response_s"])
                        self.assertIsNone(cell["selected_base_id"])
                self.assertEqual(counts["timely"], row["timely_cells"])
                self.assertEqual(counts["late"], row["late_cells"])
                self.assertEqual(counts["unreachable"], row["unreachable_cells"])
                self.assertEqual(
                    counts["weather_closed"], row["weather_closed_cells"])

    def test_case_query_rejects_missing_duplicate_and_unknown_values(self) -> None:
        case_id = self.loaded["scenarios"][0]["case_id"]
        quoted = urllib.parse.quote(case_id, safe="")
        bad_queries = (
            "/api/coverage",
            "/api/coverage?",
            "/api/coverage?other=1",
            f"/api/coverage?case={quoted}&case={quoted}",
            f"/api/coverage?case={quoted}&other=1",
            "/api/coverage?case=",
            "/api/coverage?case=not-a-real-case",
        )
        for path in bad_queries:
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 400)
                self.assert_error_body(body)
        status, _, body = self.request("/api/coverage/catalog?case=x")
        self.assertEqual(status, 400)
        self.assert_error_body(body)

    def test_missing_capture_returns_503_while_old_routes_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            absent = Path(tmp) / "absent-capture"
            server = make_server(port=0, coverage_root=absent)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                host, port = server.server_address
                base_url = f"http://{host}:{port}"
                for path in ("/api/coverage/catalog", "/api/coverage?case=x"):
                    with self.subTest(path=path):
                        status, headers, body = self.request(path, base_url=base_url)
                        self.assertEqual(status, 503)
                        self.assertEqual(
                            headers.get_content_type(), "application/json")
                        self.assert_error_body(body)
                status, headers, _ = self.request("/", base_url=base_url)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
                status, _, body = self.request("/api/catalog", base_url=base_url)
                self.assertEqual(status, 200)
                mission_catalog = self.parse_json(body)
                payload = dict(mission_catalog["defaults"])
                payload["point_km"] = [10.0, 10.0]
                status, _, body = self.request(
                    "/api/mission",
                    "POST",
                    json.dumps(payload, allow_nan=False).encode(),
                    {"Content-Type": "application/json"},
                    base_url=base_url,
                )
                self.assertEqual(status, 200)
                self.assertEqual(self.parse_json(body)["mode"], "mission")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_coverage_endpoints_have_no_post(self) -> None:
        case_id = self.loaded["scenarios"][0]["case_id"]
        query = urllib.parse.urlencode({"case": case_id})
        for path in ("/api/coverage/catalog", f"/api/coverage?{query}", "/api/coverage"):
            with self.subTest(path=path):
                status, _, body = self.request(
                    path, "POST", b"{}", {"Content-Type": "application/json"})
                self.assertEqual(status, 405)
                self.assert_error_body(body)


if __name__ == "__main__":
    unittest.main()
