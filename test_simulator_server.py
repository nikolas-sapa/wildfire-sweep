import http.client
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from simulator_server import STATIC_FILES, make_server


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


class SimulatorServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = make_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.host = host
        cls.port = port
        cls.base_url = f"http://{host}:{port}"
        status, _, body = cls.request("/api/catalog")
        if status != 200:
            raise AssertionError(f"catalog returned HTTP {status}: {body!r}")
        cls.catalog = cls.parse_json(body)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

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

    def test_catalog_and_mission_use_real_local_apis(self) -> None:
        self.assertEqual(self.catalog["mode"], "catalog")
        payload = dict(self.catalog["defaults"])
        payload["point_km"] = [10.0, 10.0]
        status, headers, body = self.request(
            "/api/mission",
            "POST",
            json.dumps(payload, allow_nan=False).encode(),
            {"Content-Type": "application/json"},
        )
        result = self.parse_json(body)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "application/json")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("Access-Control-Allow-Origin"), None)
        self.assertEqual(headers.get("Access-Control-Allow-Credentials"), None)
        self.assertEqual(result["mode"], "mission")
        self.assertEqual(result["inputs"]["point_km"], [10.0, 10.0])

    def test_replay_reads_captured_case_and_season(self) -> None:
        case_id = self.catalog["study"]["cases"][0]["case_id"]
        query = urllib.parse.urlencode({"case": case_id, "season": 0})
        status, _, body = self.request(f"/api/replay?{query}")
        result = self.parse_json(body)
        self.assertEqual(status, 200)
        self.assertEqual(result["mode"], "replay")
        self.assertEqual(result["case_id"], case_id)
        self.assertEqual(result["season"], 0)

    def test_static_whitelist_serves_only_declared_assets(self) -> None:
        for name in STATIC_FILES:
            with self.subTest(asset=name):
                status, _, _ = self.request(f"/{name}")
                self.assertEqual(status, 200)
        for path in ("/", "/index.html"):
            with self.subTest(asset=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 200)
        for path in ("/simulator_protocol.json", "/fonts/OFL.txt"):
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404)

    def test_invalid_json_size_media_type_and_routes_fail_closed(self) -> None:
        invalid = (
            (b'{"n_bases":', {"Content-Type": "application/json"}, 400),
            (
                b'{"n_bases":9,"n_bases":25}',
                {"Content-Type": "application/json"},
                400,
            ),
            (
                b'{"point_km":[NaN,0]}',
                {"Content-Type": "application/json"},
                400,
            ),
            (b"{}", {"Content-Type": "text/plain"}, 415),
            (b" " * 4097, {"Content-Type": "application/json"}, 413),
        )
        for body, headers, expected in invalid:
            with self.subTest(expected=expected, size=len(body)):
                status, _, response = self.request(
                    "/api/mission",
                    "POST",
                    body,
                    headers,
                )
                self.assertEqual(status, expected)
                self.assertEqual(self.parse_json(response).keys(), {"error"})
        status, _, body = self.request("/api/unknown")
        self.assertEqual(status, 404)
        self.assertEqual(self.parse_json(body).keys(), {"error"})
        status, _, body = self.request("/api/catalog", "POST", b"{}")
        self.assertEqual(status, 405)
        self.assertEqual(self.parse_json(body).keys(), {"error"})

    def test_query_host_origin_and_path_validation(self) -> None:
        status, _, body = self.request("/api/replay?case=x&season=0&season=1")
        self.assertEqual(status, 400)
        self.assertEqual(self.parse_json(body).keys(), {"error"})
        for headers in (
            {"Host": "not-local.example"},
            {"Origin": "https://not-local.example"},
            {"Origin": "http://["},
        ):
            with self.subTest(headers=headers):
                status, _, body = self.request("/api/catalog", headers=headers)
                self.assertEqual(status, 403)
                self.assertEqual(self.parse_json(body).keys(), {"error"})
        status, body = self.raw_request(
            "GET",
            "/%2e%2e/simulator_protocol.json",
            [("Host", f"{self.host}:{self.port}")],
        )
        self.assertEqual(status, 404)
        self.assertEqual(self.parse_json(body).keys(), {"error"})

    def test_duplicate_boundary_headers_are_rejected(self) -> None:
        cases = (
            (
                "GET",
                "/api/catalog",
                [
                    ("Host", f"{self.host}:{self.port}"),
                    ("Host", f"{self.host}:{self.port}"),
                ],
                b"",
                403,
            ),
            (
                "GET",
                "/api/catalog",
                [
                    ("Host", f"{self.host}:{self.port}"),
                    ("Origin", f"http://{self.host}:{self.port}"),
                    ("Origin", f"http://{self.host}:{self.port}"),
                ],
                b"",
                403,
            ),
            (
                "POST",
                "/api/mission",
                [
                    ("Host", f"{self.host}:{self.port}"),
                    ("Content-Type", "application/json"),
                    ("Content-Length", "2"),
                    ("Content-Length", "2"),
                ],
                b"{}",
                400,
            ),
        )
        for method, path, headers, body, expected in cases:
            with self.subTest(headers=headers):
                status, response = self.raw_request(method, path, headers, body)
                self.assertEqual(status, expected)
                self.assertEqual(self.parse_json(response).keys(), {"error"})

    def test_malformed_bracket_request_target_returns_json_error(self) -> None:
        status, body = self.raw_request(
            "GET",
            "//[::1",
            [("Host", f"{self.host}:{self.port}")],
        )
        self.assertIn(status, {400, 404})
        self.assertEqual(self.parse_json(body).keys(), {"error"})


if __name__ == "__main__":
    unittest.main()
