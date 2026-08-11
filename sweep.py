"""Tier 0 wildfire drone-swarm parameter sweep.

Answers: time-to-eyes-on vs EUR/km2/yr for a monitor-drone base network.
No terrain, no fire growth, no flight physics. See docs/superpowers/specs/.
"""

import math
import sys

import numpy as np

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


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_cost()
        check_bases()
        check_world()
        check_dispatch()
        check_metrics()
        check_monotonicity()
        print("all checks passed")
