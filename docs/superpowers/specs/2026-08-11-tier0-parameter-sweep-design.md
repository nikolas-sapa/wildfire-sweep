# Tier 0 Parameter Sweep — Design

Date: 2026-08-11
Project: wildfire-drone-swarm
Status: approved, ready for implementation plan

## Purpose

Produce the missing investor number: **time-to-eyes-on vs €/km²/yr** for a
monitor-drone base network. This is checklist item #3 in the project index
(cost breakdown + build timeline) and the "pitchable number front-loaded
before the physics step" that the 2026-07-28 handoff calls for.

It answers that question **without a simulator existing**. No Cell2Fire, no
Mesogeos, no PX4, no Gazebo.

## Non-goals

Explicitly out of scope. Do not add these:

- Fire growth or perimeter shape. Fires are points.
- Real terrain, elevation, or geographic coordinates.
- Wind as an independent axis (folds into the cruise-speed knob).
- 3D flight physics. Tier 2 owns that, for one demo scenario, never for sweeps.
- Suppression / water-drop modelling (Sweep B, later, same harness).
- Any cloud or paid compute.
- Any test framework, fixtures, or per-function test suite.

## Context: why Tier 0 exists

Parameter sweeps need ~10³–10⁴ runs. PX4/Gazebo runs near real-time, so
full-physics sweeps are months of wall-clock for numbers a closed-form model
gives in minutes. The dual-mode drone interface already in the simulator spec
exists for exactly this split. Tier 0 is the light mode, standalone.

The recorded owner decision (full 3D physics, chosen twice) stands and is not
revisited here. Tier 2 renders **one** config as video. It never sweeps.

## Architecture

One Python file, `sweep.py`, in this repo. Dependencies: `numpy`,
`matplotlib`. Nothing else.

### CONFIG block

All tunables and all euro figures live in a single dict at the top of the
file. Cost values are placeholder public-market estimates, flagged as such,
and are swapped for real quotes later without touching any logic.

| Key | Placeholder | Note |
|---|---|---|
| `drone_cost` | €15,000 | multirotor + thermal payload |
| `base_cost` | €35,000 | ruggedised drone-in-a-box, power, comms |
| `install_cost` | €20,000 | civil works, connectivity, permitting |
| `maintenance_frac` | 0.15 | of capex, per year |
| `hardware_life_yr` | 5 | amortisation period |
| `domain_km2` | 3808 | Attica-sized square |
| `season_days` | 120 | fire season |
| `ignitions_per_season` | swept | Poisson mean — see Sweep; **unverified**, no Greek source yet |
| `dwell_s` | 120 | time overhead the fire before returning |
| `turnaround_s` | 600 | battery swap / dock cycle |
| `unserved_threshold_s` | 900 | above this counts as a miss |

### Units

Five units, each with one purpose, each independently testable.

**1. World.** Generates one season over `season_days`. Real fires and false
alarms are drawn as **two independent Poisson processes**:

- `n_real ~ Poisson(ignitions_per_season)` — so `ignitions_per_season` means
  REAL fires, not total alerts.
- `n_fake ~ Poisson(ignitions_per_season × fp_rate / (1 − fp_rate))` — false
  alarms are ADDITIONAL alerts on top of the real ones. The multiplier makes
  the expected false-alarm share of all alerts equal `fp_rate`.

Both get uniform-random locations and times; the combined arrays are sorted
together by time, since `dispatch` consumes alerts in time order.

> **Corrected 2026-08-11 after the final review.** The original wording here
> drew the TOTAL alert count as Poisson and then relabelled an `fp_rate` share
> as fake. That made the false-positive axis inert: raising `fp_rate` deleted
> real fires instead of adding drone load, the opposite of the intent stated
> below. Measured on the first full sweep, fp 0.05→0.50 moved p90 by −0.4%
> and utilisation by −0.00001. Tier 1 must not reintroduce this.

**2. Bases.** Square grid at spacing `S` over the domain. `n_bases` derives
from `S` and `domain_km2`. Each base holds `D` drones.

**3. Dispatch.** On an alert, the nearest base with a free drone launches one.
That drone is unavailable for
`launch_latency + t_out + dwell + t_back + turnaround`, where
`t_out = t_back = distance / cruise_speed`. If no drone is free anywhere, the
alert queues until one frees and the wait is recorded. False alarms consume
drones identically to real fires — that coupling is the entire reason the
false-positive rate is an axis.

**4. Metrics.** Computed over **real** ignitions only:
- time-to-eyes-on p50 and p90 (alert timestamp → arrival overhead)
- share of real ignitions unserved past `unserved_threshold_s`
- drone utilisation

**5. Cost.** `n_bases × (base_cost + install_cost + D × drone_cost)`
amortised over `hardware_life_yr`, plus annual maintenance, divided by
`domain_km2` → €/km²/yr.

## Sweep

`itertools.product` over:

| Axis | Range |
|---|---|
| base spacing | 5–40 km |
| drones per base | 1–6 |
| launch latency | 30–180 s |
| false-positive rate | 5–50% |
| ignitions per season | 50 / 150 / 400 |

≈2,880 configs × 200 Monte Carlo seasons each. Vectorised per season with
numpy. Target: minutes on a laptop. If a full sweep exceeds ~30 minutes,
reduce Monte Carlo count before reaching for parallelism.

**Ignition density is swept, not assumed.** No verified Greek figure exists
yet, and the number sets how hard the fleet is stressed and how much the
false-positive rate bites. A single low guess would make thin configs look
survivable when they are not. Three levels — a quiet season, a busy one, and
a bad one — bracket the uncertainty, so the output shows *at what density* a
given base spacing stops holding rather than asserting that it does.

Getting a real Attica ignition-density figure (EFFIS or Hellenic Fire Service
statistics) is a research task, not a blocker. When it lands, it selects which
of the three levels is the headline chart; the sweep does not need rerunning.

Cruise speed is a CONFIG constant, not an axis, and absorbs wind derating.

## Data flow

```
CONFIG ──> Bases(S, D) ─────┐
                            ├──> Dispatch ──> per-ignition latencies
CONFIG ──> World(season) ───┘                        │
                                                     v
                                          Metrics (p50/p90/unserved)
                                                     │
CONFIG ──> Cost(n_bases, D) ─────────────────────────┤
                                                     v
                                       results.csv + pareto.png
```

## Outputs

- `results.csv` — one row per config: all four axis values, p50, p90,
  unserved share, utilisation, €/km²/yr.
- `pareto.png` — €/km²/yr on x, p90 time-to-eyes-on on y, points coloured by
  spacing, Pareto frontier highlighted. One panel per ignition-density level,
  so the frontier's sensitivity to density is visible rather than hidden. This
  is the investor slide.

## Error handling

Fail loud at startup, not mid-sweep. Validate on load: spacing produces at
least one base, rates are in [0,1], all costs and durations positive. A
config that yields zero bases is a config error, not a silently-skipped row.

Any config where an alert queues past the end of the season is recorded as
unserved rather than dropped, so pathological configs show up in the output
as bad numbers instead of disappearing.

## Testing

One `assert`-based `demo()` called from `__main__`. No framework, no
fixtures. It must cover:

1. **Degenerate geometry.** One base, one drone, zero launch latency, zero
   false alarms, ignition at a known distance → time-to-eyes-on equals
   `distance / cruise_speed` within float tolerance.
2. **Monotonicity.** Holding all else equal, decreasing base spacing must
   never increase p90. Decreasing drones-per-base must never decrease p90.
3. **Cost arithmetic.** A hand-computed single-base, single-drone case
   matches the cost function output.

If the dispatch logic breaks, test 1 or 2 fails. That is the whole point of
having them.

## Build order

1. CONFIG + Cost + its assert. Cheapest, and validates the euro figures early.
2. World + Bases.
3. Dispatch + degenerate-geometry assert.
4. Metrics + monotonicity assert.
5. Sweep loop + CSV.
6. Chart.

Stop and look at the numbers after step 5. The chart is presentation; the CSV
is the answer.

## What comes after

- **Sweep B (suppression)** rides this harness. One afternoon, after Tier 0
  lands. Its expected output is a *negative* result — the fleet size needed to
  hold a fire line — used to close the "why not water drops" question in
  investor meetings. Do not fund it beyond that.
- **Tier 1** swaps the point-fire World for Cell2Fire + Mesogeos. Same
  harness, same sweep, credible perimeter. Only worth building at LOI time.
- **Tier 2** is PX4 + Gazebo, one scenario, recorded as video.
