import ast
import hashlib
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import capture_integrity

REPO_ROOT = Path(__file__).resolve().parent
MANIFEST_LIMIT = 8388608


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def envelope(inventory, **overrides):
    doc = {"schema_version": 1, "status": "complete",
           "artifact_sha256": inventory}
    doc.update(overrides)
    return json.dumps(doc).encode()


def cloned_stat(info, **changes):
    fields = {"st_mode": info.st_mode, "st_dev": info.st_dev,
              "st_ino": info.st_ino, "st_size": info.st_size,
              "st_mtime_ns": info.st_mtime_ns, "st_ctime_ns": info.st_ctime_ns,
              "st_atime": info.st_atime}
    fields.update(changes)
    return SimpleNamespace(**fields)


class CaptureIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        self.manifest = self.root / "manifest.json"

    def tearDown(self):
        self.workspace.cleanup()

    def _capture(self, files):
        for name, data in files.items():
            (self.root / name).write_bytes(data)
        inventory = {name: sha256(data) for name, data in files.items()}
        self.manifest.write_bytes(envelope(inventory))
        return inventory

    def _verify(self):
        return capture_integrity.verify_capture(str(self.root))

    def _rejections(self, cases):
        for index, document in enumerate(cases):
            self.manifest.write_bytes(document)
            before = self.manifest.read_bytes()
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    self._verify()
                self.assertEqual(self.manifest.read_bytes(), before)

    def test_three_artifacts(self):
        files = {
            "zeta.txt": b"offline capture payload\n" * 8,
            "alpha.bin": bytes(range(256)) * 4,
            "empty.dat": b"",
        }
        inventory = self._capture(files)
        manifest_before = self.manifest.read_bytes()
        receipt = self._verify()
        self.assertEqual(set(receipt), {"schema_version", "status",
                                        "manifest_sha256", "artifact_sha256",
                                        "limitations"})
        self.assertEqual(receipt["schema_version"], 1)
        self.assertEqual(receipt["status"], "artifact_checksums_verified")
        self.assertEqual(receipt["manifest_sha256"], sha256(manifest_before))
        self.assertEqual(receipt["artifact_sha256"], inventory)
        self.assertEqual(list(receipt["artifact_sha256"]), sorted(files))
        self.assertEqual(receipt["limitations"], capture_integrity.LIMITATIONS)
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        for name, data in files.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_manifest_contract(self):
        (self.root / "ok.bin").write_bytes(b"payload")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(OSError):
            capture_integrity.verify_capture(str(empty))
        good = sha256(b"payload")
        cases = [b"{ not json", b"[1, 2, 3]"]
        cases += [envelope({"ok.bin": good}, schema_version=v)
                  for v in (True, 0, 2, "1", 1.0)]
        cases += [envelope({"ok.bin": good}, status=s)
                  for s in ("pending", 1, True)]
        cases += [envelope(inv) for inv in ({}, ["ok.bin"], "x", 0)]
        cases += [envelope({name: good}) for name in ("../x", "manifest.json")]
        cases += [envelope({"ok.bin": d})
                  for d in ("0" * 63, "0" * 65, "A" * 64, "g" * 64, 42, True)]
        for key in ("status", "artifact_sha256"):
            doc = json.loads(envelope({"ok.bin": good}))
            del doc[key]
            cases.append(json.dumps(doc).encode())
        self._rejections(cases)

    def test_strict_json(self):
        self._capture({"ok.bin": b"payload"})
        d = sha256(b"payload").encode()
        head = b'{"schema_version": 1, "status": "complete", "artifact_sha256": {"ok.bin": "%s"' % d
        cases = [
            b'{"schema_version": 1, "schema_version": 1, ' + head[1:] + b"}}",
            head + b', "ok.bin": "%s"}}' % d,
            head + b'}, "extra": NaN}',
            head + b'}, "extra": Infinity}',
            head + b'}, "extra": -Infinity}',
            head + b'}, "extra": 1e999}',
        ]
        self._rejections(cases)

    def test_deep_json(self):
        self._capture({"ok.bin": b"payload"})
        prefix = (b'{"schema_version": 1, "status": "complete", '
                  b'"artifact_sha256": {"ok.bin": "%s"}, "extra": '
                  % sha256(b"payload").encode())
        document = prefix + b"[" * 100000 + b"]" * 100000 + b"}"
        self._rejections([document])

    def test_manifest_size(self):
        data = b"\x00\xff" * 4096
        (self.root / "blob.bin").write_bytes(data)
        base = envelope({"blob.bin": sha256(data)})
        self.assertLess(len(base), MANIFEST_LIMIT)
        padded = base + b" " * (MANIFEST_LIMIT - len(base))
        self.manifest.write_bytes(padded)
        receipt = self._verify()
        self.assertEqual(receipt["manifest_sha256"], sha256(padded))
        self.assertEqual(receipt["artifact_sha256"], {"blob.bin": sha256(data)})
        self.manifest.write_bytes(base + b" " * (MANIFEST_LIMIT + 1 - len(base)))
        with self.assertRaises(ValueError):
            self._verify()

    def test_artifact_names(self):
        (self.root / "ok.bin").write_bytes(b"payload")
        bad_names = [
            "", ".", "..", "../x", "/abs/path", "a\\b", "bad\x00name",
            "manifest.json", "has space.txt", ".hidden", "_lead",
            "caf\u00e9.bin", "a" * 256,
        ]
        good = sha256(b"payload")
        self._rejections([envelope({name: good}) for name in bad_names])
        self.manifest.write_bytes(envelope({"a" * 255: good}))
        with self.assertRaises(OSError):
            self._verify()

    def test_nonregular_and_symlink_inputs(self):
        payload = b"payload"
        digest_ok = sha256(payload)
        self._capture({"ok.bin": payload})
        with tempfile.TemporaryDirectory() as tmp:
            alias = Path(tmp) / "alias"
            os.symlink(self.root, alias)
            receipt = capture_integrity.verify_capture(str(alias))
        self.assertEqual(receipt["status"], "artifact_checksums_verified")
        self.manifest.write_bytes(envelope({"missing.bin": digest_ok}))
        with self.assertRaises(OSError):
            self._verify()
        (self.root / "dir.bin").mkdir()
        self.manifest.write_bytes(envelope({"dir.bin": digest_ok}))
        with self.assertRaises(ValueError):
            self._verify()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "ok.bin").write_bytes(payload)
            (tmp / "real.json").write_bytes(envelope({"ok.bin": digest_ok}))
            os.symlink("real.json", tmp / "manifest.json")
            with self.assertRaises(OSError):
                capture_integrity.verify_capture(str(tmp))
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "target.bin").write_bytes(payload)
            os.symlink("target.bin", tmp / "alias.bin")
            (tmp / "manifest.json").write_bytes(envelope({"alias.bin": digest_ok}))
            with self.assertRaises(OSError):
                capture_integrity.verify_capture(str(tmp))
        os.mkfifo(self.root / "pipe.bin")
        self.manifest.write_bytes(envelope({"pipe.bin": digest_ok}))
        outcome = {}

        def attempt():
            try:
                self._verify()
            except BaseException as error:
                outcome["error"] = error

        worker = threading.Thread(target=attempt, daemon=True)
        worker.start()
        worker.join(10)
        self.assertFalse(worker.is_alive(), "verification blocked on FIFO")
        self.assertIsInstance(outcome.get("error"), ValueError)

    def test_tampering(self):
        files = {"first.bin": b"\x11" * 64, "second.bin": b"\x22" * 64}
        self._capture(files)
        manifest_before = self.manifest.read_bytes()
        tampered = bytearray(files["second.bin"])
        tampered[10] ^= 0xFF
        (self.root / "second.bin").write_bytes(bytes(tampered))
        with self.assertRaises(ValueError):
            self._verify()
        self.assertEqual(self.manifest.read_bytes(), manifest_before)

    def test_mutation_and_descriptor_cleanup(self):
        original = {"a.bin": b"\x55" * 128, "b.bin": b"\x66" * 128}
        self._capture(original)
        opened, closed = [], []
        real_open, real_close = os.open, os.close

        def tracked_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def tracked_close(fd):
            closed.append(fd)
            real_close(fd)

        with mock.patch.object(os, "open", tracked_open), \
             mock.patch.object(os, "close", tracked_close):
            receipt = self._verify()
        self.assertGreater(len(opened), 0)
        self.assertEqual(sorted(opened), sorted(closed))
        self.assertEqual(receipt["status"], "artifact_checksums_verified")
        data = bytearray((self.root / "b.bin").read_bytes())
        data[0] ^= 0xFF
        (self.root / "b.bin").write_bytes(bytes(data))
        opened.clear()
        closed.clear()
        with mock.patch.object(os, "open", tracked_open), \
             mock.patch.object(os, "close", tracked_close):
            with self.assertRaises(ValueError):
                self._verify()
        self.assertEqual(sorted(opened), sorted(closed))
        (self.root / "b.bin").write_bytes(original["b.bin"])
        real_fstat, real_stat = os.fstat, os.stat
        calls = {"n": 0}

        def mutating_fstat(fd):
            info = real_fstat(fd)
            calls["n"] += 1
            return info if calls["n"] == 1 else \
                cloned_stat(info, st_mtime_ns=info.st_mtime_ns + 1)

        def mutating_stat(path, *args, **kwargs):
            info = real_stat(path, *args, **kwargs)
            return cloned_stat(info, st_ino=info.st_ino + 1)

        def atime_fstat(fd):
            info = real_fstat(fd)
            calls["n"] += 1
            return info if calls["n"] == 1 else \
                cloned_stat(info, st_atime=info.st_atime + 1)

        with mock.patch.object(os, "fstat", mutating_fstat):
            with self.assertRaises(ValueError):
                self._verify()
        with mock.patch.object(os, "stat", mutating_stat):
            with self.assertRaises(ValueError):
                self._verify()
        calls["n"] = 0
        with mock.patch.object(os, "fstat", atime_fstat):
            receipt = self._verify()
        self.assertEqual(receipt["status"], "artifact_checksums_verified")

    def test_no_scientific_imports(self):
        banned = ("numpy", "matplotlib", "scipy", "pandas", "cv2",
                  "detect", "evaluat", "simulat", "render", "sweep",
                  "suppression", "sensitivity", "research", "factorial",
                  "robustness", "cohort", "event", "annotation", "video_io")
        for filename in ("capture_integrity.py", "verify_capture.py"):
            path = REPO_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported += [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imported.append(node.module or "")
            for module in imported:
                top = module.split(".")[0]
                hit = next((p for p in banned if top.startswith(p)), None)
                self.assertIsNone(hit, f"{filename} imports {module}")


if __name__ == "__main__":
    unittest.main()
