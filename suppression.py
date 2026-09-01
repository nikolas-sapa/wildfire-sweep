"""Sweep B: how many water-carrying drones would it take to hold a fire line?

Expected output is a NEGATIVE result. This exists to close the "why not just
put water on the drones" question in investor meetings with a number instead
of an opinion, and to be cheap enough that nobody is tempted to fund it
further. See docs/superpowers/specs/ ("What comes after").

Deterministic, not Monte Carlo. Containment has a closed form: a free-burning
fire creates new perimeter at a constant rate, so the water needed to hold it
is a constant flow rate, not a volume. Sampling seasons would add noise to an
answer that has no randomness in it.

    python suppression.py          # run the sweep, write CSV + chart
    python suppression.py --check  # self-checks only
"""

import csv
import itertools
import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ponytail: every euro figure is a placeholder, same rule as sweep.py CONFIG.
# Swap for real quotes and rerun; no logic depends on the values.
CONFIG = {
    # --- drone ---
    "cruise_mps": 20.0,           # same as sweep.py; absorbs wind derating
    "drop_s": 20.0,               # line-up + release over the target
    "refill_s": 180.0,            # land, refill tank, swap/charge battery
    "water_kg_per_l": 1.0,
    # --- logistics ---
    "water_source_km": 5.0,       # base-to-fire one-way; a dedicated fire is
                                  # not served from the nearest base but from
                                  # wherever water is, hence its own knob
    # --- suppression physics ---
    # Direct attack needs a wetted line ahead of the flame front. 1 L/m is
    # optimistic light fuel, 4 L/m is realistic shrub. Source: swap for a
    # cited figure before this goes in a deck.
    "water_l_per_m": (1.0, 2.0, 4.0),
    # Rate of spread, Mediterranean shrub under fire weather, m/min.
    "ros_m_per_min": (0.5, 1.0, 2.0),
    # Aerial suppression is ineffective above roughly this fireline intensity
    # regardless of how much water arrives; crews and helicopters are pulled
    # for the same reason. Used as a hard time window, not a modelled term.
    "intensity_limit_kw_per_m": 4000.0,
    "intensity_growth_kw_per_m_per_min": 200.0,  # coarse ramp to the limit
    # --- response ---
    "response_delay_min": (5.0, 15.0, 30.0),  # ignition -> first water on fire
    "payload_l": (5.0, 10.0, 25.0, 50.0),     # 5L toy .. 50L heavy-lift
    # --- the incumbent we are being compared to ---
    "heli_drop_l": 3000.0,
    "heli_cycle_s": 900.0,
    "heli_eur_per_hour": 5000.0,
    # --- drone cost, for the comparison line ---
    "drone_cost": 15_000.0,       # matches sweep.py; heavy-lift is optimistic
}


def validate_config(cfg):
    """Fail loud at startup rather than mid-sweep."""
    positive = [
        "cruise_mps", "drop_s", "refill_s", "water_source_km",
        "intensity_limit_kw_per_m", "intensity_growth_kw_per_m_per_min",
        "heli_drop_l", "heli_cycle_s", "drone_cost",
    ]
    for key in positive:
        assert cfg[key] > 0, f"CONFIG[{key!r}] must be positive, got {cfg[key]!r}"
    for key in ("water_l_per_m", "ros_m_per_min", "response_delay_min", "payload_l"):
        assert len(cfg[key]) > 0, f"CONFIG[{key!r}] must be a non-empty axis"
        assert all(v > 0 for v in cfg[key]), f"CONFIG[{key!r}] values must be positive"


def cycle_s(cfg):
    """Seconds for one drone to deliver one payload and be ready again."""
    return 2.0 * cfg["water_source_km"] * 1000.0 / cfg["cruise_mps"] + cfg["drop_s"] + cfg["refill_s"]


def drone_flow_lps(payload_l, cfg):
    """Sustained water delivery of ONE drone, litres per second."""
    return payload_l / cycle_s(cfg)


def perimeter_m(ros_m_per_min, t_min):
    """Perimeter of a circular free-burning fire at t minutes after ignition."""
    return 2.0 * math.pi * ros_m_per_min * t_min


def hold_flow_lps(ros_m_per_min, water_l_per_m):
    """Flow needed to WET new perimeter as fast as the fire creates it.

    dP/dt = 2*pi*ROS is constant for a circular fire, so the holding
    requirement is a constant flow rate independent of when you arrive.
    Arriving late does not raise this rate; it raises the one-off knockdown
    volume below.
    """
    return 2.0 * math.pi * ros_m_per_min * water_l_per_m / 60.0


def knockdown_l(ros_m_per_min, water_l_per_m, t_min):
    """One-off volume to wet the perimeter that already exists on arrival."""
    return perimeter_m(ros_m_per_min, t_min) * water_l_per_m


def window_min(cfg):
    """Minutes from ignition until fireline intensity passes the point where
    water stops working. Beyond this the fleet size is academic."""
    return cfg["intensity_limit_kw_per_m"] / cfg["intensity_growth_kw_per_m_per_min"]


def fleet_size(payload_l, ros_m_per_min, water_l_per_m, delay_min, cfg):
    """Drones needed to knock down the existing perimeter AND then hold it.

    Knockdown must land inside the remaining window before intensity passes
    the limit, so it too becomes a flow requirement, not just a volume.
    """
    remaining_min = window_min(cfg) - delay_min
    per_drone = drone_flow_lps(payload_l, cfg)
    hold = hold_flow_lps(ros_m_per_min, water_l_per_m)
    if remaining_min <= 0.0:
        # Arrived after water stops working. No fleet size succeeds.
        return None, hold / per_drone, float("inf")
    knock = knockdown_l(ros_m_per_min, water_l_per_m, delay_min) / (remaining_min * 60.0)
    n = math.ceil((hold + knock) / per_drone)
    return n, hold / per_drone, knock / per_drone


def heli_equivalent(cfg):
    """Sustained flow of one helicopter, litres per second."""
    return cfg["heli_drop_l"] / cfg["heli_cycle_s"]


def run_sweep(cfg=CONFIG):
    rows = []
    axes = itertools.product(
        cfg["payload_l"], cfg["ros_m_per_min"], cfg["water_l_per_m"], cfg["response_delay_min"]
    )
    for payload_l, ros, wpm, delay in axes:
        n, hold_drones, knock_drones = fleet_size(payload_l, ros, wpm, delay, cfg)
        feasible = n is not None
        rows.append({
            "payload_l": payload_l,
            "ros_m_per_min": ros,
            "water_l_per_m": wpm,
            "response_delay_min": delay,
            "fleet_drones": n if feasible else "",
            "feasible": feasible,
            "hold_only_drones": round(hold_drones, 1),
            "knockdown_drones": (round(knock_drones, 1) if feasible else ""),
            "fleet_capex_eur": (n * cfg["drone_cost"] if feasible else ""),
            "heli_equivalent": (
                round(n * drone_flow_lps(payload_l, cfg) / heli_equivalent(cfg), 2)
                if feasible else ""
            ),
        })
    return rows


def write_csv(rows, path="suppression.csv"):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return path


def plot_fleet(rows, cfg=CONFIG, path="suppression.png"):
    """Fleet size vs payload, one line per rate of spread, at the mid delay."""
    delay = sorted(cfg["response_delay_min"])[len(cfg["response_delay_min"]) // 2]
    wpm = sorted(cfg["water_l_per_m"])[len(cfg["water_l_per_m"]) // 2]
    fig, ax = plt.subplots(figsize=(8, 5))
    for ros in sorted(cfg["ros_m_per_min"]):
        pts = [
            (r["payload_l"], r["fleet_drones"]) for r in rows
            if r["ros_m_per_min"] == ros and r["response_delay_min"] == delay
            and r["water_l_per_m"] == wpm and r["feasible"]
        ]
        if pts:
            pts.sort()
            ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o",
                    label=f"spread {ros:g} m/min")
    ax.set_yscale("log")
    ax.set_xlabel("drone water payload (L)")
    ax.set_ylabel("drones needed to hold the line (log scale)")
    ax.set_title(
        f"Sweep B: fleet to suppress one fire\n"
        f"{delay:g} min response, {wpm:g} L/m line, "
        f"{cfg['water_source_km']:g} km to water"
    )
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def report(rows, cfg=CONFIG):
    """The three sentences this whole file exists to produce."""
    heli_lps = heli_equivalent(cfg)
    mid_ros = sorted(cfg["ros_m_per_min"])[len(cfg["ros_m_per_min"]) // 2]
    mid_wpm = sorted(cfg["water_l_per_m"])[len(cfg["water_l_per_m"]) // 2]
    mid_delay = sorted(cfg["response_delay_min"])[len(cfg["response_delay_min"]) // 2]
    best_payload = max(cfg["payload_l"])
    n, _, _ = fleet_size(best_payload, mid_ros, mid_wpm, mid_delay, cfg)
    lines = [
        f"Water stops working ~{window_min(cfg):g} min after ignition "
        f"({cfg['intensity_limit_kw_per_m']:g} kW/m at "
        f"{cfg['intensity_growth_kw_per_m_per_min']:g} kW/m/min).",
        f"One drone cycle is {cycle_s(cfg) / 60.0:.1f} min for "
        f"{best_payload:g} L -> {drone_flow_lps(best_payload, cfg):.2f} L/s sustained.",
        f"One helicopter sustains {heli_lps:.1f} L/s "
        f"= {heli_lps / drone_flow_lps(best_payload, cfg):.0f} of those drones.",
    ]
    if n is None:
        lines.append(
            f"At {mid_ros:g} m/min, {mid_wpm:g} L/m, {mid_delay:g} min response: "
            f"NO fleet size works - water arrives after the window closes."
        )
    else:
        lines.append(
            f"At {mid_ros:g} m/min, {mid_wpm:g} L/m, {mid_delay:g} min response: "
            f"{n} x {best_payload:g}L drones = EUR {n * cfg['drone_cost']:,.0f} capex "
            f"to match roughly {n * drone_flow_lps(best_payload, cfg) / heli_lps:.1f} helicopters."
        )
    infeasible = sum(1 for r in rows if not r["feasible"])
    lines.append(f"{infeasible}/{len(rows)} configs cannot be held at any fleet size.")
    return "\n".join(lines)


# --- self-checks: the smallest things that fail if the logic breaks ---

def check_flow():
    cfg = dict(CONFIG, water_source_km=1.0, cruise_mps=10.0, drop_s=0.0, refill_s=100.0)
    # 2 * 1000 m / 10 mps = 200 s travel + 100 s refill = 300 s
    assert cycle_s(cfg) == 300.0, cycle_s(cfg)
    assert drone_flow_lps(30.0, cfg) == 0.1, drone_flow_lps(30.0, cfg)
    # Bigger payload and shorter cycle both raise sustained flow.
    assert drone_flow_lps(60.0, cfg) > drone_flow_lps(30.0, cfg)
    assert drone_flow_lps(30.0, dict(cfg, refill_s=10.0)) > drone_flow_lps(30.0, cfg)


def check_hold_is_arrival_independent():
    """The holding flow must not depend on when you show up - only the
    one-off knockdown does. If this ever couples, the model is wrong."""
    a = hold_flow_lps(1.0, 2.0)
    assert a == hold_flow_lps(1.0, 2.0)
    assert hold_flow_lps(2.0, 2.0) == 2.0 * a, "holding flow must scale with spread"
    assert hold_flow_lps(1.0, 4.0) == 2.0 * a, "holding flow must scale with L/m"
    # 2*pi*1 m/min * 2 L/m = 12.566 L/min = 0.2094 L/s
    assert abs(a - 2.0 * math.pi * 2.0 / 60.0) < 1e-12


def check_knockdown_grows_with_delay():
    early = knockdown_l(1.0, 2.0, 5.0)
    late = knockdown_l(1.0, 2.0, 20.0)
    assert late == 4.0 * early, (early, late)
    assert knockdown_l(1.0, 2.0, 0.0) == 0.0


def check_fleet_monotonic():
    """Every axis must push fleet size the way physics says, or an axis is
    inert - the exact defect that survived six reviews in Tier 0."""
    base = dict(payload_l=25.0, ros_m_per_min=1.0, water_l_per_m=2.0, delay_min=10.0, cfg=CONFIG)
    n0, _, _ = fleet_size(**base)
    assert n0 is not None and n0 > 0, n0
    bigger, _, _ = fleet_size(**dict(base, payload_l=50.0))
    assert bigger < n0, f"bigger payload must need fewer drones: {bigger} vs {n0}"
    faster, _, _ = fleet_size(**dict(base, ros_m_per_min=2.0))
    assert faster > n0, f"faster spread must need more drones: {faster} vs {n0}"
    wetter, _, _ = fleet_size(**dict(base, water_l_per_m=4.0))
    assert wetter > n0, f"more water per metre must need more drones: {wetter} vs {n0}"
    later, _, _ = fleet_size(**dict(base, delay_min=15.0))
    assert later > n0, f"later arrival must need more drones: {later} vs {n0}"
    farther, _, _ = fleet_size(**dict(base, cfg=dict(CONFIG, water_source_km=20.0)))
    assert farther > n0, f"farther water must need more drones: {farther} vs {n0}"


def check_window_closes():
    """Past the intensity limit, no fleet works. Must return None, not a
    large number - a large number would read as 'expensive but possible'."""
    late = window_min(CONFIG) + 1.0
    n, _, _ = fleet_size(25.0, 1.0, 2.0, late, CONFIG)
    assert n is None, n
    n, _, _ = fleet_size(25.0, 1.0, 2.0, window_min(CONFIG) - 1.0, CONFIG)
    assert n is not None and n > 0, n


def check_sweep_shape():
    rows = run_sweep()
    expected = (len(CONFIG["payload_l"]) * len(CONFIG["ros_m_per_min"])
                * len(CONFIG["water_l_per_m"]) * len(CONFIG["response_delay_min"]))
    assert len(rows) == expected, (len(rows), expected)
    assert any(r["feasible"] for r in rows), "sweep found no feasible config at all"


def run_checks():
    for fn in (check_flow, check_hold_is_arrival_independent, check_knockdown_grows_with_delay,
               check_fleet_monotonic, check_window_closes, check_sweep_shape):
        fn()
        print(f"ok  {fn.__name__}")
    print("all checks passed")


if __name__ == "__main__":
    validate_config(CONFIG)
    if "--check" in sys.argv:
        run_checks()
        sys.exit(0)
    run_checks()
    rows = run_sweep()
    print(f"\n{write_csv(rows)}  {len(rows)} configs")
    print(plot_fleet(rows))
    print()
    print(report(rows))
