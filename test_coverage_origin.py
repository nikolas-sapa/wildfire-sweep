import http.client
import json
import math
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from coverage_test_fixture import create_fixture
from simulator_server import make_server

COVERAGE_ASSETS = (
    "index.html",
    "styles.css",
    "app.js",
    "map.js",
    "controls.js",
    "table.js",
    "details.js",
    "comparison.js",
    "export.js",
    "session.js",
    "api.js",
    "state.js",
    "legend.js",
    "data_contract.js",
)
CAPTURE_FILES = ("manifest.json", "scenarios.json", "summary.csv", "coverage.npz")


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


def check_finite(suite: unittest.TestCase, value: object) -> None:
    if isinstance(value, float):
        suite.assertTrue(math.isfinite(value))
    elif isinstance(value, dict):
        for child in value.values():
            check_finite(suite, child)
    elif isinstance(value, list):
        for child in value:
            check_finite(suite, child)


class CoverageOriginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.fixture_root = Path(cls.temporary.name) / "capture"
        create_fixture(cls.fixture_root)
        cls.server = make_server(port=0, coverage_root=cls.fixture_root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.host = host
        cls.port = port
        cls.base_url = f"http://{host}:{port}"
        status, _, body = cls.request("/api/coverage/catalog")
        if status != 200:
            cls._stop()
            raise AssertionError(f"coverage catalog returned HTTP {status}: {body!r}")
        cls.catalog = cls.parse_json(body)

    @classmethod
    def _stop(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._stop()

    @classmethod
    def request(cls, path, method="GET", body=None, headers=None):
        request = urllib.request.Request(
            cls.base_url + path,
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

    @staticmethod
    def get_raw(host, port, path):
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def raw_request(self, method, path, headers, body=b""):
        connection = http.client.HTTPConnection(
            self.host,
            self.port,
            timeout=5,
        )
        try:
            connection.putrequest(method, path, skip_host=True)
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders(body)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def local_host(self) -> str:
        return f"{self.host}:{self.port}"

    def atlas_paths(self) -> tuple[str, ...]:
        case_id = self.catalog["cases"][0]["case_id"]
        query = urllib.parse.urlencode({"case": case_id})
        return (
            "/api/coverage/catalog",
            f"/api/coverage?{query}",
            "/coverage",
            "/coverage/",
            "/coverage/data_contract.js",
        )

    def assert_error_json(self, body) -> None:
        result = self.parse_json(body)
        self.assertEqual(result.keys(), {"error"})
        self.assertIsInstance(result["error"], str)
        check_finite(self, result)

    def test_valid_loopback_host_serves_atlas_routes(self) -> None:
        self.assertEqual(self.catalog["mode"], "coverage_catalog")
        self.assertEqual(self.catalog["grid_n"], 4)
        self.assertEqual(self.catalog["study_id"], "2026-11-10-coverage-atlas-v1")
        case_ids = [case["case_id"] for case in self.catalog["cases"]]
        self.assertEqual(len(case_ids), 2)
        self.assertEqual(len(set(case_ids)), 2)
        check_finite(self, self.catalog)
        for case_id in case_ids:
            with self.subTest(case_id=case_id):
                query = urllib.parse.urlencode({"case": case_id})
                status, headers, body = self.request(f"/api/coverage?{query}")
                result = self.parse_json(body)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertEqual(headers.get("Cache-Control"), "no-store")
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertIn(
                    "default-src 'self'",
                    headers.get("Content-Security-Policy", ""),
                )
                self.assertEqual(headers.get("Access-Control-Allow-Origin"), None)
                self.assertEqual(headers.get("Access-Control-Allow-Credentials"), None)
                self.assertEqual(result["mode"], "coverage")
                self.assertEqual(result["case"]["case_id"], case_id)
                self.assertEqual(len(result["cells"]), 16)
                check_finite(self, result)
        for name in COVERAGE_ASSETS:
            with self.subTest(asset=name):
                status, headers, _ = self.request(f"/coverage/{name}")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        for path in ("/coverage", "/coverage/"):
            with self.subTest(page=path):
                status, headers, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
        for host in ("localhost", "LOCALHOST", "127.0.0.1"):
            with self.subTest(host=host):
                status, body = self.raw_request(
                    "GET",
                    "/api/coverage/catalog",
                    [("Host", f"{host}:{self.port}")],
                )
                self.assertEqual(status, 200)
                self.parse_json(body)

    def test_same_origin_header_is_accepted(self) -> None:
        origin = f"http://{self.local_host()}"
        for path in self.atlas_paths():
            with self.subTest(path=path):
                status, headers, body = self.request(path, headers={"Origin": origin})
                self.assertEqual(status, 200)
                if headers.get_content_type() == "application/json":
                    self.parse_json(body)
                elif path.startswith("/api/"):
                    self.fail("coverage API response was not application/json")
        status, headers, body = self.request(
            "/api/coverage/catalog", headers={"Origin": origin}
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertEqual(self.parse_json(body)["mode"], "coverage_catalog")

    def test_nonlocal_hosts_are_rejected(self) -> None:
        bad_hosts = (
            "not-local.example",
            "127.0.0.1",
            "localhost",
            f"127.0.0.1:{self.port + 1}",
            "127.0.0.1.not-local.example",
            f"localhost:{self.port + 1}",
        )
        for path in self.atlas_paths():
            for host in bad_hosts:
                with self.subTest(path=path, host=host):
                    status, _, body = self.request(path, headers={"Host": host})
                    self.assertEqual(status, 403)
                    self.assert_error_json(body)

    def test_foreign_origins_are_rejected(self) -> None:
        host = self.local_host()
        foreign = (
            "https://not-local.example",
            "http://not-local.example",
            "null",
            "http://127.0.0.1",
            f"http://{host}/path",
            f"http://{host}?query=1",
            f"http://user@{host}",
            f"http://{host}@not-local.example",
            f"https://{host}",
            "http://[",
        )
        for path in self.atlas_paths():
            for origin in foreign:
                with self.subTest(path=path, origin=origin):
                    status, _, body = self.request(path, headers={"Origin": origin})
                    self.assertEqual(status, 403)
                    self.assert_error_json(body)
        status, _, body = self.request(
            "/api/coverage/catalog",
            "POST",
            b"{}",
            {"Origin": "https://not-local.example", "Content-Type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assert_error_json(body)

    def test_duplicate_boundary_headers_are_rejected(self) -> None:
        cases = (
            (
                "GET",
                "/api/coverage/catalog",
                [("Host", self.local_host()), ("Host", self.local_host())],
                403,
            ),
            (
                "GET",
                "/coverage/data_contract.js",
                [("Host", self.local_host()), ("Host", self.local_host())],
                403,
            ),
            (
                "GET",
                "/api/coverage/catalog",
                [
                    ("Host", self.local_host()),
                    ("Origin", f"http://{self.local_host()}"),
                    ("Origin", f"http://{self.local_host()}"),
                ],
                403,
            ),
            (
                "GET",
                "/api/coverage/catalog",
                [
                    ("Host", self.local_host()),
                    ("Content-Length", "0"),
                    ("Content-Length", "0"),
                ],
                400,
            ),
            (
                "GET",
                "/api/coverage/catalog",
                [],
                403,
            ),
        )
        for method, path, headers, expected in cases:
            with self.subTest(path=path, headers=headers):
                status, body = self.raw_request(method, path, headers)
                self.assertEqual(status, expected)
                self.assert_error_json(body)

    def test_traversal_and_encoded_targets_do_not_expose_files(self) -> None:
        paths = (
            "/coverage/../simulator_server.py",
            "/coverage/../coverage_capture.py",
            "/coverage/../../sweep.py",
            "/coverage/../simulator_web/index.html",
            "/coverage/%2e%2e/simulator_server.py",
            "/coverage/%2e%2e/%2e%2e/simulator_client.py",
            "/coverage/..%2fmanifest.json",
            "/coverage%2f..%2fsimulator_protocol.json",
            "/coverage/..%5cmanifest.json",
            "/coverage//../sweep.py",
            "/coverage/data_contract.js%00",
            "/coverage/./%2e%2e/research.py",
        )
        for path in paths:
            with self.subTest(path=path):
                status, body = self.raw_request(
                    "GET",
                    path,
                    [("Host", self.local_host())],
                )
                self.assertEqual(status, 404)
                self.assert_error_json(body)

    def test_capture_and_source_names_are_never_served(self) -> None:
        paths = [
            "/simulator_server.py",
            "/coverage_capture.py",
            "/coverage/tests/data_contract.test.mjs",
            "/coverage/fonts/geist-latin.woff2",
            "/coverage/subdir/data_contract.js",
        ]
        paths += [f"/{name}" for name in CAPTURE_FILES]
        paths += [f"/coverage/{name}" for name in CAPTURE_FILES]
        for path in paths:
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assert_error_json(body)

    def test_duplicate_slashes_and_dot_segments_stay_unlisted(self) -> None:
        for path in (
            "//coverage/data_contract.js",
            "/coverage//data_contract.js",
            "/coverage/./data_contract.js",
            "/coverage//",
        ):
            with self.subTest(path=path):
                status, body = self.raw_request(
                    "GET",
                    path,
                    [("Host", self.local_host())],
                )
                self.assertEqual(status, 404)
                self.assert_error_json(body)

    def test_methods_other_than_get_are_not_allowed(self) -> None:
        for path in self.atlas_paths():
            for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
                with self.subTest(path=path, method=method):
                    status, body = self.raw_request(
                        method,
                        path,
                        [("Host", self.local_host())],
                    )
                    self.assertEqual(status, 405)
                    self.assert_error_json(body)
            with self.subTest(path=path, method="HEAD"):
                status, body = self.raw_request(
                    "HEAD",
                    path,
                    [("Host", self.local_host())],
                )
                self.assertEqual(status, 405)
                self.assertEqual(body, b"")

    def test_coverage_query_validation_fails_closed(self) -> None:
        case_id = urllib.parse.quote(
            self.catalog["cases"][0]["case_id"], safe=""
        )
        bad_targets = (
            "/api/coverage",
            "/api/coverage?",
            "/api/coverage?case=",
            f"/api/coverage?case={case_id}&case={case_id}",
            f"/api/coverage?case={case_id}&extra=1",
            "/api/coverage?case=not-a-real-case",
            "/api/coverage?case=../manifest.json",
            "/api/coverage?path=x",
            "/api/coverage/catalog?x=1",
        )
        for path in bad_targets:
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 400)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assert_error_json(body)
        for path in ("/api/coverage/catalog/", "/API/coverage/catalog"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assert_error_json(body)

    def test_missing_capture_reports_json_503_and_stays_local(self) -> None:
        absent = Path(self.temporary.name) / "absent"
        server = make_server(port=0, coverage_root=absent)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            for path in ("/api/coverage/catalog", "/api/coverage?case=x"):
                with self.subTest(path=path):
                    status, body = self.get_raw("127.0.0.1", port, path)
                    self.assertEqual(status, 503)
                    self.assert_error_json(body)
            status, _ = self.get_raw("127.0.0.1", port, "/")
            self.assertEqual(status, 200)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_existing_mission_lab_routes_keep_prior_contract(self) -> None:
        status, headers, _ = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "text/html")
        status, headers, _ = self.request("/fonts/geist-latin.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "font/woff2")
        status, _, body = self.request(
            "/api/mission",
            "POST",
            b"{}",
            {"Content-Type": "application/json"},
        )
        result = self.parse_json(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "mission")
        check_finite(self, result)
        checks = (
            ("/api/mission", "GET", None, {}, 405),
            ("/api/catalog", "POST", b"{}", {}, 405),
            ("/api/unknown", "GET", None, {}, 404),
            (
                "/api/mission",
                "POST",
                b"{}",
                {"Content-Type": "text/plain"},
                415,
            ),
            (
                "/api/mission",
                "POST",
                b"not-json",
                {"Content-Type": "application/json"},
                400,
            ),
            (
                "/api/mission",
                "POST",
                b'{"n_bases": 7}',
                {"Content-Type": "application/json"},
                400,
            ),
        )
        for path, method, body, headers, expected in checks:
            with self.subTest(path=path, method=method, expected=expected):
                status, _, response = self.request(path, method, body, headers)
                self.assertEqual(status, expected)
                self.assert_error_json(response)


if __name__ == "__main__":
    unittest.main()
