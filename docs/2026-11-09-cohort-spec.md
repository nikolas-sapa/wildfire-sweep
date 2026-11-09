# Cohort Evaluation: Acceptance Plan

## Tests Before Implementation

1. `test_pool_counts_not_mean_ratios`: two records with detected/truth 1/1 and 0/9
   give recall 0.1, not 0.5. Pool negative exposure and false episodes similarly.
2. `test_detected_only_pooled_delays`: pooled [0,2,8] gives p50=2, p90=8;
   missed episodes never add zero delays.
3. `test_manual_cluster_draws` and `test_seeded_reproducibility`: fixed manually
   enumerated draws for three clusters match all five estimates/endpoints to
   1e-12; independent seeded runs agree. Related recordings are drawn together.
4. `test_minimum_informative_clusters`: two recordings in one cluster yield no CI.
   Two total clusters with only one
   informative cluster for a metric also yield no CI for that metric.
5. `test_undefined_and_invalid_metrics`: zero denominators give null; count draws
   when resampled
   denominators vanish. Reject negative/fractional counts or nonfinite exposure.
6. `test_registry_split_guards`: reject duplicate recording IDs/source hashes, cross-split cluster/site/date,
   packet split/ID mismatch, invalid ISO dates, malformed headers or empty cohort.
7. `test_registry_freeze`: permits planned test report paths not yet present, but requires
   current complete packet captures. Preserve input CSV bytes and fingerprints.
8. `test_report_bindings`: cohort evaluation requires every planned test report, validates artifact/
   manifest hashes, exact registered packet digest, video identity, same event
   protocol, detector configuration, sample_fps and scientific source fingerprints.
9. `test_report_numeric_closure`: truth=detected+missed, alarms=matched+duplicate+false.
   Delay/censor details and sample exposure must agree with captured counts.
10. `test_fail_closed_and_exclusive`: existing output, modified registry CSV/packet/report, absent reports or
    incompatible configurations fail before new output is created.
11. `negative_controls`: mean-of-recording-recalls mutant must fail test 1;
    a cluster-to-recording resampling mutant must fail test 3.
12. `test_capture_only_renderer`: five unique metric rows, nulls and unavailable
    CIs, rejects malformed/duplicate rows and refuses overwrite.
13. `test_real_cli_workflow`: constructed software fixtures only, never described as
    actual detector accuracy. Preserve existing frozen studies byte-for-byte.
14. `final_gate`: full unit suite once, three historical checks, CLI help,
    SVG/chart visual review and both hosted Python jobs.

## Settled Design

Add a standalone frozen registry and cohort evaluator. Existing individual-video
and scientific scripts remain unchanged. No schema migration, database or new
dependency. Scientific configuration, registry guards, aggregation, resampling,
numerical tests and result checking are lead-authored.

### Registry

`cohort_registry.py COHORT.csv --output DIR`
Expose `freeze_cohort(csv_path, output)` and `COHORT_FIELDS` matching protocol.
CSV exact seven columns: recording_id, cluster_id, site_id, capture_date, split,
packet_dir, event_report_dir. IDs use the existing safe anonymous ID pattern.
Date must be canonical YYYY-MM-DD and a real calendar date. All rows need a
complete annotation packet; recorded ID/split/source-video identity must agree.
Validate every packet artifact hash, including blank template and expected pages.

No recording ID, source-video hash, cluster, site or date may cross splits.
Forbid duplicate source-video hashes altogether (not just across splits).
Near duplicates and erroneous group declarations are not automatically detected.
Only test rows may name event_report_dir; require a planned path for every test
row, allow the report not to exist yet. Train/validation paths must be blank.
Require at least one test row. Group leakage guards apply across the entire CSV,
not only the test subset.

Resolve CSV paths against its parent, then store packet/report references relative
to the fresh registry output directory so moving the whole project remains useful.
Write original `cohort.csv` byte snapshot plus `manifest.json`, status complete.
Manifest contains protocol, normalized rows, source CSV digest, source hashes,
packet manifest digests, and cohort.csv artifact hash. Use parsed byte snapshots
for provenance, not later file rereads. Never copy raw videos/datasets.
Normalized rows also freeze each packet's decoder fingerprint, sample_fps and
decoded_frames; report bindings and cohort compatibility must preserve these.

### Numerical Evaluator

`cohort_evaluation.py REGISTRY_DIR --output DIR [--seed INT]`
Expose `cohort_metrics(records)` and
`cohort_intervals(records, seed=20261109, replicates=1000)`, plus
`run_cohort(registry, output, seed=20261109)`.
Each internal record contains recording_id, cluster_id and the captured single-
recording metrics dictionary. Resample clusters, never independent frames or
independent recordings inside a shared cluster.

Pool counts for event_recall, alarm_precision and false_alarms_per_nonfire_hour.
Pool captured detected delays for nearest-rank p50/p90. Report complete raw
counts, exposure, censor counts, number of records/clusters and all source IDs.
Use 1,000 seeded numpy default_rng draws of G cluster indices of size G.
For each draw, include all records from each selected cluster with multiplicity.
Percentiles use linear np.quantile([0.025,0.975]). Null denominators are omitted
per metric and valid_bootstrap_draws is recorded. CI requires at least two
informative clusters for that specific metric, not merely two total clusters.
This is a computational minimum, not adequate empirical sample size or guaranteed
coverage. No target-passing or significance-based filtering.

Validate all test report bindings against the frozen registry and existing
event protocol, report fingerprints and numerical closure. Fail closed on
different detector configs or scientific source hashes; do not rerun reports
to make them compatible. Check packet manifests still match frozen digests.
All input JSON/CSV provenance binds the bytes actually parsed.

Outputs: `summary.csv`, `records.csv`, `report.json`, `manifest.json` written last.
Report includes aggregate counts, five metrics/intervals/status, limits and
source provenance. No actual accuracy results may be published from software
fixtures. Manifest hashes all artifacts and exact executed sources/protocol.
Also capture `cluster_draws.npz` with cluster_indices and ordered cluster_ids,
so later verification does not depend on a future NumPy RNG implementation.
`cohort_intervals` returns aggregate, intervals, cluster_ids, draws (integer
matrix), seed and replicates. API replicates accepts integers 1..10000 for tests;
CLI remains fixed at the protocol's 1000 draws.

Summary exactly five rows, columns:
metric,estimate,ci_95_low,ci_95_high,unit,n_records,n_clusters,
informative_clusters,valid_bootstrap_draws,ci_status.
Units: fraction for recall/precision, per_nonfire_hour for false alarms,
seconds for delays. Status: undefined (point null), insufficient_clusters
(point present but informative clusters<2), or cluster_bootstrap (CI present).
Unavailable numbers are empty CSV cells / JSON null, never zero replacements.

### Capture-Only Renderer (Delegated)

`render_cohort.py SUMMARY.csv --output PNG`; expose `render(summary, output)`.
Only read captured summary.csv, no scientific modules or recalculation.
Three panels: recall/precision in percent (0..100), false onset rate, p50/p90
delay. Discrete markers and capped CIs, no connecting trends. Mark undefined
points and absent intervals explicitly. Validate five unique metrics, units,
finite/range/count/status consistency; do not require point inside percentile CI.
Fresh PNG only. Blue/slate style. Footer: pointwise cluster bootstrap, declared
groups not verified independence, not field validation. Fixtures only until
independent data exists; do not embed fake result charts in README.

## Fleet Scope

Parallel free SWE-2 Max work: renderer/tests; README/quickstart/conceptual SVG;
CLI/capture software tests. A fourth bounded agent runs final verification after
integration. Lead owns both registry and numerical evaluator (including leakage
rules), all scientific tests and checking. No two agents write the same files.

## Non-Goals

No new labelled data, dataset downloads, calibration, model tuning, incident
claims, live flight, regulatory approval or deployment. Do not modify any
frozen research_results or historical CSV/PNG. Empty registry templates/examples
may document fields but never invent plausible human recording data or results.
