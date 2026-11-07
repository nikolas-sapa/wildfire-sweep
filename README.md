# Wildfire sweep

## Scope

`sweep.py`, `suppression.py`, and `sensitivity.py` are historical analyses. Their existing outputs and assumptions remain unchanged. `research.py` is a separate analytical wind-and-battery dispatch study; each run records its assumptions in its manifest.

The response-time metric runs from alert receipt to drone arrival; upstream detector latency is excluded. The frozen anchor manifest records 307 expected real ignitions per season, false-alarm fraction 0.15, launch latency 60 s, airborne endurance 46 min with 25% reserve, and maximum model wind 12 m/s. The captured anchor run covers 36 fixed-wind scenarios with 200 seasons each, `SeedSequence` common random numbers, and 61,538 real alerts per scenario; this alert count is specific to the captured run.

Rejected alerts remain in the timely-share denominator. The pooled nearest-rank alert-to-arrival p90 uses that denominator and can be unreachable. Do not equate it with the historical frontier's mean-of-season p90 or its other launch settings.

## Captured synthetic results

The following values are from the frozen `research_results/2026-11-07-anchor/summary.csv`:

| Physical configuration | Fixed conditions | Within 15 min | Physically rejected | Cost |
| --- | --- | ---: | ---: | ---: |
| 9 bases, 1 drone/base | 18 m/s; winds 0, 8, 12 m/s | 99.76%, 91.08%, 60.11% | 16.40% at 12 m/s | 100.98 EUR/km²/yr |
| 25 bases, 1 drone/base | 18 m/s; 12 m/s wind | 97.51% | 0% | 252.48 EUR/km²/yr |

For 9 bases and 1 drone/base at 18 m/s airspeed and 12 m/s wind, pooled p90 is unreachable/infinite. At zero wind, physical results can differ slightly from legacy because battery constraints can prevent distant fallback-base dispatch while nearby drones are busy. With unbounded endurance, the physical mode matches legacy.

These are fixed-wind synthetic scenarios, not forecast weather availability or field accuracy. Plotted intervals represent Monte Carlo sampling uncertainty only. They are not field validation. The published anchor chart is `research_results/2026-11-07-anchor/service.png`.

## Setup and verification

Use Python 3.10 or newer. FFmpeg must be installed separately.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -v
.venv/bin/python sweep.py --check
.venv/bin/python suppression.py --check
.venv/bin/python sensitivity.py --check
```

Run a new analytical study only into a fresh output directory:

```sh
.venv/bin/python research.py --output research-runs/my-study --seasons 200
```

Render an existing captured summary. The renderer reads summary values only; it does not import or rerun `research.py`, `sweep.py`, or other study code. Output must be a new PNG path, and its parent directory must already exist.

```sh
.venv/bin/python render_study.py research-runs/my-study/summary.csv --output research-runs/my-study/service.png
```

The renderer selects physical-mode rows for 18 and 20 m/s airspeed, winds 0, 4, 8, and 12 m/s, and configurations of 4 bases/2 drones per base, 9/1, 25/1, and 49/1. It uses the recorded timely-share confidence bounds as supplied and converts shares to percentages by multiplying by 100.

## Recorded-video tooling

The detector accepts local videos and requires externally installed FFmpeg:

```sh
.venv/bin/python detection.py LOCAL_VIDEO --output research-runs/my-video --recording-id event-001
```

Optional labels use CSV columns `recording_id,sample_index,fire,split`:

```sh
.venv/bin/python detection.py LOCAL_VIDEO --output research-runs/my-video --recording-id event-001 --labels labels.csv
```

Labels must cover every decoded sampled index exactly once; `sample_index` is not the original source-frame index. For test evaluation, hold out entire recordings and mark them `split=test`; do not split frames from one recording across partitions. The color baseline is not smoke detection and does not produce calibrated probabilities. No detector accuracy is established without labels. Frames are resampled to 640x360 RGB with aspect ratio normalized.

No datasets or ML weights are bundled, and the tools do not download them. The processed FLAME demo animation comes from the original repository at commit `40e950b8eea89145f5dd1df07b7ba921434e3fcc`; it is an I/O smoke-test input only, not independent ground truth. Do not redistribute it or infer accuracy or performance from it. Published processed-demo manifest, predictions, and provenance are under `research_results/flame-demo`; they are not accuracy evidence.

## Open-data entrypoints

These are candidate sources, not endorsements or download instructions. Check dataset-specific terms before acquisition.

- **FLAME 3:** [paper](https://arxiv.org/abs/2412.02831) and [IEEE DataPort](https://ieee-dataport.org/open-access/flame-3-radiometric-thermal-uav-imagery-wildfire-management). Single-burn imagery cannot establish cross-site generalization.
- **Original FLAME:** [repository](https://github.com/AlirezaShamsoshoara/Fire-Detection-UAV-Aerial-Image-Classification-Segmentation-UnmannedAerialVehicle) and [IEEE DataPort](https://ieee-dataport.org/open-access/flame-dataset-aerial-imagery-pile-burn-detection-using-drones-uavs). The repository README restricts academic/non-commercial use while its LICENSE reports GPL-2.0; verify dataset terms independently. Processed demo animations are not independent ground-truth validation.

`field_protocol.json` describes a proposed protocol, not flight authorization. This repository contains no real-flight control.
