# Bounded stream integrity specification

Baseline: main `9e56ded`, 231 hosted tests per Python version.
This is software resource and provenance hardening, not a scientific study.

## Test Plan Before Implementation

All fixtures are owned temporary files. No ignored/private capture dependency,
test skips, real datasets, independent labels or scientific metrics.

### Capture Artifact Reader

`test_capture_stream_bounds.py`, six cases:

1. `test_static_empty_and_binary`: empty file and literal binary bytes produce
   exact independently computed SHA-256; originals remain byte-identical.
2. `test_chunk_boundary`: 1048576+17 bytes hash correctly; no read request
   exceeds 1048576 bytes; final EOF probe requests one byte.
3. `test_growing_artifact_has_fixed_budget`: initially four bytes; append one
   real byte before each artifact read, at most eight appends. ValueError and
   at most two artifact reads, rather than following continued growth.
4. `test_truncated_artifact_rejected`: truncate an owned four-byte file after
   its initial fstat and before its first read; ValueError, no receipt.
5. `test_short_reads_preserve_digest`: return at most one real byte per read;
   unchanged file still hashes exactly, with no premature success.
6. `test_descriptor_closed_after_growth`: track actual opened/closed handles
   during case 3; each opened descriptor closes, including the early error.

Use the REAL capture_integrity.os.read export, delegating to saved os.read.
Identify the target artifact by its real inode so manifest reads are untouched.
Lead already ran case 3 against baseline: nine artifact reads, expected budget
two, actual AssertionError. This is not a fabricated successful verifier.

### Baseline Input Snapshot Reader

`test_detection_stream_bounds.py`, five cases:

1. `test_static_snapshot`: exact digest and actual file signature, no payload
   when keep_bytes=False, identical original file.
2. `test_kept_bytes_and_empty`: keep_bytes=True returns exact original bytes,
   including empty input; digests independently match.
3. `test_growing_snapshot_has_fixed_budget`: same four-byte/eight-append case,
   at most two reads, ValueError, never a successful snapshot.
4. `test_truncated_snapshot_rejected`: truncation after fstat causes ValueError.
5. `test_chunk_boundary_and_close`: 1048576+17 bytes hash exactly, read requests
   at most 1048576 plus one-byte EOF probe; handle closes on success/error.

For buffered readers use a proxy around a REAL file handle, preserving fileno,
context-manager cleanup and all bytes. Do not replace the production snapshot
function with a fake. No model/configuration/metric functions are mocked.

### Annotation Hashing And Preflight

`test_annotation_stream_bounds.py`, six cases:

1. `test_static_hash_and_empty`: independent exact SHA-256, no byte mutations.
2. `test_growing_hash_has_fixed_budget`: same controlled growth case,
   ValueError within two reads.
3. `test_truncated_hash_rejected`: truncation after fstat causes ValueError.
4. `test_fifo_rejected_before_open`: actual owned FIFO fails before a data open.
5. `test_existing_output_before_input_hash`: valid request, existing output
   sentinel and missing input; zero hash calls, FileExistsError, sentinel intact.
6. `test_chunk_boundary`: 1048576+17 bytes, exact digest, one-byte EOF probe.

### Actual CLI Integration

`test_stream_workflow_cli.py`, three cases:

1. `test_real_packet_prediction_and_receipts`: generate one owned black
   three-frame clip with real FFmpeg; actual annotation and detection CLIs,
   same recording ID/rate/cap, each yields three rows. Packet fire cells blank,
   prediction metrics null. Verify both with actual verify_capture.py; receipt
   digests independently match actual files. Software mechanics only.
2. `test_annotation_fifo_cli`: actual FIFO positional input, valid arguments,
   exit 2, no traceback/complete capture, subprocess timeout five seconds.
3. `test_annotation_existing_output_cli`: sentinel output plus missing input,
   exit 2 before input access; exact sentinel bytes and directory entries remain.

## Implementation Plan

No dependency, public signature, default, protocol or capture-schema changes.
The lead-authored literal function bodies are authoritative:

- capture_integrity._hash_artifact: initial fstat size is remaining byte budget;
  each read is min(1 MiB, remaining); early EOF fails, then one extra byte
  detects growth. Keep before/after/final signature checks and descriptor cleanup.
- detection._file_snapshot: same initial-size budget and EOF probe, preserve
  existing signature tuple, digest and optional exact byte snapshot return.
- annotation_packet._sha256_path: reject non-regular input, hash with initial
  fstat size plus EOF probe, compare descriptor and pathname signatures.
  create_packet checks existing output (including dangling symlink) before
  input hashing, after existing cheap request validation. Add stdlib stat import.

Do not truncate input, silently ignore appended bytes, accept partial input or
weaken integrity checks. Large stable files remain supported. Kept label bytes
still use memory proportional to initial input size; this introduces no maximum
input-file size and is not a constant-memory label-parser claim.

## Verification

Focused tests above, unchanged existing component tests, one final full software
gate, actual CLI integration, and deliberately disabled read-budget guards must
turn the appropriate regression tests red. Frozen captures are read-only.
Compare all detector model/metric functions against baseline byte-for-byte.

## Non-Goals

- No new scientific assumption, simulation, sampling setting, threshold,
  evaluation method, resampling rule, target or accuracy claim.
- No schema change, evidence bundle, new dataset or generated human labels.
- No decoder timeout, FFmpeg redesign or promise about stalled operating-system
  reads. Byte budgets are not wall-clock deadlines or malicious-filesystem proof.
- No alteration of historical captures, plots, source footage or protocols.
- No flight control, field deployment, network service or authorization to fly.
