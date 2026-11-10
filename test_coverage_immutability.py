import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from coverage_capture import (
    ARRAY_NAMES,
    ROOT,
    SOURCE_NAMES,
    STUDY_ID,
    load_capture,
)
from coverage_data import CoverageData
from coverage_test_fixture import create_fixture
from simulator_server import make_server

CAPTURE_FILES = ("manifest.json", "scenarios.json", "summary.csv", "coverage.npz")


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_digests(root):
    root = Path(root)
    return {path.name: _sha256(path) for path in sorted(root.iterdir()) if path.is_file()}


def _source_digests():
    return {name: _sha256(ROOT / name) for name in SOURCE_NAMES}


def _flip_byte(data: bytes) -> bytes:
    middle = len(data) // 2
    return data[:middle] + bytes([data[middle] ^ 0xFF]) + data[middle + 1:]


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value: {value}")


class CaptureReaderImmutabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "capture"
        create_fixture(cls.root)
        cls._before_fixture = _tree_digests(cls.root)
        cls._before_sources = _source_digests()
        cls.baseline = load_capture(cls.root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _assert_files_unchanged(self) -> None:
        self.assertEqual(_tree_digests(self.root), self._before_fixture)
        self.assertEqual(_source_digests(), self._before_sources)

    def test_reader_payload_shape(self) -> None:
        self.assertEqual(
            set(self.baseline),
            {"manifest", "scenarios", "summary_rows", "arrays", "capture_sha256"},
        )
        self.assertEqual(set(self.baseline["arrays"]), set(ARRAY_NAMES))
        manifest = self.baseline["manifest"]
        self.assertEqual(manifest["kind"], "wildfire-coverage-atlas-capture")
        self.assertEqual(manifest["study_id"], STUDY_ID)
        self.assertEqual(manifest["study_id"], "2026-11-10-coverage-atlas-v1")
        self.assertEqual(manifest["grid_n"], 4)
        self.assertEqual(len(self.baseline["scenarios"]), 2)
        self.assertEqual(len(self.baseline["summary_rows"]), 2)
        digest = hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest()
        self.assertEqual(self.baseline["capture_sha256"], digest)

    def test_repeated_loads_return_identical_stored_values(self) -> None:
        again = load_capture(self.root)
        self.assertIsNot(again["manifest"], self.baseline["manifest"])
        self.assertIsNot(again["scenarios"], self.baseline["scenarios"])
        self.assertIsNot(again["summary_rows"], self.baseline["summary_rows"])
        self.assertEqual(again["manifest"], self.baseline["manifest"])
        self.assertEqual(again["scenarios"], self.baseline["scenarios"])
        self.assertEqual(again["summary_rows"], self.baseline["summary_rows"])
        self.assertEqual(again["capture_sha256"], self.baseline["capture_sha256"])
        for name in ARRAY_NAMES:
            self.assertIsNot(again["arrays"][name], self.baseline["arrays"][name])
            self.assertEqual(
                again["arrays"][name].tobytes(), self.baseline["arrays"][name].tobytes()
            )
        self._assert_files_unchanged()

    def test_returned_objects_are_independent_copies(self) -> None:
        loaded = load_capture(self.root)
        loaded["manifest"]["grid_n"] = -1
        loaded["manifest"]["files"]["coverage.npz"] = "0" * 64
        loaded["scenarios"][0]["case_id"] = "mutated"
        loaded["scenarios"][0]["offline_bases"].append(999)
        loaded["scenarios"][0]["wind_mps"][0] = -99.0
        loaded["summary_rows"][0]["timely_cells"] = -1
        reloaded = load_capture(self.root)
        self.assertEqual(reloaded["manifest"], self.baseline["manifest"])
        self.assertEqual(reloaded["scenarios"], self.baseline["scenarios"])
        self.assertEqual(reloaded["summary_rows"], self.baseline["summary_rows"])
        self._assert_files_unchanged()

    def test_returned_arrays_are_read_only(self) -> None:
        loaded = load_capture(self.root)
        for name in ARRAY_NAMES:
            array = loaded["arrays"][name]
            with self.subTest(array=name):
                self.assertFalse(array.flags.writeable)
                with self.assertRaises(ValueError):
                    array.flat[0] = 1
        self._assert_files_unchanged()

    def test_mutated_arrays_do_not_leak_between_loads(self) -> None:
        loaded = load_capture(self.root)
        for name in ARRAY_NAMES:
            array = loaded["arrays"][name]
            array.setflags(write=True)
            array.flat[0] = array.flat[1] if array.size > 1 else 0
        reloaded = load_capture(self.root)
        for name in ARRAY_NAMES:
            self.assertFalse(reloaded["arrays"][name].flags.writeable)
            self.assertEqual(
                reloaded["arrays"][name].tobytes(),
                self.baseline["arrays"][name].tobytes(),
            )
        self._assert_files_unchanged()

    def test_fixture_and_source_files_unchanged_after_reads(self) -> None:
        for _ in range(2):
            loaded = load_capture(self.root)
            loaded["scenarios"].clear()
            loaded["summary_rows"].clear()
        self._assert_files_unchanged()

    def test_tampered_capture_components_are_rejected(self) -> None:
        originals = {
            path.name: path.read_bytes()
            for path in self.root.iterdir()
            if path.is_file()
        }
        try:
            for name in sorted(originals):
                with self.subTest(component=name):
                    path = self.root / name
                    path.write_bytes(_flip_byte(originals[name]))
                    with self.assertRaises((ValueError, OSError)):
                        load_capture(self.root)
                    path.write_bytes(originals[name])
                    recovered = load_capture(self.root)
                    self.assertEqual(recovered["manifest"], self.baseline["manifest"])
                    self.assertEqual(
                        recovered["capture_sha256"], self.baseline["capture_sha256"]
                    )
        finally:
            for name, data in originals.items():
                (self.root / name).write_bytes(data)
        self._assert_files_unchanged()

    def test_missing_capture_components_are_rejected(self) -> None:
        for name in CAPTURE_FILES:
            with self.subTest(component=name):
                path = self.root / name
                moved = self.root / (name + ".aside")
                path.rename(moved)
                try:
                    with self.assertRaises((ValueError, OSError)):
                        load_capture(self.root)
                finally:
                    moved.rename(path)
                recovered = load_capture(self.root)
                self.assertEqual(
                    recovered["capture_sha256"], self.baseline["capture_sha256"]
                )
        self._assert_files_unchanged()


class CoverageDataImmutabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "capture"
        create_fixture(cls.root)
        cls._before_fixture = _tree_digests(cls.root)
        cls._before_sources = _source_digests()
        cls.data = CoverageData(root=cls.root)
        cls.catalog = cls.data.catalog()
        cls.case_ids = [case["case_id"] for case in cls.catalog["cases"]]

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def _assert_files_unchanged(self) -> None:
        self.assertEqual(_tree_digests(self.root), self._before_fixture)
        self.assertEqual(_source_digests(), self._before_sources)

    def test_catalog_returns_json_safe_independent_copies(self) -> None:
        first = self.data.catalog()
        snapshot = json.loads(json.dumps(first, allow_nan=False))
        self.assertIsNot(first, self.catalog)
        first["capture_sha256"] = "0" * 64
        first["cases"][0]["case_id"] = "mutated"
        first["cases"][0]["offline_bases"].append(999)
        first["grid"]["order"] = "mutated"
        second = self.data.catalog()
        self.assertEqual(second, snapshot)
        json.dumps(second, allow_nan=False)
        self._assert_files_unchanged()

    def test_case_payloads_are_json_safe_independent_copies(self) -> None:
        for case_id in self.case_ids:
            with self.subTest(case_id=case_id):
                first = self.data.case(case_id)
                snapshot = json.loads(json.dumps(first, allow_nan=False))
                first["capture_sha256"] = "0" * 64
                first["case"]["case_id"] = "mutated"
                first["cells"][0]["outcome"] = "mutated"
                first["cells"][0]["index"] = -1
                second = self.data.case(case_id)
                self.assertEqual(second, snapshot)
                self.assertEqual(len(second["cells"]), 16)
        self._assert_files_unchanged()

    def test_repeated_adapter_calls_are_consistent(self) -> None:
        self.assertEqual(self.data.catalog(), self.catalog)
        for case_id in self.case_ids:
            self.assertEqual(self.data.case(case_id), self.data.case(case_id))
        self._assert_files_unchanged()

    def test_tampered_capture_never_returned_as_valid(self) -> None:
        case_id = self.case_ids[0]
        catalog = self.data.catalog()
        case = self.data.case(case_id)
        path = self.root / "coverage.npz"
        original = path.read_bytes()
        path.write_bytes(_flip_byte(original))
        try:
            with self.assertRaises((ValueError, OSError)):
                self.data.catalog()
            with self.assertRaises((ValueError, OSError)):
                self.data.case(case_id)
        finally:
            path.write_bytes(original)
        self.assertEqual(self.data.catalog(), catalog)
        self.assertEqual(self.data.case(case_id), case)
        self._assert_files_unchanged()


class CoverageServerImmutabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "capture"
        create_fixture(cls.root)
        cls._before_fixture = _tree_digests(cls.root)
        cls._before_sources = _source_digests()
        cls.case_ids = [case["case_id"] for case in load_capture(cls.root)["scenarios"]]
        cls.server = make_server(port=0, coverage_root=cls.root)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.host = host
        cls.port = port
        cls.base_url = f"http://{host}:{port}"
        status, _, body = cls.request("/api/coverage/catalog")
        if status != 200:
            raise AssertionError(f"coverage catalog returned HTTP {status}: {body!r}")
        cls.catalog_body = body
        cls.catalog = cls.parse_json(body)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls._tmp.cleanup()

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

    def assert_error_json(self, body):
        payload = self.parse_json(body)
        self.assertEqual(set(payload), {"error"})
        self.assertIsInstance(payload["error"], str)

    def _assert_files_unchanged(self) -> None:
        self.assertEqual(_tree_digests(self.root), self._before_fixture)
        self.assertEqual(_source_digests(), self._before_sources)

    def test_catalog_requests_are_byte_consistent(self) -> None:
        self.assertEqual(self.catalog["mode"], "coverage_catalog")
        self.assertRegex(self.catalog["capture_sha256"], r"^[0-9a-f]{64}$")
        for _ in range(2):
            status, _, body = self.request("/api/coverage/catalog")
            self.assertEqual(status, 200)
            self.assertEqual(body, self.catalog_body)
        self._assert_files_unchanged()

    def test_client_side_mutation_cannot_reach_server_state(self) -> None:
        parsed = dict(self.catalog)
        parsed["capture_sha256"] = "0" * 64
        parsed["cases"] = []
        parsed["grid_n"] = -1
        status, _, body = self.request("/api/coverage/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(body, self.catalog_body)
        self._assert_files_unchanged()

    def test_case_requests_are_consistent(self) -> None:
        bodies = {}
        for case_id in self.case_ids:
            with self.subTest(case_id=case_id):
                query = urllib.parse.urlencode({"case": case_id})
                first_status, _, first = self.request(f"/api/coverage?{query}")
                second_status, _, second = self.request(f"/api/coverage?{query}")
                self.assertEqual(first_status, 200)
                self.assertEqual(second_status, 200)
                self.assertEqual(first, second)
                payload = self.parse_json(first)
                self.assertEqual(payload["mode"], "coverage")
                self.assertEqual(
                    payload["capture_sha256"], self.catalog["capture_sha256"]
                )
                self.assertEqual(payload["case"]["case_id"], case_id)
                self.assertEqual(len(payload["cells"]), 16)
                payload["cells"][0]["outcome"] = "mutated"
                third_status, _, third = self.request(f"/api/coverage?{query}")
                self.assertEqual(third_status, 200)
                self.assertEqual(third, first)
                bodies[case_id] = first
        if len(bodies) == 2:
            self.assertNotEqual(bodies[self.case_ids[0]], bodies[self.case_ids[1]])
        self._assert_files_unchanged()

    def test_fresh_server_returns_identical_stored_values(self) -> None:
        fresh = make_server(port=0, coverage_root=self.root)
        thread = threading.Thread(target=fresh.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = fresh.server_address
            status, _, body = self.request(
                "/api/coverage/catalog", base_url=f"http://{host}:{port}"
            )
            self.assertEqual(status, 200)
            self.assertEqual(self.parse_json(body), self.catalog)
        finally:
            fresh.shutdown()
            fresh.server_close()
            thread.join(timeout=3)
        self._assert_files_unchanged()

    def test_tampered_capture_never_returned_as_valid(self) -> None:
        status, _, catalog_body = self.request("/api/coverage/catalog")
        self.assertEqual(status, 200)
        case_id = self.case_ids[0]
        query = urllib.parse.urlencode({"case": case_id})
        status, _, case_body = self.request(f"/api/coverage?{query}")
        self.assertEqual(status, 200)
        path = self.root / "summary.csv"
        original = path.read_bytes()
        path.write_bytes(_flip_byte(original))
        try:
            for target in ("/api/coverage/catalog", f"/api/coverage?{query}"):
                with self.subTest(target=target):
                    status, headers, body = self.request(target)
                    self.assertEqual(status, 503)
                    self.assertEqual(headers.get_content_type(), "application/json")
                    self.assert_error_json(body)
        finally:
            path.write_bytes(original)
        status, _, body = self.request("/api/coverage/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(body, catalog_body)
        status, _, body = self.request(f"/api/coverage?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(body, case_body)
        self._assert_files_unchanged()

    def test_missing_component_after_warm_read_fails_and_recovers(self) -> None:
        status, _, catalog_body = self.request("/api/coverage/catalog")
        self.assertEqual(status, 200)
        case_id = self.case_ids[0]
        query = urllib.parse.urlencode({"case": case_id})
        status, _, case_body = self.request(f"/api/coverage?{query}")
        self.assertEqual(status, 200)
        component = self.root / "coverage.npz"
        missing = component.with_name("coverage.npz.temporarily-missing")
        self.assertFalse(missing.exists())
        component.rename(missing)
        try:
            for target in ("/api/coverage/catalog", f"/api/coverage?{query}"):
                with self.subTest(target=target):
                    status, headers, body = self.request(target)
                    self.assertEqual(status, 503)
                    self.assertEqual(headers.get_content_type(), "application/json")
                    self.assert_error_json(body)
        finally:
            missing.rename(component)
        status, _, body = self.request("/api/coverage/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(body, catalog_body)
        status, _, body = self.request(f"/api/coverage?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(body, case_body)
        self._assert_files_unchanged()


if __name__ == "__main__":
    unittest.main()
