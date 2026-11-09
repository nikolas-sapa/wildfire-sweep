import hashlib
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import annotation_packet

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


class AnnotationStreamBoundsTests(unittest.TestCase):
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

    def test_static_hash_and_empty(self):
        for payload in (bytes(range(256)) + b"\x00\xff" * 3, b""):
            path = self._input(payload)
            before = path.read_bytes()
            self.assertEqual(annotation_packet._sha256_path(path),
                             sha256(payload))
            self.assertEqual(path.read_bytes(), before)

    def test_growing_hash_has_fixed_budget(self):
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
                annotation_packet._sha256_path(path)
        self.assertLessEqual(state["reads"], 2)
        self.assertLessEqual(state["appends"], 8)

    def test_truncated_hash_rejected(self):
        path = self._input(b"WXYZ")
        state = {"truncated": False}

        def before_read():
            if not state["truncated"]:
                os.truncate(path, 1)
                state["truncated"] = True

        patcher, _proxies = self._opener(path, before_read)
        with patcher:
            with self.assertRaises(ValueError):
                annotation_packet._sha256_path(path)
        self.assertTrue(state["truncated"])

    def test_fifo_rejected_before_open(self):
        fifo = self.root / "pipe.bin"
        os.mkfifo(fifo)
        self.assertTrue(stat.S_ISFIFO(os.stat(fifo).st_mode))
        opened = []
        real_open = Path.open

        def tracking(candidate, *args, **kwargs):
            opened.append(candidate)
            return real_open(candidate, *args, **kwargs)

        with mock.patch.object(Path, "open", tracking):
            with self.assertRaises(FileNotFoundError):
                annotation_packet._sha256_path(fifo)
        self.assertEqual(opened, [])

    def test_existing_output_before_input_hash(self):
        sentinel = self.root / "packet"
        sentinel_bytes = b"sentinel: do not overwrite\n"
        sentinel.write_bytes(sentinel_bytes)
        missing = self.root / "missing.bin"
        calls = []
        real_hash = annotation_packet._sha256_path

        def counting(path):
            calls.append(path)
            return real_hash(path)

        with mock.patch.object(annotation_packet, "_sha256_path", counting):
            with self.assertRaises(FileExistsError):
                annotation_packet.create_packet(
                    missing, sentinel, "rec-01", "test")
        self.assertEqual(calls, [])
        self.assertEqual(sentinel.read_bytes(), sentinel_bytes)

    def test_chunk_boundary(self):
        payload = (bytes(range(256)) * 4097)[:READ_CHUNK_BYTES + 17]
        path = self._input(payload)
        patcher, proxies = self._opener(path, lambda: None)
        with patcher:
            digest = annotation_packet._sha256_path(path)
        self.assertEqual(digest, sha256(payload))
        self.assertEqual(len(proxies), 1)
        self.assertEqual(proxies[0].requests, [READ_CHUNK_BYTES, 17, 1])
        self.assertLessEqual(max(proxies[0].requests), READ_CHUNK_BYTES)
        self.assertEqual(proxies[0].requests[-1], 1)
        self.assertEqual(path.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
