# Held-out single-base outage study

## Research Question

How much timely service is lost when a training-identified critical base is
unavailable, and does the 25-base layout lose less than the 9-base layout?
This is a new synthetic experiment, not more integrity tooling or field evidence.

## Test Plan Before Implementation

Lead-authored numerical tests, not agent-designed scoring:

1. `test_baseline_dispatch`: no-outage geometry exactly equals base_grid;
   existing dispatch responses match elementwise, including infinity.
2. `test_one_site_removed`: each candidate removes exactly one original site,
   9 becomes 8, 25 becomes 24; original coordinates remain unchanged.
3. `test_training_selection_and_ties`: select minimum pooled training timely
   count; tie chooses lowest row-major base index. Function has no held-out
   argument or reference. Synthetic counts [8,3,3] select site1.
4. `test_pooled_interval`: successes [1,9], totals [1,99], fixed draws
   [[0,0],[0,1],[1,0],[1,1]] yield estimate10%, low9.1590909091%,
   high93.25%, not mean-of-season ratios.
5. `test_paired_loss`: [0,0]-[1,9] with the same totals/draws yields
   -10 percentage points, bounds -93.25,-9.1590909091.
6. `test_loss_difference`: numerator [0,0]-[1,9]-[0,0]+[0,5] gives
   -5 percentage points. Shared season indices, no independent resampling arms.
7. `test_undefined_and_output_refusal`: zero real-alert denominator returns
   null estimate/bounds; existing output sentinel preserved, no rerun.
8. `test_small_capture`: two train/two test seasons, three expected ignitions
   per season, otherwise same protocol. 72 training cases, four frozen site
   selections, eight held-out cases, six contrasts, exact artifact checksums.

Negative controls: half-scale the contrast numerator, and reverse training
selection from minimum to maximum in OWNED copies; corresponding tests fail
real assertions. No edits to historical models or captures.

## Predeclared Design

- Existing 9/25-base cell-centred square grids, one drone per base.
- Existing reference flight assumptions: airspeed18m/s, endurance46min,
  reserve25%, launch60s, fixed east wind8 or12m/s, wind limit12m/s.
- Existing CONFIG and generator, 307 expected real alerts/120-day season,
  false-alarm share15%. False alarms still consume fleet time.
- A candidate outage removes one base and its drone for the entire season.
  No relocation, spare aircraft, correlated failures or failure probabilities.
- Root seed2026110901. Thirty training seasons use
  SeedSequence([0,season,seed]); 200 NEW held-out seasons use
  SeedSequence([1,season,seed]). No previous frozen alerts reused.
- Training exhaustively evaluates 9+25 single-site outages at each wind,
  plus four healthy baselines:72 cases. For each layout/wind select the
  minimum pooled timely real-alert count, ties lowest original base index.
- Freeze selection.csv and its SHA-256 BEFORE generating held-out inputs.
  Test evaluates only the four baselines and four frozen selected outages.
  Test results cannot change site selection.
- Primary outcome unchanged: fraction of ALL real alerts reached within900s
  of receipt. Rejected missions remain denominator failures.
- Four paired outage-minus-healthy contrasts, one per layout/wind. Two
  difference-in-loss contrasts: (outage25-healthy25)-(outage9-healthy9).
  Positive difference means the denser layout has a smaller service loss.
- One shared1000x200 season-index bootstrap matrix, default_rng([2,seed]).
  Pooled rates and signed contrasts use the SAME draws/denominators.
  Pointwise percentile2.5/97.5% intervals quantify Monte Carlo variability only,
  conditional on frozen training selection. No selection/input uncertainty or
  simultaneous-coverage claims.

## Implementation Plan

New lead-authored resilience.py and resilience_protocol.json. Reuse existing
dispatch_physical, MissionConfig, base_grid, generate_season, response_counts.
No changes to those functions or any existing protocol.

Capture protocol/config/source hashes, every generated alert, every candidate
geometry, all training/held-out responses, season counts, training scores,
frozen selection, exact bootstrap draws, held-out summary and contrasts.
Fresh exclusive output directory only; complete manifest written last.
Source and selection hashes rechecked before completeness.

Renderer/report read frozen captures only, no simulator imports or reruns.
Lead independently audits the raw captures before any reported numerical claim.

## Non-Goals

No measured outage probability, real optimal site, weather forecast, real
geography, detector integration, new physics, autonomous flight or deployment.
The selected site is training-worst, not guaranteed worst on held-out data.
Dense layouts use more infrastructure; this is not equal-budget optimization.
No promise the hypothesis will be supported. Null/negative findings published.
