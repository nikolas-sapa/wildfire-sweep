# Assumption robustness study

## Test Plan, Before Implementation

1. `test_paired_delta_is_event_weighted`: counts `[1, 0]` versus `[0, 0]`
   with totals `[1, 100]` yield exactly `100/101` percentage points, not 50.
2. `test_pairing_preserves_zero_difference`: identical arms yield exactly
   `(0, 0, 0)` even with different season sizes.
3. `test_paired_resampling_matches_manual_draws`: three seasons and 100
   bootstrap draws match independently calculated paired ratios to 12 places.
4. `test_invalid_counts_fail`: mismatched shapes, fractional/negative/nonfinite
   counts, successes above totals, and invalid replicate counts raise errors.
5. `test_empty_denominator_is_not_success`: all-zero totals yield no estimate;
   one season yields a point estimate but no interval.
6. `test_response_accounting_keeps_rejections`: responses `[900, 901, inf]`
   yield one timely, one late, one rejected, and unreachable pooled p90.
7. `test_protocol_grid`: exactly 20 unique scenarios, actual base counts 9/25,
   and exactly 26 predefined contrasts. Reference and combined parameters
   match the protocol exactly.
8. `test_repeated_runs_match_and_refuse_overwrite`: two 2-season runs with the
   same seed yield identical CSVs and numeric captures. Existing output raises
   `FileExistsError`; invalid run parameters create no output directory.
9. `test_capture_and_manifest_integrity`: captured inputs have three offsets
   for two seasons; each response vector has one value per real alert;
   season accounting closes exactly; manifest file hashes match file bytes.
10. `test_renderer_rejects_invalid_capture`: duplicate/missing scenarios and
    nonfinite/out-of-range shares fail. Rendering never imports the simulator
    or overwrites an existing output.
11. Negative control: deliberately unpair the bootstrap arm in an isolated
    scratch copy. Test 3 must fail. Keep repository source unchanged.
12. Final gate: full unittest discovery, all three historical `--check`
    commands, a real 200-season run, and rendering from its captured CSV.

## Design

Extend research through a separate `robustness.py`, not changes to the existing
dispatcher. `robustness_protocol.json` fixes the design before execution.
This is a prospective local protocol, not an externally registered study.

Two layouts, two fixed winds, and five conditions give 20 scenarios. Endurance
34.5 minutes is a hypothetical 25% reduction from 46 minutes. Larger reserve is
35% of the selected endurance, including in the combined condition. Launch
latency consumes fleet busy time, not airborne battery time, as in `research.py`.
All scenarios use 18 m/s airspeed, one drone per base, and the same 200 synthetic
seasons. Threshold: 900 seconds, inclusive.

Generate alerts once using the unchanged `generate_season`. Use
`SeedSequence([0, season, seed])`; the bootstrap uses `[1, seed]`, a disjoint
namespace. Save sorted times, locations, truth flags and offsets before
dispatch. False alerts consume fleet time but do not enter the real-alert
denominator. All scenarios share exactly the same real and false alerts.

Report event-weighted timely, rejected and late shares; pooled nearest-rank
p90 includes infinite rejected responses. Blank p90 plus
`p90_unreachable=True` denotes infinity. No alerts means missing metrics,
not perfect service.

Paired contrasts resample whole season indices identically for both arms.
For each draw, compute
`100 * sum(candidate_timely - reference_timely) / sum(real_alerts)`.
Use 1,000 draws and NumPy's default linear 2.5/97.5 percentiles. Exclude
zero-denominator bootstrap draws. Report missing intervals with fewer than
two seasons. Intervals are pointwise Monte Carlo intervals, not input/model
uncertainty, simultaneous coverage, or field-effect confidence intervals.

## Interfaces And Outputs

- `paired_interval(candidate, reference, totals, seed, replicates=1000)` returns
  `(delta_pp, low_pp, high_pp)`.
- `response_counts(response_s)` returns integer counts `real_alerts`,
  `within_15min`, `rejected`, `served_late`.
- `scenario_grid(protocol)` returns the fixed scenario metadata.
- `run_robustness(output, seasons=200, seed=20261108)` creates a fresh directory
  and returns summary rows.
- CLI: `python robustness.py --output PATH [--seasons N] [--seed N]`.
- Outputs: `alerts.npz`, `responses.npz`, `seasons.csv`, `summary.csv`,
  `comparisons.csv`, and `manifest.json`, written last to mark completion.
- Manifest: complete protocol/config, source hashes, artifact hashes, numeric
  environment versions, Git revision/dirty flag, random-stream definitions.
- Summary columns include scenario, condition, layout/mission parameters,
  integer event counts, timely share and marginal Monte Carlo interval,
  rejection/late shares, p90/infinity marker, and historical proxy model cost.
- Comparisons: kind (`stress` or `density`), candidate/reference scenario IDs,
  real-alert count, `delta_within_15min_pp`, `mc_95ci_low_pp`,
  `mc_95ci_high_pp`. Positive means candidate reaches more alerts on time.
- `render_robustness.py SUMMARY --output PNG` reads captured CSV only.
  Two panels (9/25 bases), five conditions each, two fixed winds and captured
  timely-share error bars. No metric recomputation or simulation import.

## Non-Goals

No new aircraft physics, stochastic weather, geography, learned detectors,
hardware control, flights, dataset downloads, cost validation, or changes to
frozen evidence. Stress levels are declared assumptions, not measured derating
or recommendations for operating aircraft.

## Implementation Order

Land numeric tests and protocol first. Author the scientific runner directly.
In parallel, implement the capture-only renderer and reproducibility automation.
Run numeric checks and the negative control before the full study. Freeze the
captured inputs and results, check counts/contrasts, then write findings from
that capture only. Review all code, verify software, and push approved work.
