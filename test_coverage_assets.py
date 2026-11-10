import re
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import urljoin, urlsplit

from coverage_test_fixture import create_fixture
from simulator_server import STATIC_FILES, WEB_ROOT as SIMULATOR_WEB_ROOT, make_server
from test_simulator_assets import _has_remote_dependency

ROOT = Path(__file__).resolve().parent
COVERAGE_WEB = ROOT / "coverage_web"
ATLAS_BASENAMES = frozenset(
    {
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
    }
)
REQUIRED_IDS = frozenset(
    {
        "cov-controls",
        "cov-map",
        "cov-compare",
        "cov-table",
        "cov-details",
        "cov-legend",
        "cov-export",
        "cov-session",
        "cov-status",
    }
)
MIME_BY_SUFFIX = {
    ".html": {"text/html"},
    ".css": {"text/css"},
    ".js": {"text/javascript", "application/javascript"},
    ".woff2": {"font/woff2"},
}
TEXT_SUFFIXES = {".html", ".css", ".js"}
HTML_SINKS = re.compile(
    r"""\b(?:innerHTML|outerHTML)\b|\binsertAdjacentHTML\b"""
    r"""|\bdocument\s*\.\s*writeln?\s*\(|\beval\s*\(|\bnew\s+Function\b"""
    r"""|\b(?:localStorage|sessionStorage|indexedDB)\b"""
)
IMPORT_REFERENCES = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)["']([^"']+\.js)["']"""
)
CSS_REFERENCES = re.compile(
    r"""@import\s+(?:url\(\s*)?["']([^"']+)["']|url\(\s*["']?([^"')]+?)["']?\s*\)"""
)


class AtlasPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.module_scripts: set[str] = set()
        self.stylesheets: set[str] = set()
        self.rejected_scripts: list[str] = []
        self.style_elements = 0
        self.inline_style_attrs = 0
        self.inline_handlers: list[str] = []
        self.resource_urls: list[str] = []
        self.anchor_hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "script":
            src = values.get("src")
            if src and (values.get("type") or "").lower() == "module":
                self.module_scripts.add(src)
                self.resource_urls.append(src)
            else:
                self.rejected_scripts.append(src or "")
        if tag == "style":
            self.style_elements += 1
        if tag == "link" and values.get("href"):
            href = values["href"]
            rels = set((values.get("rel") or "").lower().split())
            if "stylesheet" in rels:
                self.stylesheets.add(href)
            self.resource_urls.append(href)
        if tag in {"img", "iframe", "audio", "video", "source"} and values.get("src"):
            self.resource_urls.append(values["src"])
        if tag == "a" and values.get("href") is not None:
            self.anchor_hrefs.append(values["href"])
        if values.get("style") is not None:
            self.inline_style_attrs += 1
        self.inline_handlers.extend(
            name for name in values if name.lower().startswith("on")
        )


def _local_reference(value: str) -> bool:
    if not isinstance(value, str) or "\\" in value or "\x00" in value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme == "" and parsed.netloc == "" and not value.startswith("//")


def _page_basename(reference: str) -> str:
    path = urlsplit(reference).path
    if path.startswith("/coverage/"):
        path = path[len("/coverage/"):]
    while path.startswith("./"):
        path = path[2:]
    return path


def _css_references(source: str) -> list[str]:
    references = []
    for imported, raw_url in CSS_REFERENCES.findall(source):
        reference = (imported or raw_url).strip()
        if reference:
            references.append(reference)
    return references


class CoverageAssetFileTests(unittest.TestCase):
    @staticmethod
    def parse_page() -> AtlasPageParser:
        parser = AtlasPageParser()
        parser.feed((COVERAGE_WEB / "index.html").read_text(encoding="utf-8"))
        parser.close()
        return parser

    def test_page_declares_required_ids_and_module_shape(self) -> None:
        parser = self.parse_page()
        self.assertTrue(REQUIRED_IDS <= parser.ids)
        self.assertEqual(
            {_page_basename(ref) for ref in parser.module_scripts}, {"app.js"}
        )
        self.assertEqual(
            {_page_basename(ref) for ref in parser.stylesheets}, {"styles.css"}
        )
        self.assertEqual(parser.rejected_scripts, [])
        self.assertEqual(parser.style_elements, 0)
        self.assertEqual(parser.inline_style_attrs, 0)
        self.assertEqual(parser.inline_handlers, [])
        self.assertIn("/", parser.anchor_hrefs)

    def test_exact_allowlist_files_exist(self) -> None:
        for name in sorted(ATLAS_BASENAMES):
            with self.subTest(asset=name):
                self.assertTrue((COVERAGE_WEB / name).is_file(), name)

    def test_module_imports_stay_inside_allowlist(self) -> None:
        root = COVERAGE_WEB.resolve()
        for name in sorted(asset for asset in ATLAS_BASENAMES if asset.endswith(".js")):
            source = (COVERAGE_WEB / name).read_text(encoding="utf-8")
            for reference in IMPORT_REFERENCES.findall(source):
                parsed = urlsplit(reference)
                self.assertEqual(parsed.scheme, "")
                self.assertEqual(parsed.netloc, "")
                target = (root / parsed.path).resolve()
                self.assertTrue(target.is_relative_to(root), reference)
                relative = target.relative_to(root).as_posix()
                self.assertIn(relative, ATLAS_BASENAMES, reference)
                self.assertTrue(target.is_file(), reference)

    def test_assets_have_no_remote_or_html_sinks(self) -> None:
        parser = self.parse_page()
        references = (
            parser.resource_urls
            + parser.anchor_hrefs
            + list(parser.module_scripts)
            + list(parser.stylesheets)
        )
        for reference in references:
            with self.subTest(reference=reference):
                self.assertTrue(_local_reference(reference), reference)
        for path in sorted(COVERAGE_WEB.rglob("*")):
            if not path.is_file() or path.suffix not in {".js", ".css", ".mjs"}:
                continue
            source = path.read_text(encoding="utf-8")
            with self.subTest(asset=path.name):
                self.assertFalse(
                    _has_remote_dependency(source, path.suffix), path.name
                )
        for name in sorted(asset for asset in ATLAS_BASENAMES if asset.endswith(".js")):
            source = (COVERAGE_WEB / name).read_text(encoding="utf-8")
            with self.subTest(asset=name):
                self.assertIsNone(HTML_SINKS.search(source), name)

    def test_local_geist_font_is_referenced(self) -> None:
        parser = self.parse_page()
        references = list(parser.resource_urls)
        for name in sorted(asset for asset in ATLAS_BASENAMES if asset.endswith(".css")):
            references += _css_references(
                (COVERAGE_WEB / name).read_text(encoding="utf-8")
            )
        fonts = [ref for ref in references if "geist-latin.woff2" in ref]
        self.assertTrue(fonts, "expected a local geist-latin.woff2 reference")
        for reference in fonts:
            with self.subTest(reference=reference):
                self.assertTrue(_local_reference(reference), reference)

    def test_guards_detect_remote_and_html_sinks(self) -> None:
        self.assertTrue(
            _has_remote_dependency('fetch("https://cdn.example/a.js")', ".js")
        )
        self.assertTrue(
            _has_remote_dependency(
                'import x from "https://cdn.example/m.js"', ".js"
            )
        )
        self.assertTrue(
            _has_remote_dependency(
                '@import url("https://cdn.example/a.css");', ".css"
            )
        )
        self.assertFalse(
            _has_remote_dependency('import {x} from "./app.js";', ".js")
        )
        self.assertFalse(
            _has_remote_dependency(
                'const NS = "http://www.w3.org/2000/svg";', ".js"
            )
        )
        self.assertIsNotNone(HTML_SINKS.search("node.innerHTML = raw"))
        self.assertIsNone(HTML_SINKS.search("node.textContent = raw"))


class CoverageAssetServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = TemporaryDirectory()
        try:
            cls.fixture_root = create_fixture(Path(cls.temporary.name) / "capture")
            cls.server = make_server(port=0, coverage_root=cls.fixture_root)
        except Exception:
            cls.temporary.cleanup()
            raise
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host, cls.port = cls.server.server_address
        cls.base_url = f"http://{cls.host}:{cls.port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temporary.cleanup()

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

    def assert_served(self, path):
        status, headers, body = self.request(path)
        self.assertEqual(status, 200, path)
        suffix = PurePosixPath(urlsplit(path).path).suffix
        expected = MIME_BY_SUFFIX.get(suffix)
        if expected is not None:
            self.assertIn(headers.get_content_type(), expected, path)
        if suffix in TEXT_SUFFIXES:
            self.assertEqual(headers.get_content_charset(), "utf-8", path)
        return status, headers, body

    def test_index_routes_and_exact_allowlist_are_served(self) -> None:
        bodies = []
        for path in ("/coverage", "/coverage/"):
            status, headers, body = self.request(path)
            with self.subTest(path=path):
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
            bodies.append(body)
        status, headers, body = self.assert_served("/coverage/index.html")
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[0], body)
        self.assertEqual(bodies[0], (COVERAGE_WEB / "index.html").read_bytes())
        for name in sorted(ATLAS_BASENAMES - {"index.html"}):
            with self.subTest(asset=name):
                _, _, body = self.assert_served(f"/coverage/{name}")
                self.assertEqual(body, (COVERAGE_WEB / name).read_bytes())

    def test_page_and_css_references_serve_with_correct_mime(self) -> None:
        parser = CoverageAssetFileTests.parse_page()
        references = set(parser.resource_urls) | parser.module_scripts | parser.stylesheets
        for reference in sorted(references):
            resolved = urljoin("/coverage/index.html", reference)
            with self.subTest(reference=reference):
                self.assertTrue(_local_reference(reference), reference)
                self.assert_served(resolved)
        for name in sorted(asset for asset in ATLAS_BASENAMES if asset.endswith(".css")):
            source = (COVERAGE_WEB / name).read_text(encoding="utf-8")
            for reference in sorted(set(_css_references(source))):
                if reference.startswith(("data:", "#")):
                    continue
                resolved = urljoin(f"/coverage/{name}", reference)
                with self.subTest(reference=reference):
                    self.assertTrue(_local_reference(resolved), reference)
                    self.assert_served(resolved)

    def test_unlisted_archive_test_and_traversal_paths_fail(self) -> None:
        rejected = [
            "/coverage/tests/",
            "/coverage/tests/session.test.mjs",
            "/coverage/tests/state.test.mjs",
            "/coverage/tests/api.test.mjs",
            "/coverage/tests/data_contract.test.mjs",
            "/coverage/coverage.npz",
            "/coverage/manifest.json",
            "/coverage/scenarios.json",
            "/coverage/summary.csv",
            "/coverage/fonts/geist-latin.woff2",
            "/coverage/fonts/",
            "/coverage/README.md",
            "/coverage/AGENTS.md",
            "/coverage/index.htm",
            "/coverage/app.css",
            "/coverage/api.py",
            "/coverage/nested/deep.js",
            "/coverage/subdir/",
            "/coverage/app.js/",
            "/coverage/app.js/extra",
            "/coverage/%2e%2e/simulator_web/index.html",
            "/coverage/%2e%2e/index.html",
            "/coverage/%2e%2e",
            "/coverage/%2e%2e%2fsimulator_web%2findex.html",
            "/coverage/..%2findex.html",
            "/coverage/%2e%2e%2fcoverage_capture.py",
            "/coverage_web/index.html",
            "/test_coverage_assets.py",
            "/coverage_engine.py",
            "/coverage.npz",
            "/manifest.json",
            "/scenarios.json",
            "/summary.csv",
        ]
        for path in rejected:
            with self.subTest(path=path):
                status, _, _ = self.request(path)
                self.assertEqual(status, 404, path)
        for path in sorted(COVERAGE_WEB.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(COVERAGE_WEB).as_posix()
            if relative in ATLAS_BASENAMES:
                continue
            with self.subTest(path=relative):
                status, _, _ = self.request(f"/coverage/{relative}")
                self.assertEqual(status, 404, relative)

    def test_local_origin_and_method_guards_apply(self) -> None:
        status, _, _ = self.request(
            "/coverage/index.html", headers={"Host": "not-local.example"}
        )
        self.assertEqual(status, 403)
        for path in ("/coverage", "/coverage/index.html"):
            status, _, _ = self.request(
                path,
                "POST",
                b"{}",
                {"Content-Type": "application/json"},
            )
            with self.subTest(path=path):
                self.assertEqual(status, 405)

    def test_local_font_url_served(self) -> None:
        status, headers, body = self.request("/fonts/geist-latin.woff2")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "font/woff2")
        self.assertEqual(body[:4], b"wOF2")

    def test_favicon_route_is_local_and_secure(self) -> None:
        status, headers, body = self.request("/favicon.ico")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get_content_type(), "image/svg+xml")
        svg = ET.fromstring(body)
        self.assertEqual(svg.tag, "{http://www.w3.org/2000/svg}svg")
        self.assertEqual(svg[0].tag, "{http://www.w3.org/2000/svg}rect")
        self.assertEqual(svg[0].get("fill"), "#006bff")
        self.assertEqual(svg[1].tag, "{http://www.w3.org/2000/svg}path")
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn(
            "default-src 'self'",
            headers.get("Content-Security-Policy", ""),
        )

        status, _, _ = self.request(
            "/favicon.ico",
            headers={"Host": "evil.example"},
        )
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "/favicon.ico",
            "POST",
            b"",
            {"Content-Type": "application/json"},
        )
        self.assertEqual(status, 405)

    def test_existing_root_ui_still_served(self) -> None:
        for path in ("/", "/index.html"):
            status, headers, _ = self.request(path)
            with self.subTest(path=path):
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
        for name in sorted(STATIC_FILES):
            with self.subTest(asset=name):
                self.assert_served(f"/{name}")
        self.assertTrue(
            (SIMULATOR_WEB_ROOT / "fonts/geist-latin.woff2").is_file()
        )


if __name__ == "__main__":
    unittest.main()
