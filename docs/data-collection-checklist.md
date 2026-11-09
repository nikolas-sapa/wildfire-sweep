# Data collection and handoff checklist

2026-11-09. Software-side collection and handoff checklist for the recorded-video lane. It orders the mechanical steps that produce a frozen cohort: private metadata first, blank annotation packets, registry freeze, then independent human labels and captured reports.

This checklist changes no science. [`field_protocol.json`](../field_protocol.json), [`event_protocol.json`](../event_protocol.json) and [`cohort_protocol.json`](../cohort_protocol.json) govern targets, sampling, label semantics, splits, aggregation and guards; this document links them and does not restate or replace them. It adds no targets, sampling rules, annotation rubric, dataset schema or readiness verdict. Label semantics for the human reviewer are documented in the [video-evaluation quickstart](2026-11-08-video-evaluation.md); registry and aggregation mechanics in the [cohort-evaluation quickstart](2026-11-09-cohort-evaluation.md).

## Order of operations

The sequence is fixed because the registry binds blank packets:

1. Draft private worksheet metadata before anyone reviews frames.
2. Generate one blank annotation packet per recording.
3. Write `COHORT.csv` and freeze the registry.
4. Complete independent human labels and captured test reports at the frozen paths.

## 1. Intake, before any review

- [ ] Every recording is lawfully held. Sources are limited to lawfully captured burns or professionally managed events used with organizer permission (`field_protocol.json` preconditions). No downloads, no flights and no ignitions are performed as part of this checklist.
- [ ] A private source/rights-ledger entry exists per recording; only its anonymous reference is copied onto the worksheet below. The ledger itself is never committed or copied into the registry; retain its private provenance history.
- [ ] One worksheet row per recording is drafted before annotation or content review. Splits, clusters, sites and dates are declared up front, not after viewing frames.
- [ ] `recording_id`, `cluster_id` and `site_id` are anonymous and match the existing safe ID pattern `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; `capture_date` is canonical `YYYY-MM-DD` and a real calendar date.
- [ ] `derived_clip_relationship` records how each recording relates to the others (shared source video, adjacent clips of one burn, same incident, same site or date). Human judgment decides `cluster_id`; hash checks catch exact duplicate source bytes, not near-duplicates or re-encodings.
- [ ] `sensor_modality` is recorded per recording. The captured baseline processes RGB only and does not detect smoke; modality expectations remain governed by `field_protocol.json`.
- [ ] `split` is declared per recording (`train`, `validation` or `test`). At least one `test` row is required for a freezable cohort.
- [ ] `packet_path` is chosen per recording as a fresh, nonexistent directory relative to the planned `COHORT.csv` parent. `planned_report_path` is required for `test` rows and stays blank for `train`/`validation` rows.

## 2. Blank metadata worksheet

Private working surface. It is intentionally empty; do not populate it with invented rows, people or sites. The registry-facing subset is `COHORT.csv` (next section); the ledger reference, modality and clip-relationship columns stay private and are not registered. Column mapping: `packet_path` becomes `packet_dir`, and `planned_report_path` becomes `event_report_dir` for `test` rows only.

| source_rights_ledger_ref | recording_id | cluster_id | site_id | capture_date | split | sensor_modality | derived_clip_relationship | packet_path | planned_report_path |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |
|  |  |  |  |  |  |  |  |  |  |

## 3. Blank annotation packets

- [ ] One packet per recording via `annotation_packet.py` with the declared `--recording-id` and `--split`; record the `--sample-fps` and `--max-frames` used, for identical reuse in later captures. Every output is a fresh directory.

```sh
.venv/bin/python annotation_packet.py LOCAL_VIDEO --recording-id RECORDING_ID --split SPLIT --sample-fps 1 --max-frames 600 --output PACKET_PATH
```

- [ ] Each packet contains contact sheets and a `labels.csv` whose `fire` column is blank on every row: no scores, candidate fractions or inferred labels.
- [ ] Packet directories land at the declared `packet_path` values and are left unchanged afterward; the freeze verifies them byte-for-byte.

## 4. COHORT.csv and registry freeze

`COHORT.csv` uses exactly this seven-column header:

```csv
recording_id,cluster_id,site_id,capture_date,split,packet_dir,event_report_dir
```

- [ ] Every worksheet row is transcribed to a `COHORT.csv` row with no added, renamed or reordered columns.
- [ ] `packet_dir` and `event_report_dir` are relative paths resolved against the CSV's parent; `event_report_dir` is blank for `train`/`validation` rows and names a planned, possibly nonexistent path for every `test` row.
- [ ] Leakage declarations are consistent across the whole CSV: no recording ID, source-video hash, cluster, site or date crosses splits, and no duplicate source-video hash exists even within one split.

```sh
.venv/bin/python cohort_registry.py COHORT.csv --output FRESH_REGISTRY_DIR
```

- [ ] The freeze runs once against the current blank packets; the returned registry directory (`cohort.csv` byte snapshot plus `manifest.json`) is retained.

## 5. Independent human labels and captured reports

Only after the freeze:

- [ ] A human reviewer completes a separate copy of each packet's `labels.csv` under the label semantics in the [video-evaluation quickstart](2026-11-08-video-evaluation.md). The original packet stays blank and unchanged. There is no programmatic labelling, and fabricated labels are not acceptable.
- [ ] For each `test` row, `detection.py` and `event_evaluation.py` run with the same recording ID, sample rate and frame cap as the packet, and the report lands at exactly the frozen `event_report_dir` path.

```sh
.venv/bin/python detection.py LOCAL_VIDEO --output PREDICTIONS_DIR --recording-id RECORDING_ID --sample-fps 1 --max-frames 600

.venv/bin/python event_evaluation.py --predictions PREDICTIONS_DIR --packet PACKET_PATH --labels COMPLETED_LABELS.csv --annotator-id ANONYMOUS_ID --output PLANNED_REPORT_PATH
```

- [ ] Annotator IDs are anonymous and self-reported; independent adjudication and review are human arrangements the software cannot verify.
- [ ] Completed `labels.csv` copies, prediction captures and report directories are recorded against the worksheet rows; nothing overwrites an existing capture.

## Handoff package

A complete software handoff contains, per cohort:

- [ ] The frozen registry directory (`cohort.csv` byte snapshot plus `manifest.json`).
- [ ] Every blank annotation packet directory, byte-identical to freeze time.
- [ ] Completed `labels.csv` copies, held separately from the packets.
- [ ] Prediction captures and `event_evaluation.py` report directories at the registry-bound paths.
- [ ] The private worksheet and source/rights-ledger references, kept outside the registry and any published output.
- [ ] Optionally, byte-integrity receipts from `verify_capture.py` for listed captures (see the [integrity spec](2026-11-09-integrity-spec.md)).

## What this checklist does not establish

- Checksums and receipts verify that listed file bytes did not change. They cannot establish authentic source rights, genuine events, label independence, correct grouping, capture completeness or field performance.
- Group declarations and annotator independence are self-reported; hash checks do not detect near-duplicate or re-encoded footage.
- Completing every item is a mechanical state, not a readiness verdict and not detector-accuracy evidence. Frozen studies, captures and protocols remain unchanged.
