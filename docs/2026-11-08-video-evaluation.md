# Recorded-video event evaluation quickstart

2026-11-08. Additive labelling and evaluation workflow over the existing RGB baseline. The frame evaluator in `detection.py`, its thresholds and all frozen studies are unchanged.

This workflow evaluates **sampled visible-fire episodes** in one lawfully held local recording, not wildfire incidents and not field performance. A human reviewer labels every decoded sample; `event_evaluation.py` binds those labels to baseline predictions and reports the episode metrics defined by [`event_protocol.json`](../event_protocol.json).

## What you need

- A local video file you are permitted to use. Nothing is downloaded or bundled; FFmpeg remains an external dependency.
- A fresh output directory for every command. No step overwrites an existing capture.
- The recording's split assigned **before** annotation. Only a packet preassigned to `test` may be evaluated. Group adjacent clips by recording, incident, site and date across splits; keep test data unseen and freeze detector configuration on validation data.

## Step 1: Blinded annotation packet

```sh
.venv/bin/python annotation_packet.py LOCAL_VIDEO --recording-id event-001 --split test --sample-fps 1 --max-frames 600 --output research-runs/my-annotation
```

The packet contains contact sheets and a `labels.csv` template whose `fire` column is blank on every row. It carries no scores, candidate fractions or inferred labels. Blinding limits prior exposure; it does not by itself guarantee label independence. If `--max-frames` truncates the recording, the packet covers only a sampled prefix, and episodes touching the prefix edges are flagged as censored.

## Step 2: Human adjudication

A human reviewer completes a **separate copy** of `labels.csv`; the original packet and its blank template are retained unchanged.

- Labels describe visible flame at each sampled frame, not smoke-only or thermal targets.
- Use `1` for visible flame and `0` for no visible flame. Inspect the source at adequate resolution when a contact-sheet thumbnail is ambiguous; a small thumbnail alone is not evidence of absence.
- Every sampled index must be labelled exactly once with a binary value.
- Blank or uncertain cells fail evaluation rather than being excluded.
- There is no automated labelling, and fabricated human labels are not acceptable.

## Step 3: Baseline capture

```sh
.venv/bin/python detection.py LOCAL_VIDEO --output research-runs/my-predictions --recording-id event-001 --sample-fps 1 --max-frames 600
```

Same video, recording ID, sample rate and frame limit as the packet. Detector thresholds and persistence are unchanged.

## Step 4: Event evaluation

```sh
.venv/bin/python event_evaluation.py --predictions research-runs/my-predictions --packet research-runs/my-annotation --labels COMPLETED_LABELS.csv --annotator-id reviewer-01 --output research-runs/my-events
```

The evaluator verifies packet and prediction manifests, artifact and input hashes, recording identity, geometry, sample rate and complete label coverage before writing `report.json` and `manifest.json` to a fresh directory. The manifest binds the parsed input bytes and source/report hashes; packet and prediction CSVs retain sampled times. The annotator ID is recorded as self-reported, not verified independence.

## Metric semantics

- **Episodes**: maximal contiguous runs of positive labels or alarms with half-open sample indices `[start, end)`. These are sampled visible-fire episodes, not incidents.
- **Matching**: strict. An alarm onset must land inside a truth episode; only the first such onset matches. Later onsets in the same episode are duplicates, reported separately, and they reduce alarm precision.
- **No credit for preexisting alarms**: an always-on alarm, or one starting before an episode, earns nothing from later overlap.
- **False alarms**: false onsets per non-fire exposure hour, not a frame-level false-positive share.
- **Exposure**: `n_samples / sample_fps`, nominal sampled-bin exposure, not precise source-video duration.
- **Delays**: detected (matched) episodes only; nearest-rank p50 and p90. Misses never count as zero delay. Delays are measured on the sampled timeline, not ignition delay.
- **Censoring**: episodes touching either observed-prefix edge are flagged left or right censored.
- **Zero denominators** report null, never zero and never perfect performance.

## Limits

- No confidence intervals, no pass/fail verdict against field-protocol targets, no threshold fitting or training, and no field-accuracy claim.
- One recording cannot establish generalization or recording-clustered uncertainty; blinding and self-reported annotator IDs do not guarantee independence.
- Packet and prediction decoder-source fingerprints must match. Use the same FFmpeg toolchain too; matching metadata does not certify identical pixels across FFmpeg versions.
- This workflow adds no independent labels and no real detector accuracy results. Frozen studies, captures and charts are unchanged.
- Synthetic colored fixtures exist only to exercise I/O paths in tests; they are not performance evidence.
