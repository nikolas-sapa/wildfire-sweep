import re
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from simulator_server import STATIC_FILES, WEB_ROOT


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.modes: set[str] = set()
        self.panels: set[str] = set()
        self.module_scripts: set[str] = set()
        self.stylesheets: set[str] = set()
        self.inline_handlers: list[str] = []
        self.live_regions = 0
        self.resource_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if values.get("data-mode"):
            self.modes.add(values["data-mode"])
        if values.get("data-panel"):
            self.panels.add(values["data-panel"])
        if tag == "script" and values.get("type") == "module":
            self.module_scripts.add(values.get("src", ""))
        if tag == "link" and values.get("rel") == "stylesheet":
            self.stylesheets.add(values.get("href", ""))
        if tag == "script" and values.get("src"):
            self.resource_urls.append(values["src"])
        if tag == "link" and values.get("rel") in {"stylesheet", "preload", "modulepreload"}:
            self.resource_urls.append(values.get("href", ""))
        if tag in {"img", "iframe", "audio", "video", "source"} and values.get("src"):
            self.resource_urls.append(values["src"])
        if values.get("aria-live"):
            self.live_regions += 1
        self.inline_handlers.extend(
            name for name in values if name.lower().startswith("on")
        )


def _is_network_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme in {"http", "https"} or bool(parsed.netloc)


def _has_remote_dependency(source: str, suffix: str) -> bool:
    remote = r"""(?:https?:)?//"""
    if suffix == ".css":
        return bool(
            re.search(rf"""@import\s+(?:url\(\s*)?["']?\s*{remote}""", source, re.I)
            or re.search(rf"""url\(\s*["']?\s*{remote}""", source, re.I)
        )
    javascript_patterns = (
        rf"""\b(?:fetch|importScripts|WebSocket|EventSource)\s*\(\s*["'`]\s*{remote}""",
        rf"""\bnew\s+(?:Worker|SharedWorker)\s*\(\s*["'`]\s*{remote}""",
        rf"""\bfrom\s*["'`]\s*{remote}""",
        rf"""\bimport\s*(?:\(\s*)?["'`]\s*{remote}""",
        rf"""\.open\s*\(\s*["'][A-Z]+\s*["']\s*,\s*["'`]\s*{remote}""",
    )
    return any(re.search(pattern, source, re.I) for pattern in javascript_patterns)


class SimulatorAssetTests(unittest.TestCase):
    def test_page_structure_and_local_module_references(self) -> None:
        parser = PageParser()
        parser.feed((WEB_ROOT / "index.html").read_text())
        self.assertTrue(
            {
                "controls",
                "map",
                "mission-results",
                "replay-controls",
                "evidence",
                "export",
                "status",
            } <= parser.ids
        )
        self.assertEqual(parser.modes, {"mission", "replay"})
        self.assertEqual(parser.panels, {"mission", "replay"})
        self.assertEqual(parser.module_scripts, {"app.js"})
        self.assertEqual(parser.stylesheets, {"styles.css"})
        self.assertGreaterEqual(parser.live_regions, 1)
        self.assertEqual(parser.inline_handlers, [])

    def test_static_whitelist_matches_local_assets(self) -> None:
        expected = {
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
        self.assertEqual(set(STATIC_FILES), expected)
        for name in expected:
            with self.subTest(asset=name):
                self.assertTrue((WEB_ROOT / name).is_file())

    def test_module_imports_resolve_inside_whitelist(self) -> None:
        pattern = re.compile(
            r"""(?:\bfrom\s*|\bimport\s*(?:\(\s*)?)["']([^"']+\.js)["']"""
        )
        root = WEB_ROOT.resolve()
        for name in (asset for asset in STATIC_FILES if asset.endswith(".js")):
            source = (WEB_ROOT / name).read_text()
            for reference in pattern.findall(source):
                parsed = urlsplit(reference)
                self.assertEqual(parsed.scheme, "")
                self.assertEqual(parsed.netloc, "")
                target = ((WEB_ROOT / name).parent / parsed.path).resolve()
                self.assertTrue(target.is_relative_to(root), reference)
                relative = target.relative_to(root).as_posix()
                self.assertIn(relative, STATIC_FILES)
                self.assertTrue(target.is_file())

    def test_web_assets_are_self_contained(self) -> None:
        parser = PageParser()
        parser.feed((WEB_ROOT / "index.html").read_text())
        self.assertFalse(any(_is_network_url(url) for url in parser.resource_urls))
        for path in WEB_ROOT.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in {".js", ".css"}:
                self.assertFalse(
                    _has_remote_dependency(path.read_text(), path.suffix),
                    path.name,
                )

    def test_network_guard_ignores_namespace_and_plain_source_links(self) -> None:
        self.assertTrue(_has_remote_dependency('fetch("https://cdn.example/a.js")', ".js"))
        self.assertTrue(_has_remote_dependency('@import url("https://cdn.example/a.css");', ".css"))
        self.assertFalse(
            _has_remote_dependency(
                'const SVG_NS = "http://www.w3.org/2000/svg";',
                ".js",
            )
        )
        self.assertFalse(
            _has_remote_dependency(
                'anchor.href = "https://github.com/example/research";',
                ".js",
            )
        )
