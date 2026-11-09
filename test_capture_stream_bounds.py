import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import capture_integrity

READ_CHUNK_BYTES = 1048576


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def envelope(inventory):
    document = {"schema_version": 1, "status": "complete",
                "artifact_sha256": inventory}
    return json.dumps(document).encode()


class CaptureStreamBoundsTests(unittest.TestCase):
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

    def _target(self, name):
        info = os.stat(self.root / name)
        return info.st_dev, info.st_ino

    @staticmethod
    def _is_target(fd, target):
        try:
            info = os.fstat(fd)
        except OSError:
            return False
        return (info.st_dev, info.st_ino) == target

    def test_static_empty_and_binary(self):
        files = {"empty.bin": b"",
                 "blob.bin": bytes(range(256)) + b"\x00\xff" * 5}
        inventory = self._capture(files)
        manifest_before = self.manifest.read_bytes()
        receipt = self._verify()
        self.assertEqual(receipt["artifact_sha256"], inventory)
        self.assertEqual(receipt["manifest_sha256"], sha256(manifest_before))
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        for name, data in files.items():
            self.assertEqual((self.root / name).read_bytes(), data)

    def test_chunk_boundary(self):
        payload = (bytes(range(256)) * 4097)[:READ_CHUNK_BYTES + 17]
        self._capture({"clip.bin": payload})
        target = self._target("clip.bin")
        requests = []
        real_read = os.read

        def tracking_read(fd, size):
            if self._is_target(fd, target):
                requests.append(size)
            return real_read(fd, size)

        with mock.patch.object(capture_integrity.os, "read", tracking_read):
            receipt = self._verify()
        self.assertEqual(receipt["artifact_sha256"]["clip.bin"],
                         sha256(payload))
        self.assertEqual(requests, [READ_CHUNK_BYTES, 17, 1])
        self.assertLessEqual(max(requests), READ_CHUNK_BYTES)
        self.assertEqual(requests[-1], 1)

    def test_growing_artifact_has_fixed_budget(self):
        self._capture({"clip.bin": b"WXYZ"})
        path = self.root / "clip.bin"
        target = self._target("clip.bin")
        state = {"reads": 0, "appends": 0}
        real_read = os.read

        def growing_read(fd, size):
            if self._is_target(fd, target):
                state["reads"] += 1
                if state["appends"] < 8:
                    with open(path, "ab") as handle:
                        handle.write(b"!")
                    state["appends"] += 1
            return real_read(fd, size)

        with mock.patch.object(capture_integrity.os, "read", growing_read):
            with self.assertRaises(ValueError):
                self._verify()
        self.assertLessEqual(state["reads"], 2)
        self.assertLessEqual(state["appends"], 8)

    def test_truncated_artifact_rejected(self):
        self._capture({"clip.bin": b"WXYZ"})
        path = self.root / "clip.bin"
        target = self._target("clip.bin")
        state = {"truncated": False}
        real_read = os.read

        def truncating_read(fd, size):
            if self._is_target(fd, target) and not state["truncated"]:
                os.truncate(path, 1)
                state["truncated"] = True
            return real_read(fd, size)

        with mock.patch.object(capture_integrity.os, "read", truncating_read):
            with self.assertRaises(ValueError):
                self._verify()
        self.assertTrue(state["truncated"])

    def test_short_reads_preserve_digest(self):
        payload = b"PQRS"
        self._capture({"clip.bin": payload})
        target = self._target("clip.bin")
        state = {"reads": 0}
        real_read = os.read

        def short_read(fd, size):
            if self._is_target(fd, target):
                state["reads"] += 1
                size = min(size, 1)
            return real_read(fd, size)

        with mock.patch.object(capture_integrity.os, "read", short_read):
            receipt = self._verify()
        self.assertEqual(receipt["artifact_sha256"]["clip.bin"],
                         sha256(payload))
        self.assertEqual(state["reads"], len(payload) + 1)

    def test_descriptor_closed_after_growth(self):
        self._capture({"clip.bin": b"WXYZ"})
        path = self.root / "clip.bin"
        target = self._target("clip.bin")
        opened, closed = [], []
        appends = {"count": 0}
        real_read = os.read
        real_open, real_close = os.open, os.close

        def growing_read(fd, size):
            if self._is_target(fd, target) and appends["count"] < 8:
                descriptor = real_open(str(path),
                                       os.O_WRONLY | os.O_APPEND)
                try:
                    os.write(descriptor, b"!")
                finally:
                    real_close(descriptor)
                appends["count"] += 1
            return real_read(fd, size)

        def tracked_open(*args, **kwargs):
            descriptor = real_open(*args, **kwargs)
            opened.append(descriptor)
            return descriptor

        def tracked_close(descriptor):
            closed.append(descriptor)
            real_close(descriptor)

        with mock.patch.object(capture_integrity.os, "read", growing_read), \
             mock.patch.object(capture_integrity.os, "open", tracked_open), \
             mock.patch.object(capture_integrity.os, "close", tracked_close):
            with self.assertRaises(ValueError):
                self._verify()
        self.assertGreater(len(opened), 0)
        self.assertEqual(sorted(opened), sorted(closed))


if __name__ == "__main__":
    unittest.main()
