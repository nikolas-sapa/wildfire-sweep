# Cohort evaluation quickstart

2026-11-09. Additive registry and aggregation workflow over captured single-recording event reports. The RGB baseline, the per-recording evaluator, prior study protocols and frozen studies are unchanged.

This workflow aggregates **already-captured** event-episode reports from a declared cohort under [`cohort_protocol.json`](../cohort_protocol.json). It computes pooled metrics and cluster-bootstrap intervals across recordings. It supplies no independent data, no detector accuracy results and no acceptance verdict: the mechanics exist so that a real labelled cohort can be evaluated later.

## What you need

- One lawfully held local recording per cohort row. Nothing is downloaded or bundled; FFmpeg remains an external dependency.
- Recording metadata assigned **before** review: split, cluster, site and capture date are declared up front, and blank annotation packets are generated before any labelling begins.
- A complete annotation packet for every row, and a captured `event_evaluation.py` report (or a planned path) for every test row. `annotation_packet.py`, `detection.py` and `event_evaluation.py` remain the prerequisites and are unchanged.
- A fresh output directory for every command. No step overwrites an existing capture, and no capture is ever produced twice.

## Step 1: Declare the cohort

`COHORT.csv` uses exactly this seven-column header:

```csv
recording_id,cluster_id,site_id,capture_date,split,packet_dir,event_report_dir
```

| Column | Meaning |
| --- | --- |
| `recording_id` | Anonymous recording ID (existing safe ID pattern); unique per row. |
| `cluster_id` | Group of related recordings. Every recording sharing an incident or other dependence must declare the same cluster; the bootstrap resamples whole clusters. |
| `site_id` | Anonymous site ID. |
| `capture_date` | Canonical ISO `YYYY-MM-DD`; must be a real calendar date. |
| `split` | `train`, `validation` or `test`. At least one `test` row is required. |
| `packet_dir` | Annotation-packet directory, relative to the CSV's parent. Every row needs a current, complete packet. |
| `event_report_dir` | Test rows: a required planned report path, which need not exist when the registry is frozen. Train and validation rows: must be blank. |

CSV paths must be relative, not absolute, and resolve against the CSV file's parent. The freeze stores packet and report references relative to the registry output directory, so the project tree can move afterward. Group declarations are self-reported: hash checks catch exact duplicate sources, not near-duplicates, erroneous groupings or authenticity.

## Step 2: Freeze the registry

```sh
.venv/bin/python cohort_registry.py COHORT.csv --output research-runs/my-cohort-registry
```

The freeze validates every packet artifact hash, including the blank template, and checks that the recorded ID, split and source-video identity agree. Leakage guards then apply across the **entire CSV**, not only the test subset: no recording ID, source-video hash, cluster, site or date may cross splits, and a duplicate source hash is forbidden even inside a single split. The freeze writes a byte snapshot of the original `cohort.csv` plus `manifest.json` binding the protocol, normalized rows, source digests and packet manifest digests. It never copies raw video.

## Step 3: Human labels and captured test reports

The unchanged prerequisites produce what the registry bound. A human reviewer completes a separate copy of each packet's `labels.csv`; there is no automated labelling, and fabricated labels are not acceptable. For each test row:

```sh
.venv/bin/python detection.py LOCAL_VIDEO --output research-runs/my-predictions --recording-id event-001 --sample-fps 1 --max-frames 600

.venv/bin/python event_evaluation.py --predictions research-runs/my-predictions --packet research-runs/my-annotation --labels COMPLETED_LABELS.csv --annotator-id reviewer-01 --output PLANNED_EVENT_REPORT_DIR
```

Each test report must land at exactly the `event_report_dir` path the frozen registry recorded. See the [video-evaluation quickstart](2026-11-08-video-evaluation.md) for packet, adjudication and report semantics.

## Step 4: Aggregate the cohort

```sh
.venv/bin/python cohort_evaluation.py research-runs/my-cohort-registry --output research-runs/my-cohort-results --seed 20261109
```

The evaluator requires every planned test report to exist, and binds each report's artifact hashes, exact packet digest and video identity against the frozen registry. All reports must share the same event protocol, detector configuration, `sample_fps`, scientific source fingerprints and decoder source fingerprints; a different sampling rate fundamentally changes consecutive-frame persistence, and incompatible captures fail rather than being rerun. Output is `summary.csv`, `records.csv`, `report.json`, `cluster_draws.npz` and `manifest.json` in a fresh directory, with checksums and provenance recorded. `cluster_draws.npz` stores the exact resampled cluster index matrix and ordered IDs, and `report.json` records canonical per-record numeric inputs, so the aggregation can be audited without regenerating detector outputs.

The event report's blank-packet label digest must also match the registered packet's verified manifest. Predictions and completed-label digests remain upstream provenance declarations, not inputs independently reopened by cohort aggregation. Retain those source captures and completed labels for audit; neither these checks nor a byte-integrity receipt authenticate human labels.

## Step 5: Render the captured summary

```sh
.venv/bin/python render_cohort.py research-runs/my-cohort-results/summary.csv --output research-runs/my-cohort-results/cohort.png
```

The renderer only reads the captured `summary.csv`. It imports no scientific module, recomputes nothing and refuses an existing output path.

## Metric semantics

- **Pooling**: event counts and non-fire exposure are pooled across the cohort, then divided. Per-recording ratios are never averaged. Two recordings with detected/truth counts of 1/1 and 0/9 give cohort recall 0.1, not 0.5.
- **Delays**: pooled detected-onset delays only, nearest-rank p50/p90 in seconds. Missed episodes stay explicit counts and never enter as zero delay.
- **Resampling unit**: the declared `cluster_id`. Each of 1,000 seeded draws resamples all G clusters with replacement G times and retains every record in each selected cluster, with multiplicity.
- **Intervals**: nominal 95% percentile (2.5% and 97.5% quantiles) cluster-bootstrap intervals per metric. They are pointwise and conditional on declared groups; not simultaneous, not guaranteed coverage, and not input, model or label uncertainty.
- **Informative clusters**: a metric needs at least two clusters that carry information for that metric before an interval is reported: a positive truth denominator for recall, a positive alarm denominator for precision, positive non-fire exposure for the false-onset rate, and at least one matched delay for delay quantiles. Two recordings in one cluster, or two clusters where only one is informative, yield no interval. This is a computational minimum, not an adequate sample size.
- **Undefined draws**: zero-denominator resampled draws are omitted separately per metric and counted in `valid_bootstrap_draws`. Undefined point estimates and unsupported intervals are null, never zero-filled.
- **Compatibility**: all test reports must share the same event protocol, detector configuration, `sample_fps`, scientific source and decoder source fingerprints; the evaluator fails closed on mismatches.
- **Censoring**: episodes touching a sampled-prefix edge remain counted with censor flags. Cohort counts are still sampled visible-fire episodes, not physical incidents or ignition delay.

## Limits

- Declared clusters, sites and dates are self-reported; the guards enforce consistency of declarations, not real-world independence. Hash checks do not detect near-duplicate footage or confirm authenticity.
- No independent labelled data is supplied or fabricated, so there is no real detector accuracy result, no interval against field-protocol targets and no pass/fail verdict.
- No threshold tuning, training, model comparison or new dependency. Frozen studies and prior captures stay byte-identical and are never rerun.
- The earlier one-recording limit still stands: these are aggregation mechanics, and without independent data they produce no empirical uncertainty evidence.
