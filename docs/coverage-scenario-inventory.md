# Coverage scenario inventory

This document inventories the scenario registry evaluated by the coverage
atlas (`coverage_scenarios.make_scenarios()`), as contracted in the
[implementation spec](2026-11-10-coverage-atlas-spec.md). It describes what
the fixed design contains and what it omits. It is a spatial single-alert
approximation: each scenario is evaluated independently at every equal-area
cell center of the synthetic square domain by an initially idle network.

This differs from the repository's season experiments (for example the
`2026-11-09-resilience` study), which simulate streams of alerts across
120-day seasons with fleet contention and Monte Carlo intervals. The atlas
has no seasons, no alert streams, no queueing, and no intervals; it maps
where one independent alert can be reached within the 900-second deadline.
It is not a season success rate, ignition-risk estimate, forecast, detector
result, geographic map, or flight-control system.

## Exact counts

The registry contains exactly **388 unique ordered scenarios**:

| Group | Construction | Count |
| --- | --- | ---: |
| Healthy + all single-site outages | 8 headings x (1 healthy + 9 singles) + 8 headings x (1 healthy + 25 singles) = 8 x (10 + 26) | 288 |
| Selected outage pairs | 2 pairs x 8 headings x 2 layouts | 32 |
| Healthy stress profiles | 4 profiles x 8 headings x 2 layouts | 64 |
| Calm reference | 1 per layout | 2 |
| Weather-closed | 1 per layout | 2 |
| **Total** | 288 + 32 + 64 + 2 + 2 | **388** |

Per layout, the 9-base layout contributes 8 x (1 + 9 + 2 + 4) + 2 = 130
cases and the 25-base layout contributes 8 x (1 + 25 + 2 + 4) + 2 = 258
cases. These are a fixed designed set over the declared axes below, not
coverage of all possible scenarios.

## Layouts

Scenarios use the existing 9- and 25-base layouts from
`simulator_engine.layout_bases` (nominal spacings 16.0 km and 12.0 km over
the ~61.71 km side of the 3808 km2 synthetic domain). Outages reference
original base identifiers; unavailable sites keep their original IDs rather
than being reindexed. Each available site contributes one initially idle
aircraft; there is no queueing or fleet contention.

## Wind directions

Eight headings span `range(0, 360, 45)` at a nominal 12 m/s. Heading is the
direction toward which the wind blows in degrees, with east = 0 and
north = 90; `wind_mps` is the (x, y) component vector in the km frame where
positive y is north.

| heading_deg | Blows toward | wind_mps (x, y) |
| ---: | --- | --- |
| 0 | East | (12, 0) |
| 45 | Northeast | (d, d) |
| 90 | North | (0, 12) |
| 135 | Northwest | (-d, d) |
| 180 | West | (-12, 0) |
| 225 | Southwest | (-d, -d) |
| 270 | South | (0, -12) |
| 315 | Southeast | (d, -d) |

`d` is the single shared signed constant `12 / sqrt(2)`
(~8.485281374238571 m/s), not independently rounded trigonometric values.
This hypot-safe construction keeps every nominal heading's computed
magnitude at or below the model weather limit of 12 m/s; the limit itself
is unchanged. Two boundary families bracket that limit:

- **Calm:** `wind_mps` (0, 0), `wind_speed_mps` 0, `heading_deg` null. Calm
  is the only case family without a heading.
- **Weather-closed:** `wind_mps` (13, 0), `wind_speed_mps` 13, heading 0.
  Because 13 m/s exceeds the unchanged 12 m/s limit, every cell in these
  two cases is classified `weather_closed` with 0 served cells.

No other wind speeds are exercised: nothing between calm and 12 m/s, and no
above-limit speed other than 13 m/s.

## Outage sets

At every direction and layout, the design contains the healthy network and
every single-site outage (sites 0..8 for the 9-base layout, 0..24 for the
25-base layout), all under the reference profile.

In addition, exactly **two selected outage pairs** are evaluated per
direction and layout: `[0, 1]` and `[0, center_id]`, where `center_id` is
the geometric center site `(n_bases - 1) // 2`, site 4 in the 3x3 layout
and site 12 in the 5x5 layout. This is a fixed selection of 2 out of 36
possible pairs (9-base) or 300 possible pairs (25-base). It is **not**
exhaustive over all two-site combinations and is **not** an adversarial or
worst-pair optimization; no pair was chosen because it maximizes coverage
loss. Results for these cases must not be read as bounds on pair outages.

All outage scenarios use the reference profile; the registry contains no
outage-by-stress combinations.

## Stress profiles

Five profiles exist; `reference` carries the baseline aircraft assumptions
and four are healthy-network stress cases applied at every direction and
layout. `offline_bases` is always empty for the four stress families.

| profile | endurance_min | reserve_fraction | launch_latency_s |
| --- | ---: | ---: | ---: |
| reference | 46 | 0.25 | 60 |
| short_endurance | 36 | 0.25 | 60 |
| larger_reserve | 46 | 0.35 | 60 |
| slow_launch | 46 | 0.25 | 180 |
| combined | 36 | 0.35 | 180 |

Every varied value stays inside the existing sandbox parameter limits:
endurance [1, 120] min, reserve [0, 0.9], launch latency [0, 600] s,
airspeed [1, 40] m/s, so no limit or configuration change was needed.
Under the engine's existing eligibility rule, outbound flight time plus dwell
time plus return flight time must not exceed
`endurance_min * 60 * (1 - reserve_fraction)`. Launch latency adds only to
arrival time and the timely-deadline comparison; it does not reduce the
battery budget. The implied usable airborne budgets are 2070 s (reference and
slow_launch), 1620 s (short_endurance), 1794 s (larger_reserve) and 1404 s
(combined); the slow_launch profile instead widens the fixed 180 s delay added
to every response.

## Per-scenario fields and fixed values

Each descriptor carries exactly the frozen keys: `case_id` (opaque unique
string), `n_bases`, `wind_mps` (two numbers), `wind_speed_mps`,
`heading_deg` (null for calm), `profile`, `offline_bases` (sorted original
IDs), `airspeed_mps`, `endurance_min`, `reserve_fraction`,
`launch_latency_s`. Case IDs are opaque, for example
`b9-w12-h000-reference-offnone`, `b25-w12-h315-reference-off0_12`,
`b9-w0-calm-reference-offnone` and `b25-w13-h000-reference-offnone`; their
structure is shown here for orientation only.

Values shared by all 388 scenarios: airspeed 18 m/s, dwell 120 s, domain
side ~61.71 km, timely threshold 900 s, max wind 12 m/s, one aircraft per
site, no queueing. (Turnaround is part of the model but never applies
because every cell evaluation is a single idle-network alert.) The
reference profile's endurance/reserve/launch values equal the existing
sandbox defaults; only the stress axes above vary them.

Ordering is fixed by `make_scenarios()`: for each layout (9 then 25), each
of the eight headings emits the healthy reference case, every single-site
outage in ascending site order, the two selected pairs, then the four
stress profiles; the calm and 13 m/s weather-closed cases close each
layout's block.

## Stored per-case outputs

At the captured grid resolution (80 x 80 = 6400 cell centers, stored
y-major-x-fast with north at positive y), each cell holds an engine-computed
response in seconds (launch latency plus outbound flight time of the
earliest-arriving eligible base), the selected original base ID, and one of
four exclusive outcome codes: `unreachable` (0; no flight- or
battery-eligible base), `late` (1; served after 900 s), `timely` (2; served
within 900 s), `weather_closed` (3). Each case's stored summary reports the
four cell counts, `total_cells`, `timely_area_fraction` and
`reachable_area_fraction`; counts sum to 6400. Unserved cells store
infinite response and base -1, serialized as null, unavailable, never
zero. This document adds no metrics beyond those stored fields.

## Omissions and future work

The registry deliberately does not cover the following; each is a possible
extension, not a claim:

- **Terrain and geography.** The domain is a synthetic flat square. No
  terrain masking, obstacles, airspace restrictions, or real siting.
- **Ignition hotspots.** All cell centers are weighted equally; there is no
  ignition-likelihood or exposure weighting, so fractions are uniform-area
  approximations rather than risk-weighted coverage.
- **Concurrent events.** Every cell is an independent alert on an idle
  network. Multiple simultaneous alerts, fleet contention, and turnaround
  queuing, present in the season studies, are out of scope here.
- **Time-varying wind and weather.** Each case uses one fixed wind vector.
  No gusts, diurnal cycles, fronts, forecast scenarios, or wind speeds
  other than 0, 12 and 13 m/s.
- **Detection.** Alerts are assumed to exist at a cell center. Upstream
  detection latency, detector accuracy, missed detections, and thermal
  confirmation are not modeled.
- **Richer outage space.** Other two-site pairs, outages of three or more
  sites, partial-capacity sites, and outage-by-stress combinations are not
  in the design.
- **Other axes.** Additional layouts, aircraft counts per site, airspeeds,
  headings beyond the eight 45-degree increments, and cost dimensions are
  unchanged or unexplored.
- **Resolution.** The capture stores one 80 x 80 grid; the lead separately
  compares 40/80/160 resolutions as numerical sensitivity only, not
  confidence intervals or convergence guarantees.

## What this inventory does not claim

The 388 scenarios are a designed subset, not exhaustive coverage of the
parameter space, and no scenario here is evidence about all possible
scenarios. Results remain synthetic and non-field-validated: no detector
accuracy, forecast weather availability, real-world performance, geographic
siting, or flight approval is established. Sources: this document reflects
only `coverage_scenarios.py`, `coverage_engine.py`, `coverage_capture.py`,
`simulator_engine.py`, `simulator_protocol.json`, `research.py`, `sweep.py`
and the cited spec; it introduces no external literature claims.
