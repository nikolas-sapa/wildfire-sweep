"""Two checks the headline sweep never ran: can the aircraft fly the mission,
and how much does the p90 headline move if you change one assumption at a
time.

Analysis 1 (flyability) is pure geometry from sweep.base_grid — no Monte
Carlo needed. Analysis 2 (sensitivity) reuses sweep.py's own base_grid,
generate_season, dispatch, season_metrics so the physics is identical to the
canonical run; only CONFIG values change.

Does not modify sweep.py, suppression.py, or results.csv. Does not run the
full sweep (AXES product x 200 seasons, ~30 min) — every call below
evaluates a single spacing/drone config, which is seconds.
"""

import math

import numpy as np

from sweep import (
    CONFIG, base_grid, generate_season, dispatch, season_metrics,
)

# ---------------------------------------------------------------------------
# Analysis 1: physical feasibility
# ---------------------------------------------------------------------------

# DJI Matrice 4TD published specs (cited, supplied by team-lead 2026-09-01):
# max flight time ~46-49 min, max horizontal speed 21 m/s, MTOM ~2090g,
# operating range -30..50C, max wind resistance 12 m/s (also the limit for
# takeoff/landing). 47.5 min is the midpoint of the published max-flight-time
# range; it is a real spec, not a proxy, but it is still a NO-WIND HOVER/
# CRUISE max, not a mission budget, which is why the model still needs a
# reserve fraction on top of it (ENDURANCE_MIN_CITED and RESERVE_FRAC are
# both swept below, not hardcoded into one verdict).
ENDURANCE_MIN_CITED = 47.5
# The published max-flight-time range itself is 46-49 min, not a single
# number -- report the flyability table bracketed at both ends rather than
# collapsing to the midpoint.
ENDURANCE_MIN_BRACKET = (46.0, 49.0)
# The model has NO reserve margin anywhere. SORA (specific operations risk
# assessment) practice expects 20-30% reserve; report flyability at
# reserve_frac=1.0 (no reserve, matches the model's current behaviour),
# reserve_frac=0.80 (20% reserve), and reserve_frac=0.75 (25% reserve).
RESERVE_FRAC_NONE = 1.00
RESERVE_FRAC_SORA_20 = 0.80
RESERVE_FRAC_SORA = 0.75  # 25% reserve, used as the pessimistic-corner case
# Kept as aliases so existing checks that reference the old placeholder names
# still exercise the cited figures.
ENDURANCE_MIN_PLACEHOLDER = ENDURANCE_MIN_CITED
RESERVE_FRAC_PLACEHOLDER = RESERVE_FRAC_SORA

FRONTIER_SPACINGS_KM = [26.0, 16.0, 12.0, 8.0, 5.0]

# ponytail: base_grid floors n = side_km // spacing_km and re-derives the
# actual spacing as side_km / n (see mission_geometry below), so the
# spacing_km axis anyone reads off sweep.py's AXES or results.csv is a
# LABEL, not a distance. Nominal 26 km is actually 30.85 km; nominal 16 km
# is actually 20.57 km. Every table in this file reports both columns for
# exactly this reason -- read "actual", not "nominal", when it matters.


def mission_geometry(spacing_km, cfg=CONFIG):
    """Worst-case and mean fire-to-base distance for a spacing.

    base_grid floors n = side_km // spacing_km, so the actual spacing the
    grid delivers is side_km / n, not the nominal spacing_km passed in — both
    are returned. Worst-case distance is approximated by sampling ignitions
    on a fine grid over the domain and taking the max/mean nearest-base
    distance (exact for a square-cell Voronoi tessellation: the true worst
    case is a cell corner, which a fine enough grid finds to sub-100m
    accuracy).
    """
    bases_km = base_grid(spacing_km, cfg["domain_km2"])
    side_km = math.sqrt(cfg["domain_km2"])
    actual_spacing_km = side_km / max(1, int(side_km // spacing_km))

    # Fine sample grid (200x200) to find worst-case and mean distance to the
    # nearest base under the resulting Voronoi tessellation.
    n_sample = 600
    samples = (np.arange(n_sample) + 0.5) * (side_km / n_sample)
    xx, yy = np.meshgrid(samples, samples)
    pts = np.column_stack([xx.ravel(), yy.ravel()])
    d = np.hypot(
        pts[:, 0, None] - bases_km[None, :, 0],
        pts[:, 1, None] - bases_km[None, :, 1],
    )
    nearest_km = d.min(axis=1)
    return {
        "nominal_spacing_km": spacing_km,
        "actual_spacing_km": actual_spacing_km,
        "n_bases": len(bases_km),
        "worst_km": float(nearest_km.max()),
        "mean_km": float(nearest_km.mean()),
    }


def mission_time(one_way_km, cfg=CONFIG):
    """Round-trip mission time and total flight distance for one leg length."""
    flight_s = 2.0 * one_way_km * 1000.0 / cfg["cruise_mps"]
    total_s = flight_s + cfg["dwell_s"]
    return {
        "one_way_km": one_way_km,
        "flight_distance_km": 2.0 * one_way_km,
        "mission_time_min": total_s / 60.0,
        "flight_time_min": flight_s / 60.0,
    }


def max_flyable_spacing_km(endurance_min, reserve_frac, cfg=CONFIG, spacings=None):
    """Widest nominal spacing (from the swept axis) whose worst-case mission
    still fits inside the usable endurance budget. None if even the tightest
    swept spacing fails.
    """
    spacings = spacings or sorted(FRONTIER_SPACINGS_KM + [40.0, 32.0, 20.0])
    usable_s = endurance_min * 60.0 * reserve_frac
    best = None
    for s in sorted(spacings):
        geo = mission_geometry(s, cfg)
        mt = mission_time(geo["worst_km"], cfg)
        if mt["mission_time_min"] * 60.0 <= usable_s:
            best = s
    return best


def flyability_verdict(spacing_km, endurance_min, reserve_frac, cfg=CONFIG):
    """feasible / marginal / impossible for one frontier config.

    feasible: worst-case mission fits inside usable endurance with >=20%
    margin left. marginal: fits, but with less than 20% margin. impossible:
    does not fit.
    """
    geo = mission_geometry(spacing_km, cfg)
    mt = mission_time(geo["worst_km"], cfg)
    usable_s = endurance_min * 60.0 * reserve_frac
    used_s = mt["mission_time_min"] * 60.0
    margin = 1.0 - used_s / usable_s
    if used_s > usable_s:
        verdict = "impossible"
    elif margin < 0.20:
        verdict = "marginal"
    else:
        verdict = "feasible"
    return {**geo, **mt, "usable_endurance_min": usable_s / 60.0, "margin": margin, "verdict": verdict}


# --- wind ---
# 12 m/s is the Matrice 4TD's cited MAX WIND RESISTANCE, a different quantity
# from cruise speed. What actually matters for response time is ground
# speed: outbound into a headwind w is (airspeed - w), the return leg with a
# tailwind is (airspeed + w). A round trip in wind is slower than the
# still-air round trip even though the return leg alone is faster -- that
# asymmetry is what this section adds; the earlier cruise_mps sweep only
# ever varied the airspeed uniformly and never modelled headwind at all.
WIND_RATED_MAX_MPS = 12.0  # above this the aircraft is outside its rated
                            # envelope entirely -- see the grounding note
                            # below, this stops being a response-time
                            # question and becomes an availability one.
WIND_AIRSPEEDS_MPS = [18.0, 20.0]  # 18 = sustainable figure, 20 = optimistic
                                    # ceiling (21 m/s is the cited maximum)
WIND_HEADWINDS_MPS = [0.0, 4.0, 8.0, 12.0]

# ponytail: wind speed is not the only thing this model omits. Above
# WIND_RATED_MAX_MPS the aircraft cannot fly AT ALL, not just more slowly --
# some number of days per fire season will exceed 12 m/s wind (Greek meltemi
# routinely does), and on those days the fleet is grounded, not merely
# slower. "Days per season grounded by wind" is not modelled anywhere in
# this file or in sweep.py and is arguably a bigger risk to the pitch than
# any of the response-time derating computed here -- flagged as a gap for a
# future pass, not attempted here.


def wind_effective_cruise_mps(airspeed_mps, headwind_mps):
    """Effective symmetric speed that reproduces the TRUE round-trip flight
    time under a headwind opposing the outbound leg (and aiding the return).

    True round-trip time for one-way distance d is d/(v-w) + d/(v+w)
    = d * 2v / (v^2 - w^2). Solving 2d/v_eff for that same time gives
    v_eff = v - w^2/v -- independent of d, so a single number can stand in
    for cruise_mps in dispatch() without needing the mission distance.

    ponytail: this equalises ROUND-TRIP time exactly, but dispatch()'s
    response time is the OUTBOUND leg alone (time to first reach the fire),
    which under a real headwind is genuinely slower than v_eff (v_eff
    blends in the faster tailwind return). Using v_eff for both response and
    busy-time is therefore mildly OPTIMISTIC on p90 specifically, not exact
    -- a true fix would split outbound/return speed inside dispatch() itself,
    which means editing sweep.py and is out of scope here.
    """
    if headwind_mps >= airspeed_mps:
        return 0.0  # cannot make headway outbound at all
    return airspeed_mps - headwind_mps ** 2 / airspeed_mps


def wind_round_trip_geometry(one_way_km, airspeed_mps, headwind_mps, dwell_s):
    """True asymmetric round-trip time for one leg length under wind.

    Returns (out_s, back_s, total_s). If headwind_mps >= airspeed_mps the
    aircraft cannot complete the outbound leg at all: out_s and total_s are
    inf.
    """
    if headwind_mps >= airspeed_mps:
        return float("inf"), 0.0, float("inf")
    out_s = one_way_km * 1000.0 / (airspeed_mps - headwind_mps)
    back_s = one_way_km * 1000.0 / (airspeed_mps + headwind_mps)
    return out_s, back_s, out_s + back_s + dwell_s


def find_crossing_headwind(p90_fn, headwinds, threshold_min=15.0):
    """First headwind (from an ascending, caller-sorted list) at which
    p90_fn(headwind) exceeds threshold_min. None if nothing in the list
    crosses. Generic over p90_fn so the search logic itself can be
    mutation-tested against a deterministic stand-in, independent of the
    stochastic Monte Carlo evaluation used for the real answer.
    """
    for w in headwinds:
        if p90_fn(w) > threshold_min:
            return w
    return None


# ---------------------------------------------------------------------------
# Analysis 2: sensitivity of the headline
# ---------------------------------------------------------------------------

ANCHOR = dict(ignitions_per_season=307.0, fp_rate=0.05, launch_latency_s=30.0, seasons=200)

FRONTIER_CONFIGS = [
    {"label": "9-base/1-drone (headline)", "spacing_km": 16.0, "drones_per_base": 1},
    {"label": "4-base/2-drone (cheap)", "spacing_km": 26.0, "drones_per_base": 2},
]

SENSITIVITY_AXES = {
    # DJI Matrice 4TD max horizontal speed is a cited 21 m/s, so the model's
    # 20 m/s CONFIG default is ~95% of max, not a sustainable cruise figure
    # -- dropped as a sweep value. 12 m/s is also the cited max wind
    # resistance for takeoff/landing/operation, and Greek meltemi winds
    # routinely exceed it, so the LOW end of this range is the realistic
    # operating case, not a pessimistic tail. 20 m/s is kept as the
    # optimistic ceiling. Inferring that sustaining near-max speed costs
    # meaningfully more energy than the endurance spec (which is measured at
    # efficient cruise) is inference, not a DJI figure.
    "cruise_mps": [10.0, 12.0, 15.0, 18.0, 20.0],
    # DJI Dock 3 published minimum interval between sorties is a cited
    # 27 min (1620s) at 15%->95% charge, 25C, single aircraft, no hot-swap --
    # 2.7x the model's CONFIG default of 600s. 2400s stands in for hot-weather
    # charge derating in Greek summer and is an ESTIMATE, not a spec. 1620s
    # is the headline case to report on since it is sourced.
    "turnaround_s": [300.0, 600.0, 1200.0, 1620.0, 2400.0],
    "dwell_s": [60.0, 120.0, 300.0],
    "unserved_threshold_s": [600.0, 900.0, 1800.0],
    "max_unserved_share": [0.05, 0.10, 0.20],
}
TURNAROUND_CITED_S = 1620.0  # DJI Dock 3, cited (headline reporting case)


def evaluate_config(spacing_km, drones_per_base, cfg, n_seasons=None, seed_base=None):
    """p90 and unserved_share for one config at the anchor ignition/fp/latency,
    averaged over n_seasons using CONFIG's own seed discipline (seed + season
    index, matching run_sweep's per-season term for a fixed density/fp
    combination).
    """
    n_seasons = n_seasons or ANCHOR["seasons"]
    seed_base = cfg["seed"] if seed_base is None else seed_base
    bases_km = base_grid(spacing_km, cfg["domain_km2"])
    p90s, unserveds = [], []
    for season in range(n_seasons):
        rng = np.random.default_rng(seed_base + season)
        t_s, xy_km, is_real = generate_season(
            rng, cfg, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"]
        )
        response_s, _ = dispatch(
            t_s, xy_km, bases_km, drones_per_base, ANCHOR["launch_latency_s"], cfg
        )
        _, p90_s, unserved = season_metrics(response_s, is_real, cfg)
        p90s.append(p90_s)
        unserveds.append(unserved)
    return float(np.nanmean(p90s)), float(np.nanmean(unserveds))


def evaluate_config_ext(
    spacing_km, drones_per_base, cfg, ignitions_per_season, fp_rate,
    n_seasons=None, seed_base=None,
):
    """Like evaluate_config, but with the ignition density and false-alarm
    rate as explicit parameters (not fixed to ANCHOR) and utilisation
    returned alongside p90/unserved_share, so turnaround's effect can be
    read off against fleet workload instead of assumed.
    """
    n_seasons = n_seasons or ANCHOR["seasons"]
    seed_base = cfg["seed"] if seed_base is None else seed_base
    bases_km = base_grid(spacing_km, cfg["domain_km2"])
    p90s, unserveds, utils = [], [], []
    for season in range(n_seasons):
        rng = np.random.default_rng(seed_base + season)
        t_s, xy_km, is_real = generate_season(
            rng, cfg, ignitions_per_season, fp_rate
        )
        response_s, utilisation = dispatch(
            t_s, xy_km, bases_km, drones_per_base, ANCHOR["launch_latency_s"], cfg
        )
        _, p90_s, unserved = season_metrics(response_s, is_real, cfg)
        p90s.append(p90_s)
        unserveds.append(unserved)
        utils.append(utilisation)
    return float(np.nanmean(p90s)), float(np.nanmean(unserveds)), float(np.mean(utils))


TURNAROUND_PANEL_S = [300.0, 600.0, TURNAROUND_CITED_S, 2400.0]

SATURATION_PANEL = dict(ignitions_per_season=614.0, fp_rate=0.50)


def run_turnaround_panel(ignitions_per_season, fp_rate, n_seasons=None):
    """Turnaround sweep (300/600/1620/2400s) for both frontier configs at a
    given ignition density and false-positive rate, with utilisation
    reported alongside p90/unserved_share.
    """
    rows = []
    for fc in FRONTIER_CONFIGS:
        for turnaround_s in TURNAROUND_PANEL_S:
            cfg = dict(CONFIG, turnaround_s=turnaround_s)
            p90_s, unserved, utilisation = evaluate_config_ext(
                fc["spacing_km"], fc["drones_per_base"], cfg,
                ignitions_per_season, fp_rate, n_seasons,
            )
            rows.append({
                "config": fc["label"], "turnaround_s": turnaround_s,
                "p90_min": p90_s / 60.0, "unserved_share": unserved,
                "utilisation": utilisation,
                "crosses_15min": p90_s / 60.0 > 15.0,
                "crosses_gate": unserved > CONFIG["max_unserved_share"],
            })
    return rows


def run_sensitivity(n_seasons=None):
    """One-at-a-time sensitivity sweep for each frontier config.

    Returns a list of row dicts: config label, axis varied, value, p90_min,
    unserved_share, and whether it crosses the 15-min officials' threshold or
    the config's own max_unserved_share gate.
    """
    rows = []
    for fc in FRONTIER_CONFIGS:
        # Baseline at CONFIG defaults.
        base_p90, base_unserved = evaluate_config(
            fc["spacing_km"], fc["drones_per_base"], CONFIG, n_seasons
        )
        rows.append({
            "config": fc["label"], "axis": "baseline", "value": None,
            "p90_min": base_p90 / 60.0, "unserved_share": base_unserved,
            "crosses_15min": base_p90 / 60.0 > 15.0,
            "crosses_gate": base_unserved > CONFIG["max_unserved_share"],
        })
        for axis, values in SENSITIVITY_AXES.items():
            for v in values:
                if axis == "max_unserved_share":
                    # This axis doesn't feed dispatch/season_metrics; it only
                    # changes which unserved_share counts as a pass. Reuse
                    # the baseline result and re-gate it.
                    p90_s, unserved = base_p90, base_unserved
                else:
                    cfg = dict(CONFIG, **{axis: v})
                    p90_s, unserved = evaluate_config(
                        fc["spacing_km"], fc["drones_per_base"], cfg, n_seasons
                    )
                gate = v if axis == "max_unserved_share" else CONFIG["max_unserved_share"]
                rows.append({
                    "config": fc["label"], "axis": axis, "value": v,
                    "p90_min": p90_s / 60.0, "unserved_share": unserved,
                    "crosses_15min": p90_s / 60.0 > 15.0,
                    "crosses_gate": unserved > gate,
                })
    return rows


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_mission_geometry():
    # Domain side = sqrt(3808) = 61.71 km. At 16 km nominal, n = 61.71//16 = 3,
    # actual spacing = 61.71/3 = 20.57 km, giving a 3x3 = 9-base grid, which
    # must match the headline's n_bases=9.
    side_km = math.sqrt(CONFIG["domain_km2"])
    geo = mission_geometry(16.0)
    assert geo["n_bases"] == 9, f"expected 9 bases at 16km nominal, got {geo['n_bases']}"
    assert abs(geo["actual_spacing_km"] - 20.5698) < 0.01, (
        f"actual spacing wrong: {geo['actual_spacing_km']}"
    )
    # Worst-case distance for a square Voronoi cell of side `step` is half the
    # diagonal: step/sqrt(2) * sqrt(2) ... i.e. corner-to-centre = step/sqrt(2).
    # Bound is the sample grid's own resolution: worst error is half a
    # sample cell's diagonal, since the true cell corner falls between
    # sample points.
    expected_worst = geo["actual_spacing_km"] / math.sqrt(2)
    sample_tol = math.sqrt(2) * (side_km / 600) / 2.0
    assert abs(geo["worst_km"] - expected_worst) < sample_tol + 1e-6, (
        f"worst-case distance off from analytic corner distance: "
        f"{geo['worst_km']} vs {expected_worst}"
    )
    # Mean distance to nearest base must be strictly less than worst-case.
    assert geo["mean_km"] < geo["worst_km"], "mean distance not below worst-case"

    # A single-base grid (spacing wider than the domain) must have its worst
    # case at the far corner: side*sqrt(2)/2 from the centre base.
    geo1 = mission_geometry(500.0)
    assert geo1["n_bases"] == 1, f"expected 1 base, got {geo1['n_bases']}"
    expected_corner = side_km * math.sqrt(2) / 2.0
    assert abs(geo1["worst_km"] - expected_corner) < 0.2, (
        f"single-base worst case wrong: {geo1['worst_km']} vs {expected_corner}"
    )


def check_mission_time():
    cfg = dict(CONFIG, cruise_mps=20.0, dwell_s=120.0)
    mt = mission_time(10.0, cfg)
    # 10 km one-way at 20 m/s = 500s each way, 1000s flight + 120s dwell.
    assert abs(mt["flight_time_min"] - 1000.0 / 60.0) < 1e-6, mt
    assert abs(mt["mission_time_min"] - 1120.0 / 60.0) < 1e-6, mt
    assert abs(mt["flight_distance_km"] - 20.0) < 1e-9, mt

    # Slower cruise strictly lengthens the mission for a fixed distance.
    slow = mission_time(10.0, dict(cfg, cruise_mps=10.0))
    assert slow["mission_time_min"] > mt["mission_time_min"], "slower cruise did not add time"


def check_max_flyable_spacing():
    # A huge endurance budget must permit even the widest swept spacing, so
    # the widest FLYABLE spacing returned is the widest spacing swept.
    wide_budget = max_flyable_spacing_km(600.0, 1.0)
    assert wide_budget == 40.0, (
        f"generous endurance should fly the widest swept spacing: {wide_budget}"
    )
    # A near-zero endurance budget must permit nothing.
    tiny_budget = max_flyable_spacing_km(0.5, 1.0)
    assert tiny_budget is None, f"near-zero endurance should fly nothing: {tiny_budget}"
    # Result must be monotonic: raising endurance never shrinks the max
    # flyable spacing.
    lo = max_flyable_spacing_km(20.0, 0.8)
    hi = max_flyable_spacing_km(40.0, 0.8)
    lo_v = lo if lo is not None else -1.0
    hi_v = hi if hi is not None else -1.0
    assert hi_v >= lo_v, f"more endurance shrank flyable spacing: {lo} -> {hi}"

    # Exact boundary: at reserve_frac=1.0, worst-case mission times (from
    # mission_geometry/mission_time on the default swept spacings) are
    # 7.9 min (5km), 12.4 min (8km), 16.4 min (12km), 26.1 min (16/20km),
    # 38.2 min (26km), 74.6 min (32/40km). A 20-min budget must therefore
    # admit exactly up to 12km and reject 16km.
    exact = max_flyable_spacing_km(20.0, 1.0)
    assert exact == 12.0, f"expected exactly 12km flyable at a 20min budget, got {exact}"


def check_flyability_verdict():
    # A config whose worst-case mission is far inside the budget is feasible.
    v = flyability_verdict(40.0, 1000.0, 1.0)
    assert v["verdict"] == "feasible", v
    # A config whose worst-case mission exceeds the budget is impossible.
    v2 = flyability_verdict(40.0, 0.1, 1.0)
    assert v2["verdict"] == "impossible", v2
    # Exact boundary: 16km spacing's worst-case mission is 26.1 min; a 20 min
    # budget (usable_s=1200s < used_s=1567s) must be impossible, not merely
    # marginal -- pins the used_s > usable_s comparison, not some looser one.
    v3 = flyability_verdict(16.0, 20.0, 1.0)
    assert v3["verdict"] == "impossible", v3
    # Tightening spacing while holding endurance fixed can only move a
    # verdict from better to worse (fewer minutes of margin), never better.
    v_wide = flyability_verdict(26.0, ENDURANCE_MIN_PLACEHOLDER, RESERVE_FRAC_PLACEHOLDER)
    v_tight = flyability_verdict(5.0, ENDURANCE_MIN_PLACEHOLDER, RESERVE_FRAC_PLACEHOLDER)
    assert v_tight["worst_km"] <= v_wide["worst_km"], (
        "tighter spacing did not reduce worst-case distance"
    )


def check_wind_effective_cruise():
    # Zero headwind must reproduce the airspeed exactly.
    assert wind_effective_cruise_mps(20.0, 0.0) == 20.0, "no wind must equal airspeed"

    # Known value: v=20, w=12 -> v_eff = 20 - 144/20 = 12.8.
    got = wind_effective_cruise_mps(20.0, 12.0)
    assert abs(got - 12.8) < 1e-9, f"v_eff wrong: {got}"

    # Headwind at or above airspeed means no headway at all.
    assert wind_effective_cruise_mps(20.0, 20.0) == 0.0, "headwind == airspeed must ground it"
    assert wind_effective_cruise_mps(20.0, 25.0) == 0.0, "headwind > airspeed must ground it"

    # Strictly monotonic decreasing in headwind.
    v0 = wind_effective_cruise_mps(18.0, 0.0)
    v4 = wind_effective_cruise_mps(18.0, 4.0)
    v8 = wind_effective_cruise_mps(18.0, 8.0)
    assert v0 > v4 > v8, f"v_eff not monotonic decreasing in headwind: {v0}, {v4}, {v8}"


def check_wind_round_trip_geometry():
    # No headwind: outbound and return legs are identical and match the
    # symmetric mission_time computation.
    out_s, back_s, total_s = wind_round_trip_geometry(10.0, 20.0, 0.0, 120.0)
    assert abs(out_s - back_s) < 1e-9, f"legs should match with no wind: {out_s} vs {back_s}"
    mt = mission_time(10.0, dict(CONFIG, cruise_mps=20.0, dwell_s=120.0))
    assert abs(total_s - mt["mission_time_min"] * 60.0) < 1e-6, (
        f"no-wind round trip diverged from mission_time: {total_s} vs {mt['mission_time_min'] * 60.0}"
    )

    # A real headwind makes the outbound leg strictly slower than the return.
    out_w, back_w, total_w = wind_round_trip_geometry(10.0, 20.0, 8.0, 120.0)
    assert out_w > back_w, f"headwind did not slow the outbound leg more: {out_w} vs {back_w}"

    # Wind always costs time overall: the round trip with wind is never
    # faster than the still-air round trip (harmonic-mean inequality).
    assert total_w > total_s, (
        f"wind round trip should be slower than still air: {total_w} vs {total_s}"
    )

    # Headwind >= airspeed: cannot complete the outbound leg.
    out_inf, back_inf, total_inf = wind_round_trip_geometry(10.0, 20.0, 20.0, 120.0)
    assert math.isinf(out_inf) and math.isinf(total_inf), "grounded case must be inf"
    assert back_inf == 0.0, f"grounded case still returned a finite back leg: {back_inf}"


def check_find_crossing_headwind():
    # Deterministic, monotonic stand-in for p90_fn: p90 == headwind itself.
    headwinds = [0.0, 5.0, 10.0, 14.0, 16.0]
    got = find_crossing_headwind(lambda w: w, headwinds, threshold_min=15.0)
    assert got == 16.0, f"expected first crossing at 16.0, got {got}"

    # Exactly-at-threshold must NOT count as crossing (strict >), so the
    # crossing is reported one step later.
    headwinds2 = [0.0, 15.0, 16.0]
    got2 = find_crossing_headwind(lambda w: w, headwinds2, threshold_min=15.0)
    assert got2 == 16.0, f"exact-threshold value wrongly counted as crossing: {got2}"

    # Never crossing returns None.
    got3 = find_crossing_headwind(lambda w: 1.0, headwinds, threshold_min=15.0)
    assert got3 is None, f"expected no crossing, got {got3}"


def check_evaluate_config():
    # Same config, same seed, same result (reproducibility).
    a = evaluate_config(20.0, 1, CONFIG, n_seasons=5)
    b = evaluate_config(20.0, 1, CONFIG, n_seasons=5)
    assert a == b, f"evaluate_config not reproducible: {a} vs {b}"

    # More drones per base never worsens p90 (same law sweep.check_monotonicity
    # asserts on dispatch directly).
    p90_1, _ = evaluate_config(40.0, 1, CONFIG, n_seasons=8)
    p90_4, _ = evaluate_config(40.0, 4, CONFIG, n_seasons=8)
    assert p90_4 <= p90_1, f"more drones worsened p90: {p90_1} -> {p90_4}"

    # A config's evaluate_config result must reproduce run_sweep's own
    # numbers when seeded exactly the same way run_sweep would. run_sweep
    # derives density_idx/fp_idx from the POSITION of the value in the axes
    # dict passed to it, not from the global AXES table -- a single-value
    # axes dict like the one below makes both indices 0.
    from sweep import run_sweep
    cfg2 = dict(CONFIG)
    cfg2["seasons_per_config"] = 5
    rows = run_sweep(cfg2, axes={
        "spacing_km": [16.0], "drones_per_base": [1],
        "launch_latency_s": [30.0], "fp_rate": [0.05],
        "ignitions_per_season": [307.0],
    })
    seed_matched = CONFIG["seed"] + 1000 * 0 + 100_000 * 0
    p90_direct, unserved_direct = evaluate_config(
        16.0, 1, CONFIG, n_seasons=5, seed_base=seed_matched
    )
    assert abs(p90_direct - rows[0]["p90_s"]) < 1e-6, (
        f"evaluate_config diverged from run_sweep: {p90_direct} vs {rows[0]['p90_s']}"
    )
    assert abs(unserved_direct - rows[0]["unserved_share"]) < 1e-9, (
        f"unserved_share diverged from run_sweep: {unserved_direct} vs {rows[0]['unserved_share']}"
    )


def check_evaluate_config_ext():
    # At the anchor density (307/season), evaluate_config and
    # evaluate_config_ext must agree on p90/unserved when given the same
    # ignitions/fp/seed, since evaluate_config_ext is a strict generalisation.
    p90_a, unserved_a = evaluate_config(16.0, 1, CONFIG, n_seasons=5)
    p90_b, unserved_b, util_b = evaluate_config_ext(
        16.0, 1, CONFIG, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=5
    )
    assert abs(p90_a - p90_b) < 1e-9, f"evaluate_config_ext diverged on p90: {p90_a} vs {p90_b}"
    assert abs(unserved_a - unserved_b) < 1e-9, (
        f"evaluate_config_ext diverged on unserved: {unserved_a} vs {unserved_b}"
    )
    assert 0.0 <= util_b, f"utilisation must be non-negative: {util_b}"

    # Exact reproducibility: reimplement one season of the same loop directly
    # from base_grid/generate_season/dispatch and confirm util_b's underlying
    # single-season utilisation matches bit-for-bit, so a constant-factor
    # scaling bug in evaluate_config_ext's own utilisation bookkeeping cannot
    # slip past.
    bases_km = base_grid(16.0, CONFIG["domain_km2"])
    rng = np.random.default_rng(CONFIG["seed"])
    t_s, xy_km, is_real = generate_season(
        rng, CONFIG, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"]
    )
    _, util_direct = dispatch(t_s, xy_km, bases_km, 1, ANCHOR["launch_latency_s"], CONFIG)
    _, _, util_one_season = evaluate_config_ext(
        16.0, 1, CONFIG, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=1
    )
    assert abs(util_one_season - util_direct) < 1e-9, (
        f"evaluate_config_ext utilisation diverged from direct dispatch: "
        f"{util_one_season} vs {util_direct}"
    )

    # Utilisation must rise sharply between the anchor density and the
    # saturation panel (614 ignitions, fp=0.50 roughly triples total alert
    # volume: more real fires plus an equal-sized false-alarm stream).
    _, _, util_anchor = evaluate_config_ext(
        16.0, 1, CONFIG, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=5
    )
    _, _, util_sat = evaluate_config_ext(
        16.0, 1, CONFIG, SATURATION_PANEL["ignitions_per_season"],
        SATURATION_PANEL["fp_rate"], n_seasons=5,
    )
    assert util_sat > util_anchor, (
        f"saturation panel did not raise utilisation over the anchor: "
        f"{util_anchor} -> {util_sat}"
    )

    # Utilisation must also rise with a longer turnaround, holding load
    # fixed: locking a drone longer per job raises total busy time.
    cfg_short = dict(CONFIG, turnaround_s=300.0)
    cfg_long = dict(CONFIG, turnaround_s=2400.0)
    _, _, util_short = evaluate_config_ext(
        16.0, 1, cfg_short, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=5
    )
    _, _, util_long = evaluate_config_ext(
        16.0, 1, cfg_long, ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=5
    )
    assert util_long > util_short, (
        f"longer turnaround did not raise utilisation: {util_short} -> {util_long}"
    )


def check_run_turnaround_panel():
    rows = run_turnaround_panel(
        ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons=5
    )
    # 2 configs x 4 turnaround values.
    assert len(rows) == 8, f"expected 8 rows, got {len(rows)}"
    expected_keys = {
        "config", "turnaround_s", "p90_min", "unserved_share", "utilisation",
        "crosses_15min", "crosses_gate",
    }
    assert set(rows[0]) == expected_keys, f"row keys wrong: {set(rows[0])}"
    # The cited 1620s figure must actually be one of the swept values.
    assert 1620.0 in TURNAROUND_PANEL_S, "cited 27min turnaround missing from panel"
    # Within one config, utilisation must be non-decreasing as turnaround_s
    # rises across the sorted panel (longer lockup per job never frees up
    # fleet capacity).
    for fc in FRONTIER_CONFIGS:
        cfg_rows = sorted(
            (r for r in rows if r["config"] == fc["label"]),
            key=lambda r: r["turnaround_s"],
        )
        utils = [r["utilisation"] for r in cfg_rows]
        assert all(utils[i] <= utils[i + 1] for i in range(len(utils) - 1)), (
            f"utilisation not monotonic in turnaround_s for {fc['label']}: {utils}"
        )
        # Must be a STRICT rise end-to-end (300s -> 2400s), not merely
        # non-decreasing -- catches a mutant that silently drops the
        # turnaround_s override and leaves every row identical.
        assert utils[-1] > utils[0], (
            f"utilisation did not actually rise with turnaround_s for "
            f"{fc['label']}: {utils}"
        )


def run_checks():
    check_mission_geometry()
    check_mission_time()
    check_max_flyable_spacing()
    check_flyability_verdict()
    check_wind_effective_cruise()
    check_wind_round_trip_geometry()
    check_find_crossing_headwind()
    check_evaluate_config()
    check_evaluate_config_ext()
    check_run_turnaround_panel()
    print("all checks passed")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_flyability_report():
    print("=" * 78)
    print("ANALYSIS 1: PHYSICAL FEASIBILITY")
    print("=" * 78)
    print(
        f"Published DJI Matrice 4TD specs (not a placeholder): max flight time "
        f"{ENDURANCE_MIN_BRACKET[0]:.0f}-{ENDURANCE_MIN_BRACKET[1]:.0f} min, "
        f"max horizontal speed 21 m/s, MTOM ~2090g, operating range -30..50C, "
        f"max wind resistance 12 m/s (also the takeoff/landing/operation limit). "
        f"The model has NO reserve margin anywhere; SORA practice expects "
        f"20-30% reserve. Bracketed below at both ends of the published "
        f"endurance range and at 20% and 25% reserve."
    )
    print()
    reserve_scenarios = [
        ("no reserve", RESERVE_FRAC_NONE),
        ("20% reserve", RESERVE_FRAC_SORA_20),
        ("25% reserve", RESERVE_FRAC_SORA),
    ]
    for endurance_min in ENDURANCE_MIN_BRACKET:
        print(f"--- endurance = {endurance_min:.0f} min ---")
        header = (
            f"{'nominal':>8} {'actual':>8} {'bases':>6} {'worst_km':>9} "
            f"{'worst_min':>10} " + " ".join(
                f"{'margin_' + lbl.split()[0]:>13} {'verdict_' + lbl.split()[0]:>13}"
                for lbl, _ in reserve_scenarios
            )
        )
        print(header)
        for spacing in FRONTIER_SPACINGS_KM:
            geo = mission_geometry(spacing)
            worst_mt = mission_time(geo["worst_km"])
            cells = []
            for _, reserve in reserve_scenarios:
                v = flyability_verdict(spacing, endurance_min, reserve)
                cells.append(f"{v['margin']:>+13.0%} {v['verdict']:>13}")
            print(
                f"{spacing:>8.1f} {geo['actual_spacing_km']:>8.2f} {geo['n_bases']:>6d} "
                f"{geo['worst_km']:>9.2f} {worst_mt['mission_time_min']:>10.1f} " + " ".join(cells)
            )
        print()

    print("Max flyable nominal spacing, by scenario:")
    for endurance_min in ENDURANCE_MIN_BRACKET:
        for label, reserve in reserve_scenarios:
            max_spacing = max_flyable_spacing_km(endurance_min, reserve)
            print(
                f"  endurance={endurance_min:.0f}min, {label}: "
                f"{max_spacing} km" if max_spacing else
                f"  endurance={endurance_min:.0f}min, {label}: NONE of the swept spacings fit."
            )

    print()
    print("HEADLINE (9-base / 16 km nominal) across the full bracket:")
    for endurance_min in ENDURANCE_MIN_BRACKET:
        for label, reserve in reserve_scenarios:
            headline = flyability_verdict(16.0, endurance_min, reserve)
            print(
                f"  endurance={endurance_min:.0f}min, {label}: worst-case mission "
                f"{headline['mission_time_min']:.1f} min vs {headline['usable_endurance_min']:.1f} "
                f"min usable budget, margin {headline['margin']:+.0%} "
                f"-> VERDICT: {headline['verdict'].upper()}"
            )

    pessimistic = flyability_verdict(16.0, ENDURANCE_MIN_BRACKET[0], RESERVE_FRAC_SORA)
    print(
        f"\nPESSIMISTIC CORNER (46 min endurance, 25% reserve): "
        f"9-base/16km headline worst-case mission {pessimistic['mission_time_min']:.1f} min "
        f"vs {pessimistic['usable_endurance_min']:.1f} min usable budget, "
        f"margin {pessimistic['margin']:+.0%} "
        f"-> {'SURVIVES' if pessimistic['verdict'] == 'feasible' else 'DOES NOT SURVIVE'} "
        f"({pessimistic['verdict']})."
    )


def print_sensitivity_report(n_seasons=None):
    print()
    print("=" * 78)
    print("ANALYSIS 2: SENSITIVITY OF THE HEADLINE (307 ignitions, 30s latency)")
    print("=" * 78)
    rows = run_sensitivity(n_seasons)
    print(f"{'config':<28} {'axis':<22} {'value':>8} {'p90_min':>8} {'unserved':>9} {'>15min':>7} {'>gate':>6}")
    for r in rows:
        val = "-" if r["value"] is None else f"{r['value']}"
        print(
            f"{r['config']:<28} {r['axis']:<22} {val:>8} "
            f"{r['p90_min']:>8.2f} {r['unserved_share']:>9.3%} "
            f"{'YES' if r['crosses_15min'] else '.':>7} "
            f"{'YES' if r['crosses_gate'] else '.':>6}"
        )
    print()
    print(f"HEADLINE CASE: turnaround_s = {TURNAROUND_CITED_S:.0f} (cited DJI Dock 3 min sortie interval)")
    for r in rows:
        if r["axis"] == "turnaround_s" and r["value"] == TURNAROUND_CITED_S:
            print(
                f"  {r['config']}: p90={r['p90_min']:.2f} min, "
                f"unserved={r['unserved_share']:.3%}, "
                f"crosses_15min={r['crosses_15min']}, crosses_gate={r['crosses_gate']}"
            )
    return rows


def print_turnaround_panel_report(n_seasons=None):
    print()
    print("=" * 78)
    print(
        "TURNAROUND PANEL, 307 ignitions / fp=0.05 (anchor) -- p90/unserved/"
        "utilisation at 300/600/1620/2400s turnaround"
    )
    print("=" * 78)
    anchor_rows = run_turnaround_panel(
        ANCHOR["ignitions_per_season"], ANCHOR["fp_rate"], n_seasons
    )
    _print_turnaround_rows(anchor_rows)

    print()
    print("=" * 78)
    print(
        f"TURNAROUND PANEL, SATURATION CASE ({SATURATION_PANEL['ignitions_per_season']:.0f} "
        f"ignitions / fp={SATURATION_PANEL['fp_rate']:.2f}) -- honest stress test of "
        "one-drone-per-base: a false alarm occupies a dock for a full "
        "turnaround exactly like a real fire"
    )
    print("=" * 78)
    sat_rows = run_turnaround_panel(
        SATURATION_PANEL["ignitions_per_season"], SATURATION_PANEL["fp_rate"], n_seasons
    )
    _print_turnaround_rows(sat_rows)
    return anchor_rows, sat_rows


def _print_turnaround_rows(rows):
    print(f"{'config':<28} {'turnaround_s':>13} {'p90_min':>8} {'unserved':>9} {'utilisation':>11} {'>15min':>7} {'>gate':>6}")
    for r in rows:
        print(
            f"{r['config']:<28} {r['turnaround_s']:>13.0f} "
            f"{r['p90_min']:>8.2f} {r['unserved_share']:>9.3%} {r['utilisation']:>11.4f} "
            f"{'YES' if r['crosses_15min'] else '.':>7} "
            f"{'YES' if r['crosses_gate'] else '.':>6}"
        )


def print_wind_report(n_seasons=None):
    print()
    print("=" * 78)
    print("WIND: headwind on the outbound leg vs still-air cruise")
    print("=" * 78)
    print(
        f"12 m/s is the Matrice 4TD's cited MAX WIND RESISTANCE, not a cruise "
        f"speed. Above it the aircraft is outside its rated envelope and is "
        f"GROUNDED, not just slower -- 'days per season grounded by wind' is "
        f"not modelled here (see ponytail note near WIND_RATED_MAX_MPS) and "
        f"is arguably a bigger risk than any response-time derating below."
    )
    print()
    print("Asymmetric round-trip geometry at the 9-base headline's worst-case leg (14.47 km):")
    geo = mission_geometry(16.0)
    header = f"{'airspeed':>9} {'headwind':>9} {'out_min':>8} {'back_min':>9} {'total_min':>10} {'vs still-air':>13}"
    print(header)
    for airspeed in WIND_AIRSPEEDS_MPS:
        still_air_total = mission_time(geo["worst_km"], dict(CONFIG, cruise_mps=airspeed))["mission_time_min"]
        for headwind in WIND_HEADWINDS_MPS:
            out_s, back_s, total_s = wind_round_trip_geometry(
                geo["worst_km"], airspeed, headwind, CONFIG["dwell_s"]
            )
            total_min = total_s / 60.0
            delta = total_min - still_air_total
            print(
                f"{airspeed:>9.1f} {headwind:>9.1f} {out_s / 60.0:>8.1f} "
                f"{back_s / 60.0:>9.1f} {total_min:>10.1f} {delta:>+12.1f}m"
            )
    print()

    print(f"9-base headline (16km) p90/unserved by airspeed x headwind ({n_seasons or ANCHOR['seasons']} seasons):")
    header2 = f"{'airspeed':>9} {'headwind':>9} {'v_eff':>7} {'p90_min':>8} {'unserved':>9} {'>15min':>7}"
    print(header2)
    p90_cache = {}
    for airspeed in WIND_AIRSPEEDS_MPS:
        for headwind in WIND_HEADWINDS_MPS:
            v_eff = wind_effective_cruise_mps(airspeed, headwind)
            cfg = dict(CONFIG, cruise_mps=v_eff)
            p90_s, unserved = evaluate_config(16.0, 1, cfg, n_seasons)
            p90_min = p90_s / 60.0
            p90_cache[(airspeed, headwind)] = p90_min
            print(
                f"{airspeed:>9.1f} {headwind:>9.1f} {v_eff:>7.2f} "
                f"{p90_min:>8.2f} {unserved:>9.3%} "
                f"{'YES' if p90_min > 15.0 else '.':>7}"
            )

    print()
    fine_headwinds = [0.5 * i for i in range(0, 25)]  # 0.0 .. 12.0 step 0.5
    for airspeed in (18.0,):
        def p90_fn(w, _airspeed=airspeed):
            v_eff = wind_effective_cruise_mps(_airspeed, w)
            cfg = dict(CONFIG, cruise_mps=v_eff)
            p90_s, _ = evaluate_config(16.0, 1, cfg, n_seasons)
            return p90_s / 60.0

        crossing = find_crossing_headwind(p90_fn, fine_headwinds, threshold_min=15.0)
        if crossing is None:
            print(
                f"At airspeed={airspeed:.0f} m/s: p90 never crosses 15 min "
                f"within the rated wind envelope (0-{WIND_RATED_MAX_MPS:.0f} m/s)."
            )
        else:
            print(
                f"HEADWIND CROSSING at airspeed={airspeed:.0f} m/s: p90 first "
                f"exceeds 15 min at headwind = {crossing:.1f} m/s "
                f"({'within' if crossing <= WIND_RATED_MAX_MPS else 'ABOVE'} "
                f"the {WIND_RATED_MAX_MPS:.0f} m/s rated wind envelope)."
            )
    return p90_cache


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        run_checks()
    else:
        print_flyability_report()
        print_sensitivity_report()
        print_turnaround_panel_report()
        print_wind_report()
        print_turnaround_panel_report()
