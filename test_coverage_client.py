import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from coverage_capture import load_capture
from coverage_client import main
from coverage_test_fixture import create_fixture
from simulator_server import make_server

DESCRIPTOR_KEYS = {
    "case_id", "n_bases", "wind_mps", "wind_speed_mps", "heading_deg", "profile",
    "offline_bases", "airspeed_mps", "endurance_min", "reserve_fraction",
    "launch_latency_s",
}
SUMMARY_KEYS = {
    "unreachable_cells", "late_cells", "timely_cells", "weather_closed_cells",
    "total_cells", "timely_area_fraction", "reachable_area_fraction",
}


class CoverageClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.fixture_root = create_fixture(Path(cls.temp_dir.name) / "capture")
        cls.capture = load_capture(cls.fixture_root)
        cls.server = make_server(port=0, coverage_root=cls.fixture_root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"
        empty_root = Path(cls.temp_dir.name) / "empty-capture"
        empty_root.mkdir()
        cls.empty_server = make_server(port=0, coverage_root=empty_root)
        cls.empty_thread = threading.Thread(
            target=cls.empty_server.serve_forever, daemon=True)
        cls.empty_thread.start()
        empty_host, empty_port = cls.empty_server.server_address
        cls.empty_base_url = f"http://{empty_host}:{empty_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.empty_server.shutdown()
        cls.empty_server.server_close()
        cls.empty_thread.join(timeout=3)
        cls.temp_dir.cleanup()

    def _run_client(
        self, arguments: list[str], base_url: str | None = None
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(
                ["--base-url", base_url or self.base_url, *arguments])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_catalog_command_returns_capture_catalog(self) -> None:
        exit_code, output, error = self._run_client(["catalog"])
        payload = json.loads(output)
        manifest = self.capture["manifest"]
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        for key in (
            "schema_version", "mode", "study_id", "capture_sha256", "grid_n",
            "domain_side_km", "timely_threshold_s", "outcome_codes",
            "source_sha256", "grid", "limitations", "layouts", "cases",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["mode"], "coverage_catalog")
        self.assertEqual(payload["study_id"], manifest["study_id"])
        self.assertEqual(payload["capture_sha256"], self.capture["capture_sha256"])
        self.assertEqual(payload["grid_n"], manifest["grid_n"])
        self.assertEqual(payload["domain_side_km"], manifest["domain_side_km"])
        self.assertEqual(payload["timely_threshold_s"], manifest["timely_threshold_s"])
        self.assertEqual(payload["outcome_codes"], manifest["outcome_codes"])
        self.assertEqual(payload["source_sha256"], manifest["source_sha256"])
        self.assertEqual(payload["grid"], manifest["grid"])
        self.assertEqual(payload["limitations"], manifest["limitations"])
        self.assertEqual(set(payload["layouts"]), {"9", "25"})
        cases = payload["cases"]
        self.assertEqual(
            [entry["case_id"] for entry in cases],
            [case["case_id"] for case in self.capture["scenarios"]])
        for entry, scenario, row in zip(
                cases, self.capture["scenarios"], self.capture["summary_rows"]):
            self.assertTrue(DESCRIPTOR_KEYS <= set(entry))
            self.assertTrue(SUMMARY_KEYS <= set(entry["summary"]))
            for key, value in scenario.items():
                self.assertEqual(entry[key], value)
            for name in SUMMARY_KEYS:
                self.assertEqual(entry["summary"][name], row[name])
        json.dumps(payload, allow_nan=False)

    def test_case_command_returns_requested_case(self) -> None:
        manifest = self.capture["manifest"]
        grid_n = manifest["grid_n"]
        for scenario, row in zip(
                self.capture["scenarios"], self.capture["summary_rows"]):
            with self.subTest(case_id=scenario["case_id"]):
                exit_code, output, error = self._run_client(
                    ["case", "--case", scenario["case_id"]])
                payload = json.loads(output)
                self.assertEqual(exit_code, 0)
                self.assertEqual(error, "")
                for key in (
                    "schema_version", "mode", "study_id", "capture_sha256",
                    "grid_n", "domain_side_km", "timely_threshold_s",
                    "outcome_codes", "source_sha256", "grid", "limitations",
                    "case", "bases", "cells",
                ):
                    self.assertIn(key, payload)
                self.assertEqual(payload["schema_version"], 1)
                self.assertEqual(payload["mode"], "coverage")
                self.assertEqual(payload["study_id"], manifest["study_id"])
                self.assertEqual(
                    payload["capture_sha256"], self.capture["capture_sha256"])
                self.assertEqual(payload["grid_n"], grid_n)
                self.assertEqual(payload["case"]["case_id"], scenario["case_id"])
                for key, value in scenario.items():
                    self.assertEqual(payload["case"][key], value)
                self.assertEqual(len(payload["bases"]), scenario["n_bases"])
                cells = payload["cells"]
                self.assertEqual(len(cells), grid_n * grid_n)
                counts = {name: 0 for name in manifest["outcome_codes"]}
                for cell in cells:
                    self.assertEqual(
                        cell["index"], cell["row"] * grid_n + cell["column"])
                    self.assertIn(cell["outcome"], manifest["outcome_codes"])
                    counts[cell["outcome"]] += 1
                    if cell["outcome"] in ("timely", "late"):
                        self.assertIsInstance(
                            cell["response_s"], (int, float))
                        self.assertGreaterEqual(cell["response_s"], 0)
                        self.assertIsInstance(cell["selected_base_id"], int)
                        self.assertGreaterEqual(cell["selected_base_id"], 0)
                        self.assertLess(
                            cell["selected_base_id"], scenario["n_bases"])
                    else:
                        self.assertIsNone(cell["response_s"])
                        self.assertIsNone(cell["selected_base_id"])
                    self.assertIsInstance(cell["x_km"], (int, float))
                    self.assertIsInstance(cell["y_km"], (int, float))
                    self.assertGreaterEqual(cell["x_km"], 0)
                    self.assertGreaterEqual(cell["y_km"], 0)
                    self.assertLessEqual(
                        cell["x_km"], manifest["domain_side_km"])
                    self.assertLessEqual(
                        cell["y_km"], manifest["domain_side_km"])
                self.assertEqual(counts["timely"], row["timely_cells"])
                self.assertEqual(counts["late"], row["late_cells"])
                self.assertEqual(
                    counts["unreachable"], row["unreachable_cells"])
                self.assertEqual(
                    counts["weather_closed"], row["weather_closed_cells"])
                json.dumps(payload, allow_nan=False)

    def test_weather_closed_case_serializes_unserved_cells_as_null(self) -> None:
        scenario, row = next(
            (case, summary) for case, summary in zip(
                self.capture["scenarios"], self.capture["summary_rows"])
            if summary["weather_closed_cells"] == summary["total_cells"])
        exit_code, output, error = self._run_client(
            ["case", "--case", scenario["case_id"]])
        payload = json.loads(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(row["weather_closed_cells"], row["total_cells"])
        self.assertTrue(payload["cells"])
        for cell in payload["cells"]:
            self.assertEqual(cell["outcome"], "weather_closed")
            self.assertIsNone(cell["response_s"])
            self.assertIsNone(cell["selected_base_id"])

    def test_encoded_invalid_case_ids_are_clean_errors(self) -> None:
        invalid_ids = (
            "no-such-case", "../manifest", "not a case", "b9-w12%2fh000",
            "case=x&season=1", "",
        )
        for case_id in invalid_ids:
            with self.subTest(case_id=case_id):
                exit_code, output, error = self._run_client(
                    ["case", "--case", case_id])
                self.assertEqual(exit_code, 2)
                self.assertEqual(output, "")
                self.assertIn("error", error.lower())
                self.assertNotIn("Traceback", error)

    def test_missing_capture_returns_clean_error(self) -> None:
        case_id = self.capture["scenarios"][0]["case_id"]
        for arguments in (["catalog"], ["case", "--case", case_id]):
            with self.subTest(arguments=arguments):
                exit_code, output, error = self._run_client(
                    arguments, base_url=self.empty_base_url)
                self.assertEqual(exit_code, 2)
                self.assertEqual(output, "")
                self.assertIn("503", error)
                self.assertNotIn("Traceback", error)

    def test_invalid_base_urls_rejected_before_any_request(self) -> None:
        class CountingHandler(BaseHTTPRequestHandler):
            requests = 0

            def do_GET(self) -> None:
                type(self).requests += 1
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, format_string: str, *args: object) -> None:
                return

        counter = ThreadingHTTPServer(("127.0.0.1", 0), CountingHandler)
        counter_thread = threading.Thread(
            target=counter.serve_forever, daemon=True)
        counter_thread.start()
        host, port = counter.server_address
        loop = f"http://127.0.0.1:{port}"
        try:
            invalid_urls = (
                "https://example.com", "http://example.com",
                f"https://127.0.0.1:{port}", f"ftp://127.0.0.1:{port}",
                f"http://user:pw@127.0.0.1:{port}",
                f"{loop}/coverage", f"{loop}?case=x", f"{loop}#fragment",
                "http://127.0.0.1:99999", "http://127.0.0.1:notaport",
                "not-a-url",
            )
            for url in invalid_urls:
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), \
                        contextlib.redirect_stderr(stderr):
                    exit_code = main(["--base-url", url, "catalog"])
                with self.subTest(url=url):
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("error", stderr.getvalue().lower())
            for arguments in ([], ["case"], ["bogus"], ["catalog", "--extra"]):
                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    with self.assertRaises(SystemExit) as caught:
                        main(["--base-url", loop, *arguments])
                with self.subTest(arguments=arguments):
                    self.assertEqual(caught.exception.code, 2)
            self.assertEqual(CountingHandler.requests, 0)
        finally:
            counter.shutdown()
            counter.server_close()
            counter_thread.join(timeout=3)

    def test_redirect_target_is_never_requested(self) -> None:
        class TargetHandler(BaseHTTPRequestHandler):
            requests = 0

            def do_GET(self) -> None:
                type(self).requests += 1
                self.send_response(200)
                self.send_header("Content-Length", "3")
                self.end_headers()
                self.wfile.write(b"hit")

            def log_message(self, format_string: str, *args: object) -> None:
                return

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(302)
                self.send_header("Location", self.server.target_url)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format_string: str, *args: object) -> None:
                return

        target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
        target_thread = threading.Thread(target=target.serve_forever, daemon=True)
        target_thread.start()
        target_host, target_port = target.server_address
        redirect = ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler)
        redirect.target_url = f"http://{target_host}:{target_port}/hit"
        redirect_thread = threading.Thread(
            target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        host, port = redirect.server_address
        case_id = self.capture["scenarios"][0]["case_id"]
        try:
            for arguments in (["catalog"], ["case", "--case", case_id]):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with contextlib.redirect_stdout(stdout), \
                        contextlib.redirect_stderr(stderr):
                    exit_code = main(
                        ["--base-url", f"http://{host}:{port}", *arguments])
                with self.subTest(arguments=arguments):
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertIn("redirect", stderr.getvalue().lower())
        finally:
            redirect.shutdown()
            redirect.server_close()
            redirect_thread.join(timeout=3)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=3)
        self.assertEqual(TargetHandler.requests, 0)


if __name__ == "__main__":
    unittest.main()
