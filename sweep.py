"""Tier 0 wildfire drone-swarm parameter sweep.

Answers: time-to-eyes-on vs EUR/km2/yr for a monitor-drone base network.
No terrain, no fire growth, no flight physics. See docs/superpowers/specs/.
"""

import sys

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
