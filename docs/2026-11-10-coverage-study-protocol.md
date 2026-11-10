# Coverage Atlas Numerical Protocol

This extends the frozen Mission Lab models, not their assumptions. The
implementation contract defines the 388 scenarios before capture.

## Estimand

For each scenario, count the equal-area cell centers whose independent,
initially idle mission arrives within 900 seconds. Divide by the grid's cell
count. This approximates potential timely area, not season service,
probability of fire detection, risk-weighted coverage or weather availability.

## Design

- 388 fixed scenarios, exactly as coverage_scenarios.make_scenarios().
- Three deterministic cell-center grids: 40x40, 80x80 and 160x160, all scenarios.
- The 80x80 capture is the interactive atlas's default.
- Refinement changes only spatial quadrature. No random seeds, new aircraft
  assumptions, queueing or additional scenario selection.
- Run each resolution into a fresh directory, never overwrite or rerun an
  already captured resolution to adjust its results.

## Comparisons

- Healthy/reference potential timely area by layout and each wind direction.
- Single-outage loss relative to the healthy case with identical layout,
  direction, wind and reference aircraft assumptions.
- Selected two-outage loss relative to that same matched healthy case.
- Healthy stress profiles relative to the matched healthy/reference case.
- Within the enumerated matrix, describe largest observed losses and ranges.
  Do not call the selected two-outage pairs exhaustive or optimal.
- For each matched scenario, report signed 40-minus-160 and 80-minus-160
  percentage-point differences. Report their maximum absolute values over all
  388 cases. A 160x160 grid is a finer comparison, not ground truth.

These are descriptive deterministic comparisons. No confidence intervals,
p-values, held-out claims, adversarial optimization or equal-budget comparison.
Denser layouts use more infrastructure. Numerical sensitivity is not a formal
error bound or evidence of field performance.

## Verification And Presentation

The vectorized engine must match the existing single-alert dispatcher:
120 detailed point comparisons, one additional point in every scenario,
deadline/battery boundaries and original base IDs. An intentionally wrong
return leg must fail the existing oracle test.

Each capture binds source hashes, scenario order, coordinates, arrays and
summary counts. Checksum corruption and a rehashed but inconsistent summary
must be rejected. Derived tables/plot inputs read those frozen captures once
and record all three manifest hashes. Plotting reads only frozen derived
presentation inputs, never reruns the model.
