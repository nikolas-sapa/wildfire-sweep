# Reproducibility runbook

2026-11-09. Software-side runbook for reproducing this repository's checks, captures and byte-integrity receipts. It orders existing commands and links the fixed protocols; it defines no new science, thresholds, rubrics or acceptance criteria. Frozen studies, captures, metrics and renderers stay unchanged.

## What you need

- Python 3.10 or newer on POSIX macOS or Linux.
- A fresh virtual environment with the pinned dependencies, per the [README](../README.md#reproduce):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

- FFmpeg, externally installed, for the recorded-video lane and the full test suite. Nothing is downloaded or bundled by the project.
- A fresh output path for every capture command. `research-runs/` is the local, ignored output area for new runs. `research_results/` and tracked historical plots hold published evidence; ignored root CSV outputs may exist only locally and are not bundled by this runbook.

## Step 1: Verify the software baseline

```sh
make verify
```

`make verify` runs the full unit suite and then the three historical self-checks (`sweep.py --check`, `suppression.py --check`, `sensitivity.py --check`), the same sequence the CI workflow runs. [`AGENTS.md`](../AGENTS.md) additionally lists `.venv/bin/python render_study.py --help` as a renderer smoke check.

Run each command directly so its real exit code reaches the shell. Do not wrap a step in a pipeline such as `command | tail` or append `|| true`: the pipeline then reports the last filter's status and a failing step looks green. If output is long, redirect the full log to a file inside the fresh run directory and inspect the command's own exit status. `make` stops at the first failing step; reaching the end means every listed step exited 0.

## Step 2: Create captures only in fresh directories

Every capture command (`research.py`, `robustness.py`, `factorial.py`, `annotation_packet.py`, `detection.py`, `event_evaluation.py`, `cohort_registry.py`, `cohort_evaluation.py`) writes a new manifest and artifact set into a previously nonexistent `research-runs/<run-id>` path and refuses existing outputs. Command forms and option semantics are documented in the [README reproduce section](../README.md#reproduce) and the lane quickstarts linked below; this runbook does not restate sampling, metric or evaluation definitions.

- Capture directories and receipt files are always fresh: nothing overwrites an existing run, packet, report or receipt.
- Never rerun a frozen study or detector to recreate an output. A frozen capture that cannot be reproduced from its documented protocol is a finding to report, not a rerun trigger.
- Existing captures (`research_results/`, `results.csv`, `suppression.csv`, rendered PNGs) are retained byte-for-byte as the original evidence. Do not regenerate, rename or overwrite them.

## Step 3: Render from captured values only

`render_study.py`, `render_robustness.py`, `render_factorial.py` and `render_cohort.py` read an existing captured `summary.csv` and draw a chart at a fresh output path. They import no scientific module, recompute nothing and never rerun the underlying study or detector. If a `summary.csv` is missing or fails checks, the capture is incomplete: record the gap; do not fill it by rerunning frozen code.

## Step 4: Verify listed bytes and file a fresh receipt

```sh
.venv/bin/python verify_capture.py CAPTURE_DIR
.venv/bin/python verify_capture.py CAPTURE_DIR --output research-runs/NEW_RECEIPT.json
```

The verifier checks only the artifact bytes the capture's `manifest.json` lists, under the complete schema-v1 envelope. It exits 0 and emits a receipt on success, or exits 2 with a brief error and no receipt on failure. `--output` is itself a fresh file: the parent must exist, the name must be unused, and the check runs before any input is read. Semantics are in the [capture-integrity quickstart](2026-11-09-capture-integrity.md); the authoritative contract is the [integrity specification](2026-11-09-integrity-spec.md).

A failed verification is evidence, not a repair task:

- Do not edit the manifest or artifacts to make a corrupt capture pass, and do not weaken the checks for older captures that lack the complete-v1 envelope; they stay unsupported and unchanged.
- Keep the original directory exactly as found, record the command, its real exit code and stderr, and escalate to the lead.

## What reproduction does not establish

- A passing suite and a verified receipt mean the software ran and the listed bytes did not change. They establish nothing about completeness, authenticity, label truth, source-code identity, split independence, detector accuracy or field performance.
- All study outputs remain synthetic and non-field-validated; reproducing them changes no scientific claim. Private data handling and retention rules are in [responsible data handling](responsible-data-handling.md).

## See also

- Fixed protocols: [`field_protocol.json`](../field_protocol.json), [`event_protocol.json`](../event_protocol.json), [`cohort_protocol.json`](../cohort_protocol.json), [`robustness_protocol.json`](../robustness_protocol.json), [`factorial_protocol.json`](../factorial_protocol.json).
- [Recorded-video event evaluation quickstart](2026-11-08-video-evaluation.md)
- [Cohort evaluation quickstart](2026-11-09-cohort-evaluation.md)
- [Data-collection checklist](data-collection-checklist.md)
- [Capture integrity quickstart](2026-11-09-capture-integrity.md) and [integrity specification](2026-11-09-integrity-spec.md)
- [Research project brief](research-project-brief.md) and [research roadmap](research-roadmap.md)
