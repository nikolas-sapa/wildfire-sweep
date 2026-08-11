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


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_cost()
        check_bases()
        print("all checks passed")
