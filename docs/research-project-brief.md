# Research project brief

2026-11-09. One-page description of the software and research infrastructure in
this repository, suitable for a resume or project summary. It states what is
built and what evidence exists. It is not a detector validation, a field
trial, a peer-reviewed publication, a claim of sole authorship or a deployed
system.

## External alert to simulated response

The dispatch lane studies a docked UAV fleet responding after an external
wildfire alert arrives. The alert is an assumed input, not an integrated
detector or live feed. `research.py` simulates dispatch under fixed wind,
airborne endurance, launch-latency and battery-reserve constraints with fleet
contention; the response clock starts at alert receipt. Captured studies are
frozen under `research_results/` with manifests, per-season rows and
source/environment fingerprints:

- The [anchor capture](../README.md#captured-anchor) under
  `research_results/2026-11-07-anchor/`.
- The [assumption stress study](2026-11-08-robustness-study.md): paired
  operating-assumption changes over shared synthetic seasons.
- The [full-factorial extension](2026-11-08-factorial-study.md): 32 cells and
  28 contrasts over the same 200 shared synthetic seasons. At 25 bases and
  fixed 12 m/s wind, the endurance/reserve interaction adds a 5.56
  percentage-point loss beyond additive effects, averaged over launch
  settings. Reuse of the source alerts is not independent replication.

All results are synthetic fixed-wind scenarios with unmeasured aircraft
inputs. Monte Carlo intervals quantify resampling error only, not input,
model or weather uncertainty.

## Recorded-video baseline

A separate offline lane processes lawfully held local video. It is not the
upstream detector the dispatch lane assumes. `video_io.py` and `detection.py`
form an exploratory RGB color/persistence baseline over sampled frames. The
additive evaluation mechanics are:

- [Blinded annotation packets and event-episode evaluation](2026-11-08-video-evaluation.md)
  for one fully human-labelled test recording, once provided.
- [Cohort registry and pooled cluster-bootstrap aggregation](2026-11-09-cohort-evaluation.md)
  over captured per-recording reports.
- [Capture byte-integrity receipts](2026-11-09-capture-integrity.md), which
  verify listed file hashes only, not completeness, authenticity or labels.

No independently labelled evaluation exists, so there is no detector accuracy
result. These are mechanics, not evidence.

## Evidence gates

The [research roadmap](research-roadmap.md) defines what is still missing:

- **Independent data.** Recordings with splits, clusters, sites and dates
  declared before review; completed human labels; captured test reports
  aggregated under the frozen registry. The mechanics exist; independent
  labels and verified group independence remain missing.
- **Authorized field work.** Measured endurance and launch latency under a
  qualified, authorized, conservative VLOS protocol, per the
  [proposed field protocol](../field_protocol.json). This is a future
  evidence gate, not authorization to fly.

## Resume-safe description

> Developed a reproducible Python research prototype for drone-supported
> wildfire-alert verification: a synthetic wind-aware dispatch simulation with
> frozen, hash-captured studies and paired season-bootstrap comparisons, plus
> an offline recorded-video RGB baseline with blinded-annotation,
> cohort-registry and byte-integrity tooling. Described as simulation
> research infrastructure, not a validated detector, deployed system or
> sole-author effort.

Claim only what can be explained and substantiated, and disclose
collaboration and AI assistance where relevant.

## Primary documents

- Studies: [robustness](2026-11-08-robustness-study.md),
  [factorial](2026-11-08-factorial-study.md),
  [anchor section](../README.md#captured-anchor).
- Workflows: [video evaluation](2026-11-08-video-evaluation.md),
  [cohort evaluation](2026-11-09-cohort-evaluation.md),
  [capture integrity](2026-11-09-capture-integrity.md),
  [data-collection checklist](data-collection-checklist.md),
  [responsible data handling](responsible-data-handling.md).
- Limits: [README evidence and limitations](../README.md#evidence-and-limitations),
  [integrity-spec non-goals](2026-11-09-integrity-spec.md),
  [research roadmap](research-roadmap.md).
