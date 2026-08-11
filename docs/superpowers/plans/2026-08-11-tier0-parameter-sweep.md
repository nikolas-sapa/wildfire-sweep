# Tier 0 Parameter Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `results.csv` and `pareto.png` answering "what does time-to-eyes-on cost per km²/yr" for a monitor-drone base network, with no simulator, no terrain, and no physics.

**Architecture:** One file, `sweep.py`. Five pure-ish functions (cost, bases, world, dispatch, metrics) wired by a sweep loop over `itertools.product`. Correctness is guarded by `assert`-based checks in a `--check` mode, not a test framework — this is a deliberate spec decision, not an omission.

**Tech Stack:** Python 3.11+, numpy, matplotlib. Nothing else.

## Global Constraints

- **One file.** All code lives in `sweep.py` at the repo root. Do not create a package, a `src/` tree, or a module per unit.
- **No test framework.** No pytest, no unittest, no fixtures. Checks are `assert` statements inside functions named `check_*`, run by `python sweep.py --check`.
- **Dependencies are numpy and matplotlib only.** Adding any third-party dependency is a plan violation.
- **All tunables and all euro figures live in the single `CONFIG` dict** at the top of `sweep.py`. No magic numbers below it.
- **Cost figures are unverified placeholders** and must carry a comment saying so: `# ponytail: placeholder, swap for real quotes`.
- **Ignition density is swept, never assumed.** Levels: 50 / 150 / 400 per season.
- **Fail loud at startup.** Config validation runs before any sweep work, not mid-loop.
- **Random numbers come from `np.random.default_rng(seed)`.** Never the global `np.random` functions — reproducibility matters for a chart shown to investors.
- **Distances are kilometres, times are seconds, money is euros.** Any variable mixing units carries a unit suffix in its name (`d_km`, `flight_s`).

---

### Task 1: Config, validation, and cost model

**Files:**
- Create: `sweep.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `CONFIG: dict`, `validate_config(cfg: dict) -> None`, `cost_per_km2_yr(n_bases: int, drones_per_base: int, cfg: dict) -> float`, `check_cost() -> None`.

- [ ] **Step 1: Write the failing check**

Create `sweep.py` with only this content:

```python
"""Tier 0 wildfire drone-swarm parameter sweep.

Answers: time-to-eyes-on vs EUR/km2/yr for a monitor-drone base network.
No terrain, no fire growth, no flight physics. See docs/superpowers/specs/.
"""

import sys


def check_cost():
    cfg = dict(CONFIG)
    cfg["domain_km2"] = 1000.0
    cfg["base_cost"] = 35_000.0
    cfg["install_cost"] = 20_000.0
    cfg["drone_cost"] = 15_000.0
    cfg["hardware_life_yr"] = 5.0
    cfg["maintenance_frac"] = 0.15

    # One base, one drone: capex = 35k + 20k + 15k = 70k.
    # Annual = 70k/5 + 70k*0.15 = 14_000 + 10_500 = 24_500.
    # Per km2 over 1000 km2 = 24.5
    got = cost_per_km2_yr(1, 1, cfg)
    assert abs(got - 24.5) < 1e-9, f"one-base cost wrong: {got}"

    # Cost is linear in base count.
    got10 = cost_per_km2_yr(10, 1, cfg)
    assert abs(got10 - 245.0) < 1e-9, f"cost not linear in bases: {got10}"

    # More drones per base costs strictly more.
    assert cost_per_km2_yr(1, 2, cfg) > cost_per_km2_yr(1, 1, cfg)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_cost()
        print("all checks passed")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ~/Developer/python/wildfire-sweep && python sweep.py --check`
Expected: FAIL with `NameError: name 'CONFIG' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Insert directly below the `import sys` line:

```python
CONFIG = {
    # --- costs: ponytail: placeholder, swap for real quotes ---
    "drone_cost": 15_000.0,       # multirotor + thermal payload
    "base_cost": 35_000.0,        # ruggedised drone-in-a-box, power, comms
    "install_cost": 20_000.0,     # civil works, connectivity, permitting
    "maintenance_frac": 0.15,     # of capex, per year
    "hardware_life_yr": 5.0,
    # --- world ---
    "domain_km2": 3808.0,         # Attica-sized square
    "season_days": 120.0,
    # --- drone behaviour ---
    "cruise_mps": 20.0,           # absorbs wind derating; not a sweep axis
    "dwell_s": 120.0,             # time overhead the fire before returning
    "turnaround_s": 600.0,        # battery swap / dock cycle
    "unserved_threshold_s": 900.0,
    # --- run control ---
    "seasons_per_config": 50,     # ponytail: 50 keeps the full sweep ~7min;
                                  # raise toward 200 if the frontier looks noisy
    "seed": 20260811,
}


def validate_config(cfg):
    """Fail loud at startup rather than mid-sweep."""
    positive = [
        "drone_cost", "base_cost", "install_cost", "hardware_life_yr",
        "domain_km2", "season_days", "cruise_mps", "turnaround_s",
        "unserved_threshold_s", "seasons_per_config",
    ]
    for key in positive:
        assert cfg[key] > 0, f"CONFIG[{key!r}] must be positive, got {cfg[key]!r}"
    assert cfg["dwell_s"] >= 0, "CONFIG['dwell_s'] must be non-negative"
    assert 0.0 <= cfg["maintenance_frac"] <= 1.0, "maintenance_frac must be a fraction"


def cost_per_km2_yr(n_bases, drones_per_base, cfg):
    """Annualised total cost of ownership per km2 of covered domain."""
    capex = n_bases * (
        cfg["base_cost"] + cfg["install_cost"] + drones_per_base * cfg["drone_cost"]
    )
    annual = capex / cfg["hardware_life_yr"] + capex * cfg["maintenance_frac"]
    return annual / cfg["domain_km2"]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: config, validation, and cost model"
```

---

### Task 2: Base grid

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: `CONFIG`.
- Produces: `base_grid(spacing_km: float, domain_km2: float) -> np.ndarray` returning shape `(n, 2)` of base centre coordinates in km; `check_bases() -> None`.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_bases():
    # 100 km2 domain is a 10x10 km square. At 5 km spacing that is a 2x2 grid.
    bases = base_grid(5.0, 100.0)
    assert bases.shape == (4, 2), f"expected 4 bases, got {bases.shape}"

    # Centres sit at 2.5 and 7.5 km on each axis.
    xs = sorted(set(round(float(v), 6) for v in bases[:, 0]))
    assert xs == [2.5, 7.5], f"base x-centres wrong: {xs}"

    # All bases fall strictly inside the domain.
    side = 10.0
    assert bases.min() > 0.0 and bases.max() < side, "base outside domain"

    # Spacing wider than the domain still yields one base, never zero.
    assert base_grid(500.0, 100.0).shape == (1, 2), "wide spacing must yield 1 base"

    # Tighter spacing never yields fewer bases.
    counts = [len(base_grid(s, 3808.0)) for s in (40.0, 20.0, 10.0, 5.0)]
    assert counts == sorted(counts), f"base count not monotonic in spacing: {counts}"
```

Add `check_bases()` to the `--check` block so it reads:

```python
    if "--check" in sys.argv:
        check_cost()
        check_bases()
        print("all checks passed")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'base_grid' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add `import math` and `import numpy as np` to the imports, then add this function below `cost_per_km2_yr`:

```python
def base_grid(spacing_km, domain_km2):
    """Square grid of base positions over a square domain.

    Returns an (n, 2) array of km coordinates. Bases sit at cell centres, so
    none land on the domain edge. Always returns at least one base.
    """
    side_km = math.sqrt(domain_km2)
    n = max(1, int(side_km // spacing_km))
    step = side_km / n
    centres = (np.arange(n) + 0.5) * step
    xx, yy = np.meshgrid(centres, centres)
    return np.column_stack([xx.ravel(), yy.ravel()])
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: square base grid over the domain"
```

---

### Task 3: World — season generation

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: `CONFIG`.
- Produces: `generate_season(rng, cfg: dict, ignitions_per_season: float, fp_rate: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]` returning `(t_s, xy_km, is_real)` where `t_s` is sorted ascending, `xy_km` has shape `(n, 2)`, and `is_real` is a boolean array; `check_world() -> None`.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_world():
    rng = np.random.default_rng(0)
    cfg = dict(CONFIG)
    cfg["domain_km2"] = 100.0
    cfg["season_days"] = 10.0

    t_s, xy_km, is_real = generate_season(rng, cfg, 200.0, 0.25)

    assert len(t_s) == len(xy_km) == len(is_real), "ragged season arrays"
    assert np.all(np.diff(t_s) >= 0), "ignition times not sorted"
    assert t_s.min() >= 0.0 and t_s.max() <= 10.0 * 86400.0, "ignition outside season"
    assert xy_km.min() >= 0.0 and xy_km.max() <= 10.0, "ignition outside domain"
    assert is_real.dtype == bool, "is_real must be boolean"

    # False-positive rate is honoured on average. 200 draws, 25% fake.
    fake_share = float((~is_real).mean())
    assert 0.15 < fake_share < 0.35, f"fp rate not honoured: {fake_share}"

    # A zero false-positive rate produces no fake alerts at all.
    _, _, all_real = generate_season(np.random.default_rng(1), cfg, 200.0, 0.0)
    assert all_real.all(), "fp_rate=0 still produced fake alerts"

    # Same seed, same season.
    a = generate_season(np.random.default_rng(7), cfg, 50.0, 0.1)
    b = generate_season(np.random.default_rng(7), cfg, 50.0, 0.1)
    assert np.array_equal(a[0], b[0]), "season not reproducible for a fixed seed"
```

Add `check_world()` to the `--check` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'generate_season' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add below `base_grid`:

```python
def generate_season(rng, cfg, ignitions_per_season, fp_rate):
    """One fire season of alerts.

    Ignition count is Poisson. Locations are uniform over the domain. Each
    alert is either a real fire or a false alarm; false alarms consume drones
    identically, which is the whole reason fp_rate is a sweep axis.

    Returns (t_s, xy_km, is_real) with t_s sorted ascending.
    """
    n = int(rng.poisson(ignitions_per_season))
    season_s = cfg["season_days"] * 86400.0
    t_s = np.sort(rng.uniform(0.0, season_s, n))
    side_km = math.sqrt(cfg["domain_km2"])
    xy_km = rng.uniform(0.0, side_km, size=(n, 2))
    is_real = rng.random(n) >= fp_rate
    return t_s, xy_km, is_real
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: season generation with Poisson ignitions and false alarms"
```

---

### Task 4: Dispatch

This is the load-bearing unit. If it is wrong, every number in the output is wrong.

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: `base_grid`, `generate_season`, `CONFIG`.
- Produces: `dispatch(t_s, xy_km, bases_km, drones_per_base: int, launch_latency_s: float, cfg: dict) -> tuple[np.ndarray, float]` returning `(response_s, utilisation)` where `response_s[k]` is alert-to-overhead seconds for alert `k`; `check_dispatch() -> None`.

**Dispatch rule:** assign each alert to whichever drone achieves the earliest arrival, where `arrival = max(drone_free_at, alert_time) + launch_latency + flight_time`. When drones are idle this picks the nearest one; when they are all busy it picks the best trade of wait against distance. One rule, no queue branch.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_dispatch():
    cfg = dict(CONFIG)
    cfg["dwell_s"] = 0.0
    cfg["turnaround_s"] = 0.0
    cfg["cruise_mps"] = 10.0

    # Degenerate geometry: one base at (0,0), one drone, no launch latency,
    # one alert 1 km away at t=0. Response must be exactly 1000m / 10m/s.
    bases = np.array([[0.0, 0.0]])
    t_s = np.array([0.0])
    xy_km = np.array([[1.0, 0.0]])
    response_s, _ = dispatch(t_s, xy_km, bases, 1, 0.0, cfg)
    assert abs(response_s[0] - 100.0) < 1e-9, f"expected 100s, got {response_s[0]}"

    # Launch latency adds directly to the response.
    response_s, _ = dispatch(t_s, xy_km, bases, 1, 45.0, cfg)
    assert abs(response_s[0] - 145.0) < 1e-9, f"latency not added: {response_s[0]}"

    # Contention: one drone, two simultaneous alerts 1 km away. The second
    # waits for the first round trip (out 100s + back 100s).
    t_s = np.array([0.0, 0.0])
    xy_km = np.array([[1.0, 0.0], [1.0, 0.0]])
    response_s, _ = dispatch(t_s, xy_km, bases, 1, 0.0, cfg)
    assert abs(response_s[0] - 100.0) < 1e-9, f"first alert wrong: {response_s[0]}"
    assert abs(response_s[1] - 300.0) < 1e-9, f"queued alert wrong: {response_s[1]}"

    # Two drones serve both simultaneous alerts without either waiting.
    response_s, _ = dispatch(t_s, xy_km, bases, 2, 0.0, cfg)
    assert np.allclose(response_s, 100.0), f"second drone unused: {response_s}"

    # The nearer base wins when both are idle.
    bases2 = np.array([[0.0, 0.0], [50.0, 0.0]])
    response_s, _ = dispatch(np.array([0.0]), np.array([[49.0, 0.0]]), bases2, 1, 0.0, cfg)
    assert abs(response_s[0] - 100.0) < 1e-9, f"did not pick nearest base: {response_s[0]}"

    # Utilisation is a fraction and rises with load.
    rng = np.random.default_rng(3)
    bases3 = base_grid(20.0, CONFIG["domain_km2"])
    t_s, xy_km, _ = generate_season(rng, CONFIG, 400.0, 0.0)
    _, util_busy = dispatch(t_s, xy_km, bases3, 1, 60.0, CONFIG)
    t_s, xy_km, _ = generate_season(np.random.default_rng(3), CONFIG, 50.0, 0.0)
    _, util_quiet = dispatch(t_s, xy_km, bases3, 1, 60.0, CONFIG)
    assert 0.0 <= util_quiet <= 1.0 and 0.0 <= util_busy <= 1.0, "utilisation out of range"
    assert util_busy > util_quiet, "utilisation did not rise with ignition load"

    # An empty season is not a crash.
    response_s, util = dispatch(np.array([]), np.zeros((0, 2)), bases, 1, 0.0, cfg)
    assert len(response_s) == 0 and util == 0.0, "empty season mishandled"
```

Add `check_dispatch()` to the `--check` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'dispatch' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add below `generate_season`:

```python
def dispatch(t_s, xy_km, bases_km, drones_per_base, launch_latency_s, cfg):
    """Assign each alert to the drone that can arrive soonest.

    A drone is locked from launch until it is back and turned around:
        busy = launch_latency + flight_out + dwell + flight_back + turnaround

    When drones are idle this reduces to "nearest base". When they are all
    busy it trades waiting against distance, which is what a real dispatcher
    would do. False alarms lock drones exactly like real fires.

    Returns (response_s, utilisation).
    """
    n_alerts = len(t_s)
    drone_xy_km = np.repeat(bases_km, drones_per_base, axis=0)
    free_at_s = np.zeros(len(drone_xy_km))
    response_s = np.empty(n_alerts)
    busy_s = 0.0

    for k in range(n_alerts):
        d_km = np.hypot(
            drone_xy_km[:, 0] - xy_km[k, 0],
            drone_xy_km[:, 1] - xy_km[k, 1],
        )
        flight_s = d_km * 1000.0 / cfg["cruise_mps"]
        arrival_s = np.maximum(free_at_s, t_s[k]) + launch_latency_s + flight_s
        i = int(np.argmin(arrival_s))
        response_s[k] = arrival_s[i] - t_s[k]
        occupied_s = (
            launch_latency_s + 2.0 * flight_s[i] + cfg["dwell_s"] + cfg["turnaround_s"]
        )
        free_at_s[i] = max(free_at_s[i], t_s[k]) + occupied_s
        busy_s += occupied_s

    season_s = cfg["season_days"] * 86400.0
    utilisation = busy_s / (len(drone_xy_km) * season_s) if n_alerts else 0.0
    return response_s, utilisation
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: earliest-arrival dispatch with drone occupancy"
```

---

### Task 5: Metrics and the monotonicity guard

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: `dispatch`, `base_grid`, `generate_season`, `CONFIG`.
- Produces: `season_metrics(response_s, is_real, cfg) -> tuple[float, float, float]` returning `(p50_s, p90_s, unserved_share)` over real ignitions only; `check_metrics() -> None`.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_metrics():
    cfg = dict(CONFIG)
    cfg["unserved_threshold_s"] = 900.0

    # Percentiles are computed over real ignitions only. The 10_000s response
    # belongs to a false alarm and must not appear in the statistics.
    response_s = np.array([100.0, 200.0, 300.0, 10_000.0])
    is_real = np.array([True, True, True, False])
    p50_s, p90_s, unserved = season_metrics(response_s, is_real, cfg)
    assert abs(p50_s - 200.0) < 1e-9, f"p50 contaminated by false alarm: {p50_s}"
    assert p90_s < 300.1, f"p90 contaminated by false alarm: {p90_s}"
    assert unserved == 0.0, f"false alarm counted as unserved: {unserved}"

    # Responses past the threshold count as misses.
    response_s = np.array([100.0, 5_000.0])
    is_real = np.array([True, True])
    _, _, unserved = season_metrics(response_s, is_real, cfg)
    assert abs(unserved - 0.5) < 1e-9, f"unserved share wrong: {unserved}"

    # A season with no real ignitions yields nan rather than crashing.
    p50_s, p90_s, unserved = season_metrics(
        np.array([5.0]), np.array([False]), cfg
    )
    assert math.isnan(p50_s) and math.isnan(p90_s) and math.isnan(unserved)


def check_monotonicity():
    """The two sanity laws the whole sweep rests on."""
    cfg = dict(CONFIG)
    rng_seed = 11

    def p90_for(spacing_km, drones_per_base):
        p90s = []
        for s in range(8):
            rng = np.random.default_rng(rng_seed + s)
            t_s, xy_km, is_real = generate_season(rng, cfg, 150.0, 0.2)
            bases = base_grid(spacing_km, cfg["domain_km2"])
            response_s, _ = dispatch(t_s, xy_km, bases, drones_per_base, 60.0, cfg)
            _, p90_s, _ = season_metrics(response_s, is_real, cfg)
            p90s.append(p90_s)
        return float(np.nanmean(p90s))

    # Law 1: tighter base spacing never makes response worse.
    by_spacing = [p90_for(s, 2) for s in (40.0, 20.0, 10.0)]
    assert by_spacing[0] >= by_spacing[1] >= by_spacing[2], (
        f"tighter spacing worsened p90: {by_spacing}"
    )

    # Law 2: more drones per base never makes response worse.
    by_drones = [p90_for(20.0, d) for d in (1, 2, 4)]
    assert by_drones[0] >= by_drones[1] >= by_drones[2], (
        f"more drones worsened p90: {by_drones}"
    )
```

Add both `check_metrics()` and `check_monotonicity()` to the `--check` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'season_metrics' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add below `dispatch`:

```python
def season_metrics(response_s, is_real, cfg):
    """Response statistics over real ignitions only.

    False alarms consume drones but are not fires, so they never enter the
    quality numbers. Returns (p50_s, p90_s, unserved_share); all nan when the
    season contained no real ignition.
    """
    real_s = np.asarray(response_s)[np.asarray(is_real, dtype=bool)]
    if real_s.size == 0:
        return float("nan"), float("nan"), float("nan")
    p50_s, p90_s = np.percentile(real_s, [50, 90])
    unserved = float((real_s > cfg["unserved_threshold_s"]).mean())
    return float(p50_s), float(p90_s), unserved
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`. `check_monotonicity` takes a few seconds — that is expected.

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: season metrics and monotonicity guard"
```

---

### Task 6: Sweep loop and CSV

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: every unit above.
- Produces: `AXES: dict`, `run_sweep(cfg) -> list[dict]`, `write_csv(rows, path) -> None`. Each row has keys: `spacing_km`, `drones_per_base`, `launch_latency_s`, `fp_rate`, `ignitions_per_season`, `n_bases`, `p50_s`, `p90_s`, `unserved_share`, `utilisation`, `eur_per_km2_yr`.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_sweep():
    cfg = dict(CONFIG)
    cfg["seasons_per_config"] = 2
    rows = run_sweep(cfg, axes={
        "spacing_km": [20.0, 10.0],
        "drones_per_base": [1],
        "launch_latency_s": [60.0],
        "fp_rate": [0.2],
        "ignitions_per_season": [50.0],
    })
    assert len(rows) == 2, f"expected 2 configs, got {len(rows)}"

    expected_keys = {
        "spacing_km", "drones_per_base", "launch_latency_s", "fp_rate",
        "ignitions_per_season", "n_bases", "p50_s", "p90_s",
        "unserved_share", "utilisation", "eur_per_km2_yr",
    }
    assert set(rows[0]) == expected_keys, f"row keys wrong: {set(rows[0])}"

    # Tighter spacing costs more and responds faster.
    wide = next(r for r in rows if r["spacing_km"] == 20.0)
    tight = next(r for r in rows if r["spacing_km"] == 10.0)
    assert tight["eur_per_km2_yr"] > wide["eur_per_km2_yr"], "tighter grid not costlier"
    assert tight["p90_s"] <= wide["p90_s"], "tighter grid not faster"
```

Add `check_sweep()` to the `--check` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'run_sweep' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add `import csv`, `import itertools`, and `import time` to the imports. Add below `season_metrics`:

```python
AXES = {
    "spacing_km": [5.0, 8.0, 12.0, 16.0, 20.0, 26.0, 32.0, 40.0],
    "drones_per_base": [1, 2, 3, 4, 5, 6],
    "launch_latency_s": [30.0, 60.0, 120.0, 180.0],
    "fp_rate": [0.05, 0.15, 0.25, 0.35, 0.50],
    "ignitions_per_season": [50.0, 150.0, 400.0],
}


def run_sweep(cfg, axes=None):
    """Monte Carlo every axis combination. Returns one row dict per config."""
    axes = AXES if axes is None else axes
    names = list(axes)
    combos = list(itertools.product(*(axes[k] for k in names)))
    rows = []
    started = time.monotonic()

    for idx, combo in enumerate(combos):
        params = dict(zip(names, combo))
        bases_km = base_grid(params["spacing_km"], cfg["domain_km2"])
        p50s, p90s, unserveds, utils = [], [], [], []

        for season in range(cfg["seasons_per_config"]):
            rng = np.random.default_rng(cfg["seed"] + idx * 10_000 + season)
            t_s, xy_km, is_real = generate_season(
                rng, cfg, params["ignitions_per_season"], params["fp_rate"]
            )
            response_s, utilisation = dispatch(
                t_s, xy_km, bases_km,
                params["drones_per_base"], params["launch_latency_s"], cfg,
            )
            p50_s, p90_s, unserved = season_metrics(response_s, is_real, cfg)
            p50s.append(p50_s)
            p90s.append(p90_s)
            unserveds.append(unserved)
            utils.append(utilisation)

        rows.append({
            **params,
            "n_bases": len(bases_km),
            "p50_s": float(np.nanmean(p50s)),
            "p90_s": float(np.nanmean(p90s)),
            "unserved_share": float(np.nanmean(unserveds)),
            "utilisation": float(np.mean(utils)),
            "eur_per_km2_yr": cost_per_km2_yr(
                len(bases_km), params["drones_per_base"], cfg
            ),
        })

        if (idx + 1) % 100 == 0:
            elapsed = time.monotonic() - started
            rate = (idx + 1) / elapsed
            print(
                f"  {idx + 1}/{len(combos)} configs "
                f"({elapsed:.0f}s elapsed, ~{(len(combos) - idx - 1) / rate:.0f}s left)"
            )

    return rows


def write_csv(rows, path="results.csv"):
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {path} ({len(rows)} rows)")
```

Replace the `__main__` block with:

```python
if __name__ == "__main__":
    validate_config(CONFIG)
    if "--check" in sys.argv:
        check_cost()
        check_bases()
        check_world()
        check_dispatch()
        check_metrics()
        check_monotonicity()
        check_sweep()
        print("all checks passed")
    else:
        rows = run_sweep(CONFIG)
        write_csv(rows)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

Then run the real sweep: `time python sweep.py`
Expected: progress lines every 100 configs, then `wrote results.csv (2880 rows)`.

**If this exceeds 30 minutes, stop and lower `seasons_per_config` before doing anything else.** Do not add parallelism, do not add a dependency.

- [ ] **Step 5: Read the numbers before moving on**

Run: `python -c "import csv;rows=list(csv.DictReader(open('results.csv')));rows.sort(key=lambda r: float(r['p90_s']));print(rows[0]);print(rows[-1])"`

Sanity-check the fastest and slowest configs by eye. The CSV is the answer; the chart is presentation. If a number looks impossible, it probably is — investigate before charting it.

- [ ] **Step 6: Commit**

```bash
git add sweep.py
git commit -m "feat: sweep loop over all axes with CSV output"
```

---

### Task 7: Pareto chart

**Files:**
- Modify: `sweep.py`

**Interfaces:**
- Consumes: `run_sweep` output rows.
- Produces: `pareto_front(rows) -> list[dict]`, `plot_pareto(rows, path) -> None`; `check_pareto() -> None`.

- [ ] **Step 1: Write the failing check**

Add this function above `if __name__ == "__main__":`:

```python
def check_pareto():
    # b is dominated by a (costs more, slower). c and a are both efficient.
    rows = [
        {"eur_per_km2_yr": 10.0, "p90_s": 500.0},   # a
        {"eur_per_km2_yr": 20.0, "p90_s": 600.0},   # b: dominated
        {"eur_per_km2_yr": 30.0, "p90_s": 200.0},   # c
    ]
    front = pareto_front(rows)
    costs = sorted(r["eur_per_km2_yr"] for r in front)
    assert costs == [10.0, 30.0], f"pareto front wrong: {costs}"

    # The front is sorted by cost and strictly improves in p90.
    assert all(
        front[i]["p90_s"] > front[i + 1]["p90_s"] for i in range(len(front) - 1)
    ), "front not strictly improving"

    # An equal-cost tie keeps only the faster option.
    tie = pareto_front([
        {"eur_per_km2_yr": 10.0, "p90_s": 500.0},
        {"eur_per_km2_yr": 10.0, "p90_s": 900.0},
    ])
    assert len(tie) == 1 and tie[0]["p90_s"] == 500.0, f"tie mishandled: {tie}"
```

Add `check_pareto()` to the `--check` block.

- [ ] **Step 2: Run it to verify it fails**

Run: `python sweep.py --check`
Expected: FAIL with `NameError: name 'pareto_front' is not defined`

- [ ] **Step 3: Write the minimal implementation**

Add `import matplotlib` / `matplotlib.use("Agg")` / `import matplotlib.pyplot as plt` to the imports (the `Agg` line must come before the `pyplot` import). Add below `write_csv`:

```python
def pareto_front(rows):
    """Configs where nothing else is both cheaper and faster."""
    ordered = sorted(rows, key=lambda r: (r["eur_per_km2_yr"], r["p90_s"]))
    front, best_p90 = [], float("inf")
    for row in ordered:
        if row["p90_s"] < best_p90:
            front.append(row)
            best_p90 = row["p90_s"]
    return front


def plot_pareto(rows, path="pareto.png"):
    """One panel per ignition-density level, so density sensitivity is visible."""
    densities = sorted({r["ignitions_per_season"] for r in rows})
    fig, axes_grid = plt.subplots(
        1, len(densities), figsize=(6 * len(densities), 5), squeeze=False
    )

    for ax, density in zip(axes_grid[0], densities):
        subset = [r for r in rows if r["ignitions_per_season"] == density]
        scatter = ax.scatter(
            [r["eur_per_km2_yr"] for r in subset],
            [r["p90_s"] / 60.0 for r in subset],
            c=[r["spacing_km"] for r in subset],
            cmap="viridis", s=14, alpha=0.55,
        )
        front = pareto_front(subset)
        ax.plot(
            [r["eur_per_km2_yr"] for r in front],
            [r["p90_s"] / 60.0 for r in front],
            color="#006bff", linewidth=2, marker="o", markersize=5,
            label="Pareto frontier",
        )
        ax.set_xscale("log")
        ax.set_xlabel("€ / km² / year")
        ax.set_ylabel("p90 time-to-eyes-on (minutes)")
        ax.set_title(f"{density:.0f} ignitions / season")
        ax.grid(alpha=0.25)
        ax.legend()
        fig.colorbar(scatter, ax=ax, label="base spacing (km)")

    fig.suptitle(
        "Monitor swarm: response time vs cost (Tier 0 — costs are placeholders)"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"wrote {path}")
```

Extend the `else` branch of `__main__`:

```python
    else:
        rows = run_sweep(CONFIG)
        write_csv(rows)
        plot_pareto(rows)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python sweep.py --check`
Expected: `all checks passed`

Then: `python sweep.py` and open `pareto.png`. The frontier should bend — cheap configs slow, expensive configs fast, with a knee. A flat or vertical frontier means something upstream is wrong.

- [ ] **Step 5: Commit**

```bash
git add sweep.py
git commit -m "feat: Pareto chart panelled by ignition density"
```

---

## Self-Review

**Spec coverage.** CONFIG block → Task 1. Cost unit → Task 1. Bases unit → Task 2. World unit → Task 3. Dispatch unit → Task 4. Metrics unit → Task 5. Sweep + `results.csv` → Task 6. `pareto.png` panelled by density → Task 7. Config validation before the sweep → Task 1, wired in Task 6. Three required checks (degenerate geometry, monotonicity, cost arithmetic) → Tasks 4, 5, 1 respectively. Spec build order is followed exactly.

**Deviations from the spec, both deliberate:**
1. Dispatch is one earliest-arrival rule rather than "nearest free, else queue". Equivalent when drones are idle, better-defined under contention.
2. `seasons_per_config` defaults to 50 rather than the spec's 200, to hold the full sweep near 7 minutes. It is a CONFIG knob, and Task 6 Step 4 carries the spec's 30-minute guard.

**Non-goals held.** No terrain, no fire growth, no wind axis, no physics, no suppression, no cloud, no test framework, no dependency beyond numpy and matplotlib.
