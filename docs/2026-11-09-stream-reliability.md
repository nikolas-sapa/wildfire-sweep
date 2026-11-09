# Stream reliability guide

2026-11-09. Software-side guide to the bounded-read contract shared by the three byte readers in this repository: the capture verifier (`verify_capture.py`, implemented by `capture_integrity.py`), the detection input snapshot (`detection.py`) and the annotation-packet input hash (`annotation_packet.py`). It explains the stable-file precondition and the per-reader byte budgets. It defines no science: sampling, metrics, thresholds, label semantics and frozen captures are governed elsewhere and unchanged. The authoritative contract and test plan is the [bounded stream specification](2026-11-09-stream-bounds-spec.md).

## Stable-file precondition

Every reader hashes only an input that is regular and stable for the duration of one read pass.

- **Regular.** FIFOs, sockets, devices and directories are rejected before any data is consumed. `verify_capture.py` artifacts open relative to the pinned capture-root descriptor with `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` and are fstat-checked, so a FIFO fails fast instead of blocking the open. `detection.py` and `annotation_packet.py` reject non-regular paths via `path.is_file()` before opening and re-check `stat.S_ISREG` on the opened descriptor.
- **Stable.** The device, inode, size and timestamps recorded at open must still hold after the last byte is read. A file that grows, shrinks or is replaced mid-read is a `ValueError`, never a partial digest. Truncation fails when a read returns early EOF; growth fails on the closing one-byte probe or the final signature comparison; the verifier additionally re-stats every read input against the pinned root before issuing a receipt.

This is a fail-closed precondition over ordinary files, not protection against a malicious filesystem and not a wall-clock deadline. A stalled read remains an operating-system or decoder concern and is out of scope here.

## Byte budgets

All three readers use the same budget shape. The fstat size observed at open becomes the remaining byte budget; each read requests at most `min(1048576, remaining)` bytes (1 MiB); after the budget is spent, exactly one extra byte is requested as an EOF probe that detects appends. The logical byte budget is N+1 for an initially N-byte file. Short reads can require more calls, and buffered handles may prefetch additional bytes internally. A file that keeps growing is rejected rather than followed.

| Reader | Function | Budget notes |
| --- | --- | --- |
| Verifier | `capture_integrity._hash_artifact` | Per-artifact budget from the fstat at open, chunked via `os.read`; `manifest.json` itself is separately capped at 8388608 bytes. |
| Detector | `detection._file_snapshot` | Same budget and probe on the buffered handle; compares both descriptor and pathname signatures after reading. Used for the input video, the `detection.py`/`video_io.py` source snapshots and optional `--labels` bytes. |
| Packet | `annotation_packet._sha256_path` | Same budget and probe; descriptor and pathname signatures compared before the digest is written into the packet's `labels.csv`. |

Consequences worth remembering:

- Large stable files remain supported; the budget limits how much is read per pass, not how large an input may be.
- Bytes kept for `--labels` remain proportional to the initial input size; this is not a constant-memory label-parser claim.
- Every opened descriptor closes on success and on the early error paths.

## Packet output ordering

`annotation_packet.create_packet` validates the request fields first, then refuses an existing output path before any input hashing: a file, directory or dangling symlink at the target raises `FileExistsError`. An existing sentinel output is therefore never touched, and a missing input is never hashed when the output is already taken.

## What this does not establish

- A successful read or receipt means the listed bytes were regular, stable and matched; it establishes nothing about completeness, authenticity, label truth, split independence, detector accuracy or field readiness.
- Byte budgets are read caps, not deadlines: decoder timeouts, FFmpeg behavior and stalled operating-system reads are unchanged and out of scope.

## See also

- [Bounded stream specification](2026-11-09-stream-bounds-spec.md): authoritative contract and test plan for this layer.
- [Capture integrity quickstart](2026-11-09-capture-integrity.md) and [integrity specification](2026-11-09-integrity-spec.md): the verifier's envelope, receipt fields and semantics.
- [Data-collection checklist](data-collection-checklist.md): the capture-handling sequence these readers support.
- [Reproducibility runbook](reproducibility-runbook.md): checking software without rerunning frozen studies.
