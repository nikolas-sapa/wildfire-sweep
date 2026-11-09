# Offline artifact-integrity receipt specification

Baseline: main `5172ae3`, 204 hosted tests per Python version. This additive
software layer checks listed file bytes, not scientific validity. Existing
models, protocols, metrics, thresholds, captures and renderers stay unchanged.

## Test Plan (Before Implementation)

Core tests live in `test_capture_integrity.py`:

1. `test_three_artifacts`: three real temporary regular files (text, empty,
   binary) produce exactly their three independently computed SHA-256 values;
   original manifest/artifact bytes remain identical. Keys are sorted.
2. `test_manifest_contract`: reject missing/malformed JSON, array roots, schema
   values true/0/2/"1", missing/non-complete status, missing/empty/non-map
   artifact inventory and malformed digest keys/values. No writes.
3. `test_strict_json`: reject duplicate keys at root and inside artifact maps,
   NaN, Infinity, -Infinity and a float literal 1e999. No partial success.
4. `test_manifest_size`: accept a valid JSON manifest padded with spaces to
   8 MiB; reject 8 MiB+1 before parsing. Do not allocate unbounded input.
5. `test_artifact_names`: reject empty, ".", "..", "../x", absolute paths,
   backslashes, NUL, "manifest.json", and nonportable/overlong names. Only
   `[A-Za-z0-9][A-Za-z0-9._-]{0,254}` basenames are supported.
6. `test_nonregular_and_symlink_inputs`: reject missing artifacts, directories,
   manifest symlinks and artifact symlinks (even inside the capture). A FIFO
   must fail without blocking: use O_NONBLOCK together with O_NOFOLLOW, then
   fstat and require S_ISREG before reading.
7. `test_tampering`: change one byte in one artifact, keep valid JSON and its
   original expected hash, and require ValueError. No receipt returned.
8. `test_mutation_and_descriptor_cleanup`: metadata/identity mutation while
   reading must fail, and opened descriptors close on success/error. Compare
   device, inode, size, mtime_ns and ctime_ns, not atime. Use deterministic
   stdlib mocks at the os.read/stat seam, never fabricate a successful verifier.
9. `test_no_scientific_imports`: AST rejects imports of detector, evaluator,
   simulator, renderer or NumPy/Matplotlib modules.
10. `test_deep_json`: a valid envelope with an unused array nested 100000 times
    (approximately 200 KiB, below size limit) raises ValueError rather than
    leaking parser RecursionError; actual CLI exits 2 without traceback.

Single-fault rejection fixtures must otherwise be valid, including actual
artifact digests, so disabling a schema/status guard cannot still pass a test
because an unrelated digest mismatch raises the same exception.

All mandatory tests create their own temporary fixtures. No test depends on
ignored research-runs files or skips when private captures are unavailable.

### Producer And Packet-Binding Regression Tests

Lead confirmed an upstream provenance race with actual FFmpeg: a 3-frame input
was decoded, then replaced by a different 4-frame file before the producer's
late hash; the complete manifest recorded the replacement digest. Raw evidence
is retained privately, not detector-accuracy evidence.

`test_detection_capture.py`, software I/O cases only:

1. Stable real 3-frame constructed black clip: capture completes, exactly 3
   predictions, video/optional-label digests equal the consumed byte snapshots.
2. Replace input after REAL decoder completes but before producer writes:
   exit 2, no complete capture and no output directory created.
3. Mutate completed-label file after validation: exit 2 before output creation.
4. Mutate a COPIED source file during processing: exit 2 before output, never
   edit real repository source to simulate this case.
5. Existing output sentinel with missing video: exit 2 before input access;
   sentinel byte-identical.
6. Invalid sample_fps (NaN, 0, 31) or max_frames (0, 100001) rejected before
   file hashing. These are existing decoder bounds, not new sampling rules.
7. A failure while consuming frames closes its generator and produces no
   complete capture. No predictions/configuration/metric formula changes.

`test_report_packet_labels_binding_fails` in test_cohort_capture.py:
change only input_artifact_sha256.packet_labels.csv to a different valid
64-hex digest; cohort evaluation raises ValueError before output creation.
Compare against the labels digest inside the verified, registered packet
manifest, without adding a new registry field or capture schema.

CLI tests live in `test_verify_capture_cli.py`, actual subprocesses, timeout 30:

1. help exits 0; missing positional input exits 2 with usage, no traceback.
2. valid fixture exits 0 and stdout parses as the exact API receipt.
3. --output writes one fresh UTF-8 JSON file with newline, stdout empty.
4. existing file, directory or dangling symlink output exits 2 before accessing
   a missing input and preserves sentinel bytes/entries.
5. missing directory, malformed manifest, mismatched artifact and symlink
   artifact exit 2, no traceback, no receipt output.
6. no detector, simulation or dataset download runs; no source files change.

Integration: verify an existing constructed-clip cohort capture and packet from
the preceding phase, independently compare receipt digests to actual bytes,
then alter a COPIED owned fixture and confirm rejection. Never alter originals.
No actual detector accuracy results may be inferred from this exercise.

## Implementation Contract

Only new modules `capture_integrity.py` and `verify_capture.py`. Standard library,
Python 3.10+, POSIX macOS/Linux. No dependency installation or global config.
Lead consulted CPython docs for directory-relative open and strict JSON hooks.

Approved upstream scope: detection.py capture I/O only, plus the missing
registered-packet-label digest join in cohort_evaluation.py. Existing pure
CandidateConfig, candidate_fraction, predict_frames, frame_metrics,
validate_labels, aggregation and uncertainty functions stay byte-identical.
No protocol, target, threshold, sampling default or historical output changes.
Producer snapshots video/label/source file bytes and identities before decode,
parses labels from that byte snapshot, checks identities/digests again before
writing, explicitly closes its decoder and writes its manifest exclusively.
These checks detect ordinary mid-run changes, not malicious filesystem races
or proof of which bytecode an interpreter loaded.

`capture_integrity.verify_capture(directory) -> dict`:

- Read only directory/manifest/listed artifacts. The root argument can resolve
  through a directory alias, but pin an opened root directory descriptor.
- Open manifest.json and artifacts relative to that descriptor with
  O_RDONLY | O_NOFOLLOW | O_NONBLOCK; require regular files using fstat.
  No following file symlinks, no path traversal, no sockets/FIFO reads.
- Read manifest bytes with an 8 MiB limit (8388608). Reject UTF-8 errors,
  duplicate object keys anywhere, nonfinite constants and float overflow.
  Convert RecursionError from the JSON parsing call only to ValueError for an
  unsupported deeply nested input; do not broadly catch implementation bugs.
- Require a dictionary, schema_version of exact int type and value 1,
  status == "complete", and nonempty dictionary artifact_sha256.
- Every inventory name obeys the portable basename rule above and is not
  manifest.json; every digest is a lowercase 64-character hexadecimal string.
- Hash regular artifacts in 1 MiB chunks, not whole-file reads. Compare
  stat identity/metadata before and after reading; keep signatures of all
  inputs and check them again relative to the pinned root before returning.
  Close every descriptor with finally/context managers.
- Manifest digest is SHA-256 of the exact parsed byte snapshot. Sort artifact
  keys. Do not parse artifact contents or import scientific code.
- Raise ValueError for invalid content/mismatch/mutation; OSError subclasses
  for filesystem problems are acceptable. Unsupported POSIX flags fail loud.
- Return EXACT keys:

```json
{
  "schema_version": 1,
  "status": "artifact_checksums_verified",
  "manifest_sha256": "<actual manifest digest>",
  "artifact_sha256": {"<listed basename>": "<actual digest>"},
  "limitations": ["Only listed file hashes are checked; not completeness, authenticity, labels, source-code identity, split independence or research performance."]
}
```

This is a byte-integrity receipt, not a signed attestation or an atomic
filesystem snapshot. It cannot authenticate a maliciously rewritten manifest.
It does not validate recording/capture schemas beyond the declared envelope.
Source/protocol hash fields and original input files are NOT revalidated.
Old captures without this exact complete-v1 envelope are unsupported; do not
rewrite them or weaken checks to make them compatible.

`verify_capture.main(argv=None) -> int`, CLI:

```sh
.venv/bin/python verify_capture.py CAPTURE_DIR
.venv/bin/python verify_capture.py CAPTURE_DIR --output NEW_RECEIPT.json
```

Optional output check happens BEFORE input access. Never overwrite existing
file, directory or dangling symlink; require existing output parent. Output
uses exclusive file creation. After full verification, write JSON only to
stdout OR output file, indent=2, allow_nan=False, trailing newline. No absolute
source paths or arbitrary manifest metadata are returned. Errors exit 2 with
brief stderr and no traceback, catch OSError/ValueError, do not hide bugs.

## Collection Documentation

Add software-oriented collection checklist, responsible-data handling notes,
reproducibility runbook and research one-pager. Link existing scientific
protocols verbatim; do not author new annotation criteria, scoring rubrics,
sampling thresholds, targets or performance claims. No new machine-readable
dataset schema. Keep current COHORT.csv and pre-review split declarations.

## Non-Goals

- No new scientific model/evaluation/uncertainty methods or refits.
- No footage, labels, datasets, weights, downloads, live APIs or flight control.
- No new authorization, licensing choice, deployment or empirical readiness.
- No automatic repair, source editing, capture reruns, file deletions or
  archived-output changes. Preserve prior results byte-for-byte.
- No assertion that checksum integrity implies independent labels, genuine
  events, correct grouping, capture completeness or useful field performance.
