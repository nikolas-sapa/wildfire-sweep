import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import SplitResult, parse_qsl, unquote, urlsplit

from simulator_data import ExplorerData
from simulator_engine import run_mission

WEB_ROOT = Path(__file__).resolve().parent / "simulator_web"
STATIC_FILES = frozenset(
    {
        "index.html",
        "styles.css",
        "app.js",
        "state.js",
        "map.js",
        "controls.js",
        "mission.js",
        "replay.js",
        "evidence.js",
        "export.js",
        "session.js",
        "comparison.js",
        "comparison_data.js",
        "fonts/geist-latin.woff2",
    }
)
MAX_REQUEST_BYTES = 4096


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


class MissionRequestHandler(BaseHTTPRequestHandler):
    server: "MissionHTTPServer"

    def log_message(self, format_string: str, *args: object) -> None:
        return

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        if code == 501:
            self._method_error()
            return
        safe_messages = {
            400: "bad request",
            403: "local request required",
            404: "not found",
            405: "method not allowed",
            413: "request body too large",
            414: "request target too long",
            415: "application/json required",
        }
        self._error(code, safe_messages.get(code, "request failed"))

    def _send_bytes(
        self,
        status: int,
        content_type: str,
        body: bytes,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Security-Policy", self.server.content_security_policy)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, payload: object) -> None:
        try:
            body = json.dumps(
                payload,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            status = 500
            body = b'{"error":"internal server error"}'
        self._send_bytes(status, "application/json; charset=utf-8", body)

    def _error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    def _local_origin(self) -> bool:
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            self._error(403, "local Host required")
            return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1:
            self._error(403, "one Origin header required")
            return False
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            self._error(400, "one Content-Length header required")
            return False
        host = hosts[0]
        if origins:
            try:
                parsed = urlsplit(origins[0])
            except ValueError:
                self._error(403, "same-origin local request required")
                return False
            if (
                parsed.scheme.lower() != "http"
                or parsed.netloc.lower() != host.lower()
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.query
                or parsed.fragment
            ):
                self._error(403, "same-origin local request required")
                return False
        return True

    def _parsed_target(self) -> SplitResult | None:
        try:
            return urlsplit(self.path)
        except ValueError:
            return None

    def _decoded_path(self, parsed: SplitResult) -> str | None:
        path = unquote(parsed.path)
        if "\x00" in path or "\\" in path or ".." in PurePosixPath(path).parts:
            return None
        return path

    def _known_path(self, path: str) -> bool:
        routes = {"/", "/index.html", "/api/catalog", "/api/replay", "/api/mission"}
        static = path.startswith("/") and not path.startswith("//") and path[1:] in STATIC_FILES
        return path in routes or static

    def _method_error(self) -> None:
        if not self._local_origin():
            return
        parsed = self._parsed_target()
        if parsed is None:
            self._error(400, "invalid request target")
            return
        path = self._decoded_path(parsed)
        if path is None:
            self._error(404, "not found")
        elif self._known_path(path):
            self._error(405, "method not allowed")
        else:
            self._error(404, "not found")

    def _serve_static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            filename = "index.html"
        elif path.startswith("/") and not path.startswith("//"):
            filename = path[1:]
        else:
            self._error(404, "not found")
            return
        if filename not in STATIC_FILES:
            self._error(404, "not found")
            return
        target = self.server.web_root.joinpath(*PurePosixPath(filename).parts)
        current = self.server.web_root
        for part in PurePosixPath(filename).parts:
            current = current / part
            if current.is_symlink():
                self._error(404, "not found")
                return
        try:
            resolved = target.resolve(strict=True)
            resolved.relative_to(self.server.web_root)
        except (OSError, ValueError):
            self._error(404, "not found")
            return
        if not resolved.is_file():
            self._error(404, "not found")
            return
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if filename.endswith(".woff2"):
            content_type = "font/woff2"
        if content_type.startswith("text/") or content_type in (
            "application/javascript",
            "image/svg+xml",
        ):
            content_type = f"{content_type}; charset=utf-8"
        try:
            body = resolved.read_bytes()
        except OSError:
            self._error(404, "not found")
            return
        self._send_bytes(200, content_type, body)

    def _dispatch(self) -> None:
        if not self._local_origin():
            return
        parsed = self._parsed_target()
        if parsed is None:
            self._error(400, "invalid request target")
            return
        path = self._decoded_path(parsed)
        if path is None:
            self._error(404, "not found")
            return
        if self.command == "GET":
            if path == "/api/catalog":
                if parsed.query:
                    self._error(400, "catalog does not accept query parameters")
                    return
                try:
                    self._send_json(200, self.server.data.catalog())
                except Exception:
                    self._error(500, "internal server error")
                return
            if path == "/api/replay":
                try:
                    params = parse_qsl(
                        parsed.query,
                        keep_blank_values=True,
                        strict_parsing=True,
                    )
                except ValueError:
                    self._error(400, "invalid replay query")
                    return
                keys = [key for key, _ in params]
                if len(params) != 2 or set(keys) != {"case", "season"}:
                    self._error(400, "case and season must appear exactly once")
                    return
                values = dict(params)
                try:
                    season = int(values["season"])
                except ValueError:
                    self._error(400, "season must be an integer")
                    return
                try:
                    self._send_json(200, self.server.data.replay(values["case"], season))
                except (ValueError, TypeError, KeyError, IndexError) as error:
                    self._error(400, str(error) or "invalid replay request")
                except Exception:
                    self._error(500, "internal server error")
                return
            if path == "/api/mission":
                self._error(405, "method not allowed")
                return
            self._serve_static(path)
            return
        if self.command == "POST":
            if path != "/api/mission":
                if self._known_path(path):
                    self._error(405, "method not allowed")
                else:
                    self._error(404, "not found")
                return
            if parsed.query or parsed.fragment:
                self._error(400, "mission does not accept query parameters")
                return
            self._post_mission()
            return
        self._error(405, "method not allowed")

    def _post_mission(self) -> None:
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(415, "application/json required")
            return
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            self._error(400, "Content-Length required")
            return
        try:
            length = int(raw_length)
        except ValueError:
            self._error(400, "invalid Content-Length")
            return
        if length < 1:
            self._error(400, "empty JSON body")
            return
        if length > MAX_REQUEST_BYTES:
            self._error(413, "request body too large")
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._error(400, "incomplete request body")
            return
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            self._error(400, "invalid JSON body")
            return
        if not isinstance(payload, dict):
            self._error(400, "JSON body must be an object")
            return
        try:
            self._send_json(200, run_mission(payload))
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            self._error(400, str(error) or "invalid mission request")
        except Exception:
            self._error(500, "internal server error")

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._method_error()

    def do_PUT(self) -> None:
        self._method_error()

    def do_DELETE(self) -> None:
        self._method_error()

    def do_PATCH(self) -> None:
        self._method_error()

    def do_OPTIONS(self) -> None:
        self._method_error()


class MissionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    content_security_policy = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "font-src 'self'; img-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )

    def __init__(
        self,
        server_address: tuple[str, int],
        data: ExplorerData | None,
        web_root: str | Path,
    ) -> None:
        self.data = data if data is not None else ExplorerData()
        self.web_root = Path(web_root).resolve()
        super().__init__(server_address, MissionRequestHandler)


def make_server(
    port: int = 0,
    data: ExplorerData | None = None,
    web_root: str | Path = WEB_ROOT,
) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return MissionHTTPServer(("127.0.0.1", port), data, web_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--capture", type=Path)
    arguments = parser.parse_args()
    if not 0 <= arguments.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    data = ExplorerData(capture_dir=arguments.capture) if arguments.capture else None
    try:
        with make_server(arguments.port, data) as server:
            print(f"Mission Lab listening at http://127.0.0.1:{server.server_address[1]}", flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
