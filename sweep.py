"""Tier 0 wildfire drone-swarm parameter sweep.

Answers: time-to-eyes-on vs EUR/km2/yr for a monitor-drone base network.
No terrain, no fire growth, no flight physics. See docs/superpowers/specs/.
"""

import csv
import itertools
import math
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

CONFIG = {
    # --- costs ---
    # Researched 2026-09-01. Hardware is list price, so it is real. Everything
    # below the hardware line is still a placeholder: no published figure
    # exists for drone-in-a-box insurance, site lease, or Mediterranean
    # replacement life. See docs/2026-09-01-research-pass-3.md for sources
    # and confidence per line.
    "drone_cost": 21_500.0,       # DJI Matrice 4TD, thermal (list, 2026)
    "base_cost": 14_600.0,        # DJI Dock 3 (list, 2026)
    "install_cost": 12_000.0,     # ponytail: no drone-specific breakdown is
                                  # published anywhere (EU tenders, EIB
                                  # drone finance guide, Percepto/Flytbase
                                  # case studies all silent). Proxy: telecom
                                  # remote-site / small-cell install (power
                                  # drop, mount, backhaul) runs EUR 8-15k;
                                  # using the midpoint.
    "maintenance_frac": 0.25,     # of capex, per year. Industry rule of thumb
                                  # for medium-high utilisation is 20-30%.
    "hardware_life_yr": 3.0,      # ponytail: no vendor MTBF or multi-year
                                  # hot-climate field data exists. DJI
                                  # warrants the Dock 3 for 1 year standard
                                  # and sells paid Care Enterprise Plus
                                  # extensions (up to 2 battery swaps/yr) —
                                  # a manufacturer monetising extensions
                                  # past year 1 is not expecting trouble-free
                                  # 5yr life. Dock is IP56/50C rated so heat
                                  # itself isn't the constraint. 3yr is a
                                  # supported planning assumption, not a
                                  # measured figure.
    # Recurring opex, which the original model omitted entirely and which
    # dominates the answer. Reported EU dock-based BVLOS operations run
    # EUR 30-50k per base per year all-in. That bundle is split in two here
    # because the two halves scale differently:
    "opex_per_base_yr": 8_000.0,  # ponytail: assembled from proxies, not
                                  # quoted. Insurance ~EUR 2-3k/yr per
                                  # dock+aircraft (built up from EU Reg
                                  # 785/2004 minimum 3rd-party liability,
                                  # market cover ~EUR 650-750/yr at a
                                  # EUR 1.3M limit, hull cover at 6-12% of
                                  # declared value, +~25% BVLOS loading; no
                                  # broker publishes a drone-in-a-box rate).
                                  # Site lease ~EUR 1.5-3k/yr, proxied off
                                  # Greek telecom mast colocation (siting on
                                  # an existing mast/substation/water tank
                                  # avoids new forestry permitting; no Greek
                                  # forestry-service permit tariff is
                                  # published). Remainder covers connectivity
                                  # and scheduled service. Scales with base
                                  # count.
    "ops_staff_yr": 60_000.0,     # remote-pilot / ops desk for the WHOLE
                                  # fleet. Does NOT scale with base count.
                                  # Splitting it out is the point: if remote
                                  # supervision were charged per base, a dense
                                  # swarm would be penalised for the very
                                  # thing that makes it work.
    # --- world ---
    "domain_km2": 3808.0,         # Attica-sized square
    "season_days": 120.0,
    # --- drone behaviour ---
    "cruise_mps": 20.0,           # absorbs wind derating; not a sweep axis
    "dwell_s": 120.0,             # time overhead the fire before returning
    "turnaround_s": 600.0,        # battery swap / dock cycle
    "unserved_threshold_s": 900.0,
    "max_unserved_share": 0.10,   # quality floor: configs missing more than
                                  # this share of real fires are excluded
                                  # from the Pareto frontier as infeasible
    # --- run control ---
    "seasons_per_config": 200,    # The 50-season run let a config sit ON the
                                  # max_unserved_share gate and flip in and out
                                  # of feasibility with fp_rate, which cannot
                                  # affect response time. At 200 that config
                                  # fails cleanly at every fp_rate, so the gate
                                  # artifact was noise, not a result. Measured
                                  # ~30 min on a quiet machine; an earlier
                                  # ~4h projection was contention from parallel
                                  # agents, not the workload. Keep 200.
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
    for key in ("opex_per_base_yr", "ops_staff_yr"):
        assert cfg[key] >= 0, f"CONFIG[{key!r}] must be non-negative, got {cfg[key]!r}"
    assert 0.0 <= cfg["maintenance_frac"] <= 1.0, "maintenance_frac must be a fraction"
    assert 0.0 <= cfg["max_unserved_share"] <= 1.0, "max_unserved_share must be a fraction"
    # The common-random-number seed in run_sweep packs season into the low
    # three digits (seed + season + 1000*density_idx + 100_000*fp_idx). At 1000
    # or more seasons it collides with density_idx and silently correlates
    # configs that should be independent.
    assert cfg["seasons_per_config"] < 1000, (
        f"seasons_per_config must stay under 1000 to keep the CRN seeds "
        f"distinct, got {cfg['seasons_per_config']!r}"
    )


def cost_per_km2_yr(n_bases, drones_per_base, cfg):
    """Annualised total cost of ownership per km2 of covered domain.

    Three terms: amortised capex, per-base recurring opex, and one fleet-wide
    ops-staff cost that does not scale with base count.
    """
    capex = n_bases * (
        cfg["base_cost"] + cfg["install_cost"] + drones_per_base * cfg["drone_cost"]
    )
    annual = (
        capex / cfg["hardware_life_yr"]
        + capex * cfg["maintenance_frac"]
        + n_bases * cfg["opex_per_base_yr"]
        + cfg["ops_staff_yr"]
    )
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

    ignitions_per_season is the REAL fire count (Poisson). False alarms are
    ADDITIONAL alerts drawn independently so that raising fp_rate never
    deletes real fires, only adds drone load; the expected share of all
    alerts that are fake equals fp_rate. Locations are uniform over the
    domain; times are uniform over the season. False alarms consume drones
    identically to real fires, which is the whole reason fp_rate is a sweep
    axis.

    Returns (t_s, xy_km, is_real) with t_s sorted ascending and xy_km/is_real
    kept in step with it.
    """
    if fp_rate >= 1.0:
        raise ValueError(f"fp_rate must be < 1.0, got {fp_rate!r}")
    n_real = int(rng.poisson(ignitions_per_season))
    n_fake = int(rng.poisson(ignitions_per_season * fp_rate / (1.0 - fp_rate)))
    n = n_real + n_fake
    season_s = cfg["season_days"] * 86400.0
    t_s = rng.uniform(0.0, season_s, n)
    side_km = math.sqrt(cfg["domain_km2"])
    xy_km = rng.uniform(0.0, side_km, size=(n, 2))
    is_real = np.concatenate([np.ones(n_real, dtype=bool), np.zeros(n_fake, dtype=bool)])
    order = np.argsort(t_s)
    return t_s[order], xy_km[order], is_real[order]


def dispatch(t_s, xy_km, bases_km, drones_per_base, launch_latency_s, cfg):
    """Assign each alert to the drone that can arrive soonest.

    A drone is locked from launch until it is back and turned around:
        busy = launch_latency + flight_out + dwell + flight_back + turnaround

    When drones are idle this reduces to "nearest base". When they are all
    busy it trades waiting against distance, which is what a real dispatcher
    would do. False alarms lock drones exactly like real fires.

    Returns (response_s, utilisation). Utilisation is a workload ratio, not a
    bounded fraction: it sums each job's full lock-up time even when that
    window extends past the season end, so it can exceed 1.0 under saturation.
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


AXES = {
    "spacing_km": [5.0, 8.0, 12.0, 16.0, 20.0, 26.0, 32.0, 40.0],
    "drones_per_base": [1, 2, 3, 4, 5, 6],
    "launch_latency_s": [30.0, 60.0, 120.0, 180.0],
    "fp_rate": [0.05, 0.15, 0.25, 0.35, 0.50],
    # Anchored 2026-09-01 on the Hellenic Fire Service national figure:
    # ~10,640 forest fire incidents per season over 131,957 km2 = 80.6 per
    # 1000 km2, so 307 over this 3808 km2 domain. Attica runs hotter than the
    # national average (wildland-urban interface, human ignition) but no
    # citable Attica multiplier was found, so the axis brackets the anchor
    # rather than asserting one: half it, it, and a 2x Attica assumption.
    "ignitions_per_season": [154.0, 307.0, 614.0],
}


def run_sweep(cfg, axes=None):
    """Monte Carlo every axis combination. Returns one row dict per config."""
    axes = AXES if axes is None else axes
    names = list(axes)
    combos = list(itertools.product(*(axes[k] for k in names)))
    rows = []
    started = time.monotonic()

    # Only ignitions_per_season and fp_rate feed generate_season, so the seed
    # must depend on their axis INDEX (not the float value) and on nothing
    # else, so configs that share those two values draw the same seasons and
    # can be compared without a winner's-curse bias. seasons_per_config is
    # kept well under 1000 (spec: <= 999) so the `season` term never collides
    # with the index terms above it.
    density_idx_of = {v: i for i, v in enumerate(axes["ignitions_per_season"])}
    fp_idx_of = {v: i for i, v in enumerate(axes["fp_rate"])}

    for idx, combo in enumerate(combos):
        params = dict(zip(names, combo))
        bases_km = base_grid(params["spacing_km"], cfg["domain_km2"])
        p50s, p90s, unserveds, utils = [], [], [], []
        density_idx = density_idx_of[params["ignitions_per_season"]]
        fp_idx = fp_idx_of[params["fp_rate"]]

        for season in range(cfg["seasons_per_config"]):
            seed = cfg["seed"] + season + 1000 * density_idx + 100_000 * fp_idx
            rng = np.random.default_rng(seed)
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


def pareto_front(rows, max_unserved_share=None):
    """Configs where nothing else is both cheaper and faster.

    If max_unserved_share is given, rows missing more than that share of
    real fires are dropped before the dominance pass, so a cheap config that
    quietly fails most fires can never front-run a slide.
    """
    eligible = (
        rows if max_unserved_share is None
        else [r for r in rows if r["unserved_share"] <= max_unserved_share]
    )
    ordered = sorted(eligible, key=lambda r: (r["eur_per_km2_yr"], r["p90_s"]))
    front, best_p90 = [], float("inf")
    for row in ordered:
        if row["p90_s"] < best_p90:
            front.append(row)
            best_p90 = row["p90_s"]
    return front


def plot_pareto(rows, cfg=CONFIG, path="pareto.png"):
    """One panel per ignition-density level, so density sensitivity is visible.

    All points are plotted regardless of quality; the frontier line is drawn
    through feasible points only (unserved_share <= max_unserved_share), so
    cheap-but-broken configs cannot masquerade as the best value on the line.
    """
    max_unserved_share = cfg["max_unserved_share"]
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
        front = pareto_front(subset, max_unserved_share=max_unserved_share)
        if front:
            ax.plot(
                [r["eur_per_km2_yr"] for r in front],
                [r["p90_s"] / 60.0 for r in front],
                color="#006bff", linewidth=2, marker="o", markersize=5,
                label=f"Pareto frontier (unserved ≤ {max_unserved_share:.0%})",
            )
        else:
            ax.text(
                0.5, 0.5, "no feasible configs\n(all miss quality floor)",
                transform=ax.transAxes, ha="center", va="center",
                color="#b00020", fontsize=10,
            )
        ax.set_xscale("log")
        ax.set_xlabel("€ / km² / year")
        ax.set_ylabel("p90 time-to-eyes-on (minutes)")
        ax.set_title(f"{density:.0f} ignitions / season")
        ax.grid(alpha=0.25)
        if front:
            ax.legend()
        fig.colorbar(scatter, ax=ax, label="base spacing (km)")

    fig.suptitle(
        "Monitor swarm: response time vs cost (Tier 0 — costs are placeholders)"
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    print(f"wrote {path}")


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

    # Raising fp_rate adds load: more total alerts for the same real-fire rate.
    low_t, _, _ = generate_season(np.random.default_rng(42), cfg, 200.0, 0.05)
    high_t, _, _ = generate_season(np.random.default_rng(42), cfg, 200.0, 0.50)
    assert len(high_t) > len(low_t), (
        f"raising fp_rate did not increase alert count: {len(low_t)} -> {len(high_t)}"
    )


def check_cost():
    cfg = dict(CONFIG)
    cfg["domain_km2"] = 1000.0
    cfg["base_cost"] = 35_000.0
    cfg["install_cost"] = 20_000.0
    cfg["drone_cost"] = 15_000.0
    cfg["hardware_life_yr"] = 5.0
    cfg["maintenance_frac"] = 0.15
    cfg["opex_per_base_yr"] = 0.0
    cfg["ops_staff_yr"] = 0.0

    # One base, one drone: capex = 35k + 20k + 15k = 70k.
    # Annual = 70k/5 + 70k*0.15 = 14_000 + 10_500 = 24_500.
    # Per km2 over 1000 km2 = 24.5
    got = cost_per_km2_yr(1, 1, cfg)
    assert abs(got - 24.5) < 1e-9, f"one-base cost wrong: {got}"

    # With both opex terms zeroed, cost is linear in base count.
    got10 = cost_per_km2_yr(10, 1, cfg)
    assert abs(got10 - 245.0) < 1e-9, f"cost not linear in bases: {got10}"

    # More drones per base costs strictly more.
    assert cost_per_km2_yr(1, 2, cfg) > cost_per_km2_yr(1, 1, cfg)

    # Per-base opex scales with base count: +1k/base/yr over 1000 km2 is
    # +1.0 per km2 at one base and +10.0 at ten.
    scaled = dict(cfg, opex_per_base_yr=1_000.0)
    assert abs(cost_per_km2_yr(1, 1, scaled) - (24.5 + 1.0)) < 1e-9
    assert abs(cost_per_km2_yr(10, 1, scaled) - (245.0 + 10.0)) < 1e-9

    # Fleet-wide ops staff does NOT scale with base count: the same absolute
    # amount is added at one base and at ten. If this ever starts scaling,
    # dense networks get wrongly penalised and the density argument dies.
    fixed = dict(cfg, ops_staff_yr=60_000.0)
    assert abs(cost_per_km2_yr(1, 1, fixed) - (24.5 + 60.0)) < 1e-9
    assert abs(cost_per_km2_yr(10, 1, fixed) - (245.0 + 60.0)) < 1e-9

    # Shortening hardware_life_yr spreads capex over fewer years, so the
    # annual cost must go up. Guards the term that was tightened 5.0 -> 3.0.
    short_life = dict(cfg, hardware_life_yr=3.0)
    assert cost_per_km2_yr(1, 1, short_life) > cost_per_km2_yr(1, 1, cfg), (
        "shortening hardware_life_yr did not raise annual cost"
    )


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

    def p90_for(spacing_km, drones_per_base, ignitions_per_season=150.0):
        p90s = []
        for s in range(8):
            rng = np.random.default_rng(rng_seed + s)
            t_s, xy_km, is_real = generate_season(rng, cfg, ignitions_per_season, 0.2)
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

    # Law 2: more drones per base never makes response worse. Uses a sparse
    # grid (40 km spacing, few bases) with a high ignition load (400/season)
    # so drones are actually contended; a light-load scenario passes this
    # law on exact equality and guards nothing.
    by_drones = [p90_for(40.0, d, ignitions_per_season=400.0) for d in (1, 2, 4)]
    assert by_drones[0] >= by_drones[1] >= by_drones[2], (
        f"more drones worsened p90: {by_drones}"
    )


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

    # Common random numbers: two configs differing ONLY in spacing_km must
    # see identical seasons. 40.0 and 50.0 spacing both floor to a single
    # base on the 3808 km2 domain (side = 61.71 km), so geometry and cost
    # are identical between them; under CRN the resulting p90_s must then be
    # bit-identical too. Under the old idx-based seeding (or any seed that
    # depended on spacing_km itself) these would diverge.
    rows_crn = run_sweep(cfg, axes={
        "spacing_km": [40.0, 50.0],
        "drones_per_base": [1],
        "launch_latency_s": [60.0],
        "fp_rate": [0.2],
        "ignitions_per_season": [50.0],
    })
    assert rows_crn[0]["n_bases"] == rows_crn[1]["n_bases"] == 1, (
        "expected identical single-base geometry for spacing 40/50"
    )
    assert rows_crn[0]["p90_s"] == rows_crn[1]["p90_s"], (
        "spacing-only configs with identical geometry drew different "
        f"seasons (common random numbers broken): {rows_crn[0]['p90_s']} "
        f"vs {rows_crn[1]['p90_s']}"
    )


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

    # A quality floor excludes an infeasible-but-cheap row from the frontier,
    # even though on cost/speed alone it would otherwise dominate everything.
    quality_rows = [
        {"eur_per_km2_yr": 5.0, "p90_s": 100.0, "unserved_share": 0.75},  # cheap, infeasible
        {"eur_per_km2_yr": 40.0, "p90_s": 300.0, "unserved_share": 0.05},  # feasible
    ]
    feasible_front = pareto_front(quality_rows, max_unserved_share=0.10)
    assert len(feasible_front) == 1 and feasible_front[0]["eur_per_km2_yr"] == 40.0, (
        f"infeasible row not excluded from frontier: {feasible_front}"
    )
    # Without a floor the infeasible row still wins on cost/speed alone.
    unfiltered_front = pareto_front(quality_rows)
    assert any(r["eur_per_km2_yr"] == 5.0 for r in unfiltered_front), (
        "sanity check failed: infeasible row should dominate without a floor"
    )


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
        check_pareto()
        print("all checks passed")
    else:
        rows = run_sweep(CONFIG)
        write_csv(rows)
        plot_pareto(rows)
