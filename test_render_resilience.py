import ast
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import render_resilience

ROOT = Path(__file__).parent
RUN_DIR = ROOT / "research_results" / "2026-11-09-resilience"
FORBIDDEN_IMPORTS = {"resilience", "research", "robustness", "sweep", "factorial"}
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(PNG_MAGIC):
        raise AssertionError(f"{path.name} lacks PNG magic bytes")
    if data[12:16] != b"IHDR":
        raise AssertionError(f"{path.name} lacks an IHDR chunk")
    return struct.unpack(">II", data[16:24])


class RenderResilienceTests(unittest.TestCase):
    def test_help_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "render_resilience.py", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("--run", result.stdout)
        self.assertIn("--output", result.stdout)

    def test_no_scientific_script_imports(self) -> None:
        tree = ast.parse(
            (ROOT / "render_resilience.py").read_text(encoding="utf-8")
        )
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse(imported & FORBIDDEN_IMPORTS)

    def test_real_capture_renders_verified_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "figures"
            result = render_resilience.render_capture(RUN_DIR, output)
            self.assertEqual(result, output)
            self.assertTrue(output.is_dir())
            self.assertEqual(png_dimensions(output / "service.png"), (2160, 1260))
            self.assertEqual(png_dimensions(output / "sites.png"), (1800, 1800))
            manifest = json.loads((output / "manifest.json").read_bytes())
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(
                manifest["input_manifest_sha256"],
                hashlib.sha256(
                    (RUN_DIR / "manifest.json").read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                manifest["source_sha256"]["render_resilience.py"],
                hashlib.sha256(
                    (ROOT / "render_resilience.py").read_bytes()
                ).hexdigest(),
            )
            self.assertEqual(
                set(manifest["artifact_sha256"]), {"service.png", "sites.png"}
            )
            for name, digest in manifest["artifact_sha256"].items():
                self.assertEqual(
                    digest,
                    hashlib.sha256((output / name).read_bytes()).hexdigest(),
                )
            self.assertTrue(manifest["limitations"])
            with self.assertRaises(FileExistsError):
                render_resilience.render_capture(RUN_DIR, output)

    def test_existing_output_fails_before_input_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing_run = Path(directory) / "missing-run"
            output = Path(directory) / "figures"
            output.mkdir()
            sentinel = output / "sentinel.txt"
            sentinel.write_bytes(b"keep")
            with self.assertRaises(FileExistsError):
                render_resilience.render_capture(missing_run, output)
            self.assertEqual(sentinel.read_bytes(), b"keep")
            dangling = Path(directory) / "dangling"
            os.symlink(Path(directory) / "absent-target", dangling)
            with self.assertRaises(FileExistsError):
                render_resilience.render_capture(missing_run, dangling)

    def test_input_mutation_during_plot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "run"
            shutil.copytree(RUN_DIR, copied)
            target = copied / "summary.csv"
            real_service_png = render_resilience._service_png

            def patched(*args, **kwargs):
                with target.open("ab") as handle:
                    handle.write(b"X")
                return real_service_png(*args, **kwargs)

            output = Path(directory) / "figures"
            with mock.patch.object(
                render_resilience, "_service_png", patched
            ), self.assertRaises(ValueError):
                render_resilience.render_capture(copied, output)
            self.assertFalse(output.exists())

    def test_source_mutation_during_plot_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_copy = Path(directory) / "render_resilience_copy.py"
            shutil.copyfile(ROOT / "render_resilience.py", source_copy)
            real_sites_png = render_resilience._sites_png

            def patched(*args, **kwargs):
                image = real_sites_png(*args, **kwargs)
                with source_copy.open("ab") as handle:
                    handle.write(b"\n")
                return image

            output = Path(directory) / "figures"
            with mock.patch.object(
                render_resilience, "__file__", str(source_copy)
            ), mock.patch.object(
                render_resilience, "_sites_png", patched
            ), self.assertRaises(ValueError):
                render_resilience.render_capture(RUN_DIR, output)
            self.assertFalse(output.exists())

    def test_tampered_capture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            copied = Path(directory) / "run"
            shutil.copytree(RUN_DIR, copied)
            with (copied / "summary.csv").open("ab") as handle:
                handle.write(b"X")
            output = Path(directory) / "figures"
            with self.assertRaises(ValueError):
                render_resilience.render_capture(copied, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
