# Full-Factorial Extension

## Acceptance Tests, Before Implementation

1. `test_additive_cube_has_zero_interactions`: a cube of percentages
   `80 - 10*E - 20*L - 5*R` yields main differences -10/-20/-5 points and
   exactly zero second/third differences.
2. `test_pair_interaction_is_full_difference_in_differences`: adding `-8*E*L`
   yields E/L main differences -14/-24, EL difference -8 and other
   interactions zero, to 12 decimal places.
3. `test_triple_term_scales_correctly`: `50 + 4*E*L*R` yields main differences
   1, pair differences 2 and third difference 4, not half-scaled effects.
4. `test_event_weighting_not_mean_season_share`: one additional timely event
   in one of 101 real alerts yields `100/101` points, not 50.
5. `test_bootstrap_matches_manual_paired_draws`: a 3-season, 8-cell cube
   with 100 seeded draws matches an independent nested-loop estimator to
   12 places, preserving identical season indices across all eight cells.
6. `test_invalid_inputs_fail`: wrong cube shape, fractional/negative/nonfinite
   counts, successes above totals, invalid subsets and replicate counts fail.
7. `test_empty_counts_are_missing`: zero totals give no estimate; one season
   gives a point estimate but no interval.
8. `test_grid_and_reuse`: 32 cells, exactly 20 reused and 12 newly simulated;
   no duplicate IDs, each context contains all eight factor bit patterns.
9. `test_only_missing_cells_are_dispatched`: a 2-season source produces
   exactly 24 dispatcher calls, not 64, and does not change any source bytes.
10. `test_reused_results_are_copied`: all 20 reused summaries and season
    counts equal source values; no re-estimation of their marginal intervals.
11. `test_repeat_and_overwrite`: two runs from the same source produce
    identical CSVs/numeric arrays; existing output is refused.
12. `test_source_tamper_fails_before_output`: bad source artifact hash,
    unsupported configuration or incomplete source fails before creating output.
13. `test_capture_integrity`: all artifact hashes match, 12 new response
    vectors have shared offsets and per-cell counts close exactly.
14. Negative control: in an in-memory mutant, divide every contrast by two.
    The analytic pair and triple tests must reject it.
15. Published evidence check: all 32 cells, 6,400 season rows and 28 contrasts
    close against source/new captures and an independently implemented estimator.
16. Final software gate: full unittest discovery and three historical checks.
    Renderer rejects duplicate/missing/nonfinite rows and refuses overwrite.

## Design

The previous five-condition study could not identify all interactions.
Complete the 2x2x2 endurance/launch/reserve cube within each of its four
layout/wind contexts. Read the original alerts and 20 captured results.
Only simulate the three missing pairwise-stress combinations in each context.
This adds 12 scenarios, not 32 reruns and not an independent replication.

Factor order is E (endurance), L (launch), R (reserve). Zero denotes reference,
one stressed. E: 46/34.5 min; L: 60/180 s; R: 25/35%. All values remain
unmeasured assumptions. Contexts: 9/25 bases and fixed 8/12 m/s eastward wind.
The existing physical dispatcher, 18 m/s airspeed, alert threshold and inherited
cost/configuration are unchanged.

For a nonempty factor subset S, compute the signed finite difference within S,
then average over every combination of the other factors. Equivalently each
cell receives coefficient:

```text
(-1) ** (len(S) - sum(selected_bits)) / 2 ** (3 - len(S))
```

For each season, apply these coefficients to the eight timely-event counts.
The point estimate is `100 * sum(signed_counts) / sum(real_alerts)`.
Resample complete seasons identically for all eight cells, using the source
study's `[1, seed]` bootstrap stream, 1,000 draws and linear 2.5/97.5 percentiles.
Main differences average over the other factors. Pair terms are full
differences-in-differences averaged over the third factor. The triple term is
the difference between pair differences at the two levels of the third factor.
These are not the half-scaled orthogonal effects used by some DOE packages.

Report 7 contrasts per context, 28 total, without selecting by significance.
Their intervals are pointwise Monte Carlo sampling intervals, not simultaneous
coverage, global sensitivity, empirical causal effects or uncertainty bounds
over operating assumptions.

## Interfaces And Capture

- `factorial_interval(successes, totals, factors, seed, replicates=1000)` takes
  an integer-count array of shape `(2, 2, 2, seasons)` and factor-index tuple.
  Returns `(contrast_pp, low_pp, high_pp)`.
- `factorial_grid(protocol)` yields 32 scenario dictionaries, IDs such as
  `b9-w8-e1-l1-r0`, with bit fields `endurance_stress`, `launch_stress`,
  `reserve_stress`, condition, mission metadata, and `provenance` equal to
  `reused` or `simulated`.
- `run_factorial(output, source=DEFAULT_SOURCE)` returns 32 summary rows.
  Source manifest determines seed/seasons; CLI never regenerates alerts.
- CLI: `python factorial.py --output PATH [--source CAPTURE]`.
- Outputs: `summary.csv` (32 cells), `seasons.csv`, `effects.csv` (28 contrasts),
  `new_responses.npz` (12 new vectors plus offsets), `manifest.json` written last.
- Summary uses the prior study's metric names and metadata, adds three bit
  fields and provenance; reused metrics are copied from the source CSV.
- Effects columns: `n_bases`, `wind_east_mps`, `factors` (joined by `+`),
  `difference_order`, `real_alerts`, `contrast_pp`, `mc_95ci_low_pp`,
  `mc_95ci_high_pp`.
- Manifest fingerprints source manifest/artifacts, executed source files,
  inherited config/protocol, environment, reused IDs and new IDs.
- No duplicate storage of old alert/response arrays. Retain the referenced
  source capture for complete replay.
- `render_factorial.py SUMMARY --output PNG` plots captured shares/intervals
  in four context panels, eight discrete conditions each. Mark reused/new
  points distinctly. No scientific imports or metric recomputation.

## Non-Goals

No alteration of frozen evidence or prior source scripts. No new aircraft
physics, field data, live integration, detection metrics, cost validation,
weather probabilities or additional dependencies. No claim that all relevant
operating factors are included. This completes only the declared two-level,
three-factor design.
