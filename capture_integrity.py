import hashlib
import json
import math
import os
import re
import stat

MANIFEST_NAME = "manifest.json"
MANIFEST_MAX_BYTES = 8388608
READ_CHUNK_BYTES = 1048576

_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")

LIMITATIONS = [
    "Only listed file hashes are checked; not completeness, authenticity, labels, source-code identity, split independence or research performance."
]

_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


def _signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _open_regular(root_fd, name):
    fd = os.open(name, _OPEN_FLAGS, dir_fd=root_fd)
    try:
        info = os.fstat(fd)
    except BaseException:
        os.close(fd)
        raise
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ValueError("not a regular file: %r" % name)
    return fd, _signature(info)


def _require_stable(fd, signature, name):
    if _signature(os.fstat(fd)) != signature:
        raise ValueError("input changed while reading: %r" % name)


def _read_bounded(fd, limit):
    chunks = []
    total = 0
    remaining = limit + 1
    while remaining > 0:
        data = os.read(fd, min(READ_CHUNK_BYTES, remaining))
        if not data:
            break
        chunks.append(data)
        total += len(data)
        remaining -= len(data)
    if total > limit:
        raise ValueError("manifest exceeds %d bytes" % limit)
    return b"".join(chunks)


def _object_no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate object key: %r" % key)
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant: %r" % value)


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON float literal")
    return number


def _parse_manifest(data):
    try:
        document = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_object_no_duplicates,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except RecursionError as error:
        raise ValueError("Manifest JSON nesting is too deep") from error
    if not isinstance(document, dict):
        raise ValueError("manifest root must be a JSON object")
    schema_version = document.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        raise ValueError("unsupported manifest schema_version")
    if document.get("status") != "complete":
        raise ValueError("manifest status must be 'complete'")
    inventory = document.get("artifact_sha256")
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("manifest artifact_sha256 must be a nonempty object")
    for name, expected in inventory.items():
        if not _NAME_PATTERN.fullmatch(name) or name == MANIFEST_NAME:
            raise ValueError("unsupported artifact name: %r" % name)
        if not isinstance(expected, str) or not _DIGEST_PATTERN.fullmatch(expected):
            raise ValueError("malformed digest for artifact: %r" % name)
    return inventory


def _read_manifest(root_fd):
    fd, signature = _open_regular(root_fd, MANIFEST_NAME)
    try:
        data = _read_bounded(fd, MANIFEST_MAX_BYTES)
        _require_stable(fd, signature, MANIFEST_NAME)
    finally:
        os.close(fd)
    return data, signature


def _hash_artifact(root_fd, name, signatures):
    fd, signature = _open_regular(root_fd, name)
    try:
        digest = hashlib.sha256()
        remaining = signature[2]
        while remaining:
            data = os.read(fd, min(READ_CHUNK_BYTES, remaining))
            if not data:
                raise ValueError("input changed while reading: %r" % name)
            digest.update(data)
            remaining -= len(data)
        if os.read(fd, 1):
            raise ValueError("input grew while reading: %r" % name)
        _require_stable(fd, signature, name)
    finally:
        os.close(fd)
    signatures[name] = signature
    return digest.hexdigest()


def _recheck_signatures(root_fd, signatures):
    for name, expected in signatures.items():
        info = os.stat(name, dir_fd=root_fd, follow_symlinks=False)
        if _signature(info) != expected:
            raise ValueError("input changed during verification: %r" % name)


def verify_capture(directory):
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        manifest_bytes, manifest_signature = _read_manifest(root_fd)
        inventory = _parse_manifest(manifest_bytes)
        signatures = {MANIFEST_NAME: manifest_signature}
        digests = {}
        for name in sorted(inventory):
            actual = _hash_artifact(root_fd, name, signatures)
            if actual != inventory[name]:
                raise ValueError("artifact digest mismatch: %r" % name)
            digests[name] = actual
        _recheck_signatures(root_fd, signatures)
        return {
            "schema_version": 1,
            "status": "artifact_checksums_verified",
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "artifact_sha256": digests,
            "limitations": list(LIMITATIONS),
        }
    finally:
        os.close(root_fd)
