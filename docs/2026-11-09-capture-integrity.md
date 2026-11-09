# Capture integrity quickstart

2026-11-09. Additive software layer that verifies the listed file bytes of a completed capture envelope and emits a receipt. Existing models, protocols, metrics, thresholds, captures and renderers are unchanged.

`verify_capture.py` answers one narrow question: do the files a capture's `manifest.json` lists still hash to the digests that manifest declares? It is a byte-integrity check over an already-captured directory, nothing more. It runs no detector, evaluation, simulation or renderer code and imports no scientific module.

## What you need

- Python 3.10+ on POSIX macOS or Linux. Standard library only; no dependency installation or global configuration.
- A capture directory holding a `manifest.json` with the complete schema-v1 envelope described below.
- For `--output`, an existing parent directory and a fresh, unused file name.

## Supported envelope

Only a complete schema-v1 envelope is supported. `manifest.json` must be a UTF-8 JSON object of at most 8388608 bytes (8 MiB), with no duplicate object keys and no nonfinite constants, containing:

| Field | Requirement |
| --- | --- |
| `schema_version` | Exact integer `1`; booleans, strings such as `"1"`, and other values are rejected. |
| `status` | The string `"complete"`. |
| `artifact_sha256` | Nonempty object mapping each listed artifact basename to a lowercase 64-character hexadecimal digest. |

Every listed name must be a portable basename matching `[A-Za-z0-9][A-Za-z0-9._-]{0,254}`: no empty names, `.` or `..`, nested or absolute paths, backslashes, NUL bytes, or `manifest.json` itself.

Older captures without this exact complete-v1 envelope are unsupported. They are left unchanged, and the checks are not weakened to accept them.

## Step 1: Verify a capture

```sh
.venv/bin/python verify_capture.py CAPTURE_DIR
```

On success the receipt prints to stdout and the command exits 0. On any failure the command exits 2 with a brief stderr message and no traceback, and no receipt is produced. `.venv/bin/python verify_capture.py --help` prints usage and exits 0; a missing positional argument exits 2 with usage.

## Step 2: Write the receipt to a file

```sh
.venv/bin/python verify_capture.py CAPTURE_DIR --output research-runs/NEW_RECEIPT.json
```

The output check runs before any input is accessed. The parent directory must already exist and the target must be new: an existing file, directory or dangling symlink is refused, and the receipt file is created exclusively. The file holds the same JSON stdout would print, indent 2 with a trailing newline, and stdout stays empty.

## Receipt fields

The library entry point `capture_integrity.verify_capture(directory) -> dict` and the CLI emit exactly these keys:

```json
{
  "schema_version": 1,
  "status": "artifact_checksums_verified",
  "manifest_sha256": "<actual manifest digest>",
  "artifact_sha256": {"<listed basename>": "<actual digest>"},
  "limitations": ["Only listed file hashes are checked; not completeness, authenticity, labels, source-code identity, split independence or research performance."]
}
```

- `manifest_sha256` is the SHA-256 of the exact parsed manifest byte snapshot.
- `artifact_sha256` maps each listed basename, sorted, to the digest of the bytes actually read.
- The receipt contains no absolute source paths and no arbitrary manifest metadata.

The API raises `ValueError` for invalid content, digest mismatch or mutation detected while reading, and `OSError` subclasses for filesystem problems. The CLI (`verify_capture.main(argv=None) -> int`) converts these to exit 2.

## How the check works

- The root argument may resolve through a directory alias, but all further access is relative to a pinned root directory descriptor.
- `manifest.json` and each artifact open relative to that descriptor with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and must be regular files per fstat: no symlink following, no path traversal, no FIFO or socket reads. Platforms lacking these flags fail loudly rather than degrading silently.
- Each artifact's initial fstat size is its read byte budget. Reads request at most 1 MiB at a time and never more than the remaining budget, so no whole-file reads and no following continued growth. Short reads consume only the bytes actually returned. EOF before the budget is spent means the file shrank and fails with `ValueError`. After the budget is spent, a single one-byte EOF probe detects appended data: any byte returned means the file grew and also fails with `ValueError`. Growth and truncation are rejected, never silently ignored or hashed as a partial prefix.
- File identity and metadata (device, inode, size, mtime_ns, ctime_ns; not atime) are compared before and after reading, and all inputs are checked again against the pinned root before the receipt is returned, so a file swapped mid-read fails.
- The budget scales with each file's own initial size, so it is not a maximum supported file size: large stable files still verify. It bounds bytes read, not elapsed time; it is not a deadline, not an atomic snapshot and not an authenticity claim.
- Artifact contents are never parsed. Source/protocol hash fields inside the manifest and the capture's original inputs are not revalidated.

## What the receipt does not mean

A verified receipt is **not** evidence of:

- **Completeness.** Only listed files are hashed; unlisted siblings and anything absent from the inventory are invisible to the check.
- **Authenticity.** A maliciously rewritten manifest passes if it is self-consistent. This is not a signed attestation and not an atomic filesystem snapshot.
- **Source-code identity.** Matching digests do not prove which code produced the capture.
- **Human label truth.** Labels are not inspected, and nothing here confirms a reviewer labelled anything.
- **Split independence.** Cluster, site, date and leakage declarations are not revalidated here; that is the frozen registry's job, upstream.
- **Accuracy or research performance.** No detector, evaluation or field-readiness claim follows from byte integrity.

## See also

- [Integrity specification](2026-11-09-integrity-spec.md): the authoritative contract and test plan for this layer.
- [Cohort evaluation quickstart](2026-11-09-cohort-evaluation.md): the upstream workflow whose captured outputs this tool can verify.
- [Data-collection checklist](data-collection-checklist.md): software-oriented capture-handling checklist.
- [Reproducibility runbook](reproducibility-runbook.md): checking software without rerunning frozen studies.
