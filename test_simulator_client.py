import contextlib
import io
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from simulator_client import main
from simulator_server import make_server


class SimulatorClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = make_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def _run_client(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["--url", self.base_url, *arguments])
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_catalog_command_returns_server_json(self) -> None:
        exit_code, output, error = self._run_client(["catalog"])
        payload = json.loads(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(payload["mode"], "catalog")

    def test_mission_command_merges_catalog_defaults(self) -> None:
        exit_code, output, error = self._run_client(
            ["mission", "--point-km", "10", "10"]
        )
        payload = json.loads(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(payload["mode"], "mission")
        self.assertEqual(payload["inputs"]["point_km"], [10.0, 10.0])

    def test_replay_command_reads_captured_season(self) -> None:
        catalog_code, catalog_output, catalog_error = self._run_client(["catalog"])
        self.assertEqual((catalog_code, catalog_error), (0, ""))
        case_id = json.loads(catalog_output)["study"]["cases"][0]["case_id"]
        exit_code, output, error = self._run_client(
            ["replay", "--case", case_id, "--season", "0"]
        )
        payload = json.loads(output)
        self.assertEqual(exit_code, 0)
        self.assertEqual(error, "")
        self.assertEqual(payload["mode"], "replay")
        self.assertEqual(payload["case_id"], case_id)
        self.assertEqual(payload["season"], 0)

    def test_rejects_nonlocal_url_without_request(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(["--url", "https://example.com", "catalog"])
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("localhost", stderr.getvalue())

    def test_http_error_exits_without_traceback(self) -> None:
        exit_code, output, error = self._run_client(
            ["mission", "--point-km", "1000", "1000"]
        )
        self.assertEqual(exit_code, 2)
        self.assertEqual(output, "")
        self.assertNotIn("Traceback", error)
        self.assertIn("error", error.lower())

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
        redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
        redirect_thread.start()
        host, port = redirect.server_address
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["--url", f"http://{host}:{port}", "catalog"])
        finally:
            redirect.shutdown()
            redirect.server_close()
            redirect_thread.join(timeout=3)
            target.shutdown()
            target.server_close()
            target_thread.join(timeout=3)
        self.assertEqual(TargetHandler.requests, 0)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("redirect", stderr.getvalue().lower())

    def test_nonfinite_response_exits_two_without_partial_json(self) -> None:
        class NonfiniteHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                body = b'{"mode":"catalog","overflow":1e999}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format_string: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), NonfiniteHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["--url", f"http://{host}:{port}", "catalog"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("non-finite", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
