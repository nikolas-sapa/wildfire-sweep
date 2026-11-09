import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import detection

READ_CHUNK_BYTES = 1048576


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class _HandleProxy:
    def __init__(self, handle, before_read):
        self._handle = handle
        self._before_read = before_read
        self.requests = []

    def read(self, size=-1):
        self.requests.append(size)
        self._before_read()
        return self._handle.read(size)

    def fileno(self):
        return self._handle.fileno()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return self._handle.__exit__(*exc_info)

    def __getattr__(self, name):
        return getattr(self._handle, name)


class DetectionStreamBoundsTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)

    def tearDown(self):
        self.workspace.cleanup()

    def _input(self, data, name="clip.bin"):
        path = self.root / name
        path.write_bytes(data)
        return path

    def _opener(self, path, before_read):
        info = os.stat(path)
        identity = (info.st_dev, info.st_ino)
        real_open = Path.open
        proxies = []

        def opened(candidate, *args, **kwargs):
            handle = real_open(candidate, *args, **kwargs)
            try:
                stat_info = os.stat(candidate)
            except OSError:
                return handle
            if (stat_info.st_dev, stat_info.st_ino) != identity:
                return handle
            proxy = _HandleProxy(handle, before_read)
            proxies.append(proxy)
            return proxy

        return mock.patch.object(Path, "open", opened), proxies

    def test_static_snapshot(self):
        payload = bytes(range(256)) * 3 + b"\x00\xff"
        path = self._input(payload)
        info = os.stat(path)
        digest, signature, kept = detection._file_snapshot(path)
        self.assertEqual(digest, sha256(payload))
        self.assertEqual(signature, (info.st_dev, info.st_ino, info.st_size,
                                     info.st_mtime_ns, info.st_ctime_ns))
        self.assertIsNone(kept)
        self.assertEqual(path.read_bytes(), payload)

    def test_kept_bytes_and_empty(self):
        for payload in (b"recording,split\n" + bytes(range(64)), b""):
            path = self._input(payload, "labels.csv")
            digest, _signature, kept = detection._file_snapshot(
                path, keep_bytes=True)
            self.assertEqual(digest, sha256(payload))
            self.assertEqual(kept, payload)
            self.assertEqual(path.read_bytes(), payload)

    def test_growing_snapshot_has_fixed_budget(self):
        path = self._input(b"WXYZ")
        state = {"reads": 0, "appends": 0}

        def before_read():
            state["reads"] += 1
            if state["appends"] < 8:
                with open(path, "ab") as handle:
                    handle.write(b"!")
                state["appends"] += 1

        patcher, _proxies = self._opener(path, before_read)
        with patcher:
            with self.assertRaises(ValueError):
                detection._file_snapshot(path)
        self.assertLessEqual(state["reads"], 2)
        self.assertLessEqual(state["appends"], 8)

    def test_truncated_snapshot_rejected(self):
        path = self._input(b"WXYZ")
        state = {"truncated": False}

        def before_read():
            if not state["truncated"]:
                os.truncate(path, 1)
                state["truncated"] = True

        patcher, _proxies = self._opener(path, before_read)
        with patcher:
            with self.assertRaises(ValueError):
                detection._file_snapshot(path)
        self.assertTrue(state["truncated"])

    def test_chunk_boundary_and_close(self):
        payload = (bytes(range(256)) * 4097)[:READ_CHUNK_BYTES + 17]
        path = self._input(payload)
        patcher, proxies = self._opener(path, lambda: None)
        with patcher:
            digest, _signature, _kept = detection._file_snapshot(path)
        self.assertEqual(digest, sha256(payload))
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0].requests, [READ_CHUNK_BYTES, 17, 1])
        self.assertLessEqual(max(proxies[0].requests), READ_CHUNK_BYTES)
        self.assertTrue(proxies[0].closed)

        appends = {"count": 0}

        def grow():
            if appends["count"] < 8:
                with open(path, "ab") as handle:
                    handle.write(b"!")
                appends["count"] += 1

        patcher, proxies = self._opener(path, grow)
        with patcher:
            with self.assertRaises(ValueError):
                detection._file_snapshot(path)
        self.assertTrue(proxies[0].closed)


if __name__ == "__main__":
    unittest.main()
