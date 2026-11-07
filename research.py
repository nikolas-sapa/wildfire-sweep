import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess

import numpy as np

from sweep import CONFIG, base_grid, cost_per_km2_yr, dispatch, generate_season


@dataclass(frozen=True)
class MissionConfig:
    airspeed_mps: float = 20.0
    wind_mps: tuple[float, float] = (0.0, 0.0)
    endurance_min: float = 46.0
    reserve_fraction: float = 0.25
    max_wind_mps: float = 12.0

    def __post_init__(self):
        values = (self.airspeed_mps, self.endurance_min, self.max_wind_mps)
        if any(not math.isfinite(v) or v <= 0 for v in values):
            raise ValueError("Airspeed, endurance and wind limit must be finite and positive")
        if not math.isfinite(self.reserve_fraction) or not 0 <= self.reserve_fraction < 1:
            raise ValueError("Reserve must be a finite fraction in [0, 1)")
        if len(self.wind_mps) != 2 or not all(math.isfinite(v) for v in self.wind_mps):
            raise ValueError("Wind must contain two finite Cartesian components")


def flight_times(displacements_km, airspeed_mps, wind_mps):
    vectors = np.asarray(displacements_km, dtype=float)
    wind = np.asarray(wind_mps, dtype=float)
    if vectors.ndim != 2 or vectors.shape[1] != 2 or wind.shape != (2,):
        raise ValueError("Expected N x 2 displacement vectors and a two-component wind")
    if not np.isfinite(vectors).all() or not np.isfinite(wind).all():
        raise ValueError("Geometry must be finite")
    if not math.isfinite(airspeed_mps) or airspeed_mps <= 0:
        raise ValueError("Airspeed must be finite and positive")
    distance_m = np.linalg.norm(vectors, axis=1) * 1000.0
    direction = np.divide(vectors, distance_m[:, None] / 1000.0,
                          out=np.zeros_like(vectors), where=distance_m[:, None] > 0)
    along = direction @ wind
    cross_squared = np.maximum(0.0, float(wind @ wind) - along ** 2)
    feasible = cross_squared < airspeed_mps ** 2
    along_air = np.sqrt(np.maximum(0.0, airspeed_mps ** 2 - cross_squared))
    outbound = along_air + along
    inbound = along_air - along
    out_s = np.divide(distance_m, outbound, out=np.full(len(vectors), np.inf),
                      where=feasible & (outbound > 0))
    back_s = np.divide(distance_m, inbound, out=np.full(len(vectors), np.inf),
                       where=feasible & (inbound > 0))
    out_s[distance_m == 0] = 0.0
    back_s[distance_m == 0] = 0.0
    return out_s, back_s


def dispatch_physical(t_s, xy_km, bases_km, drones_per_base, launch_latency_s, cfg, mission):
    times = np.asarray(t_s, dtype=float)
    points = np.asarray(xy_km, dtype=float)
    bases = np.asarray(bases_km, dtype=float)
    if times.ndim != 1 or points.shape != (len(times), 2):
        raise ValueError("Alerts must contain aligned times and N x 2 coordinates")
    if bases.ndim != 2 or bases.shape[1] != 2 or not len(bases):
        raise ValueError("At least one two-dimensional base is required")
    if not all(np.isfinite(x).all() for x in (times, points, bases)) or np.any(np.diff(times) < 0):
        raise ValueError("Alert times must be sorted and geometry finite")
    if isinstance(drones_per_base, bool) or not isinstance(drones_per_base, (int, np.integer)) or drones_per_base < 1:
        raise ValueError("Drone count must be a positive integer")
    if any(not math.isfinite(v) or v < 0 for v in (launch_latency_s, cfg["dwell_s"], cfg["turnaround_s"])):
        raise ValueError("Launch, dwell and turnaround must be finite and nonnegative")
    if not math.isfinite(cfg["season_days"]) or cfg["season_days"] <= 0:
        raise ValueError("Season duration must be finite and positive")
    drone_xy = np.repeat(bases, drones_per_base, axis=0)
    free_at = np.zeros(len(drone_xy))
    responses = np.full(len(times), np.inf)
    statuses = []
    busy_s = 0.0
    budget_s = mission.endurance_min * 60 * (1 - mission.reserve_fraction)
    weather_closed = math.hypot(*mission.wind_mps) > mission.max_wind_mps
    for index, (alert_s, point) in enumerate(zip(times, points)):
        if weather_closed:
            statuses.append("weather_rejected")
            continue
        out_s, back_s = flight_times(point - drone_xy, mission.airspeed_mps, mission.wind_mps)
        airborne_s = out_s + cfg["dwell_s"] + back_s
        eligible = np.isfinite(airborne_s) & (airborne_s <= budget_s + 1e-9)
        if not eligible.any():
            statuses.append("battery_rejected" if np.isfinite(airborne_s).any() else "flight_rejected")
            continue
        arrival = np.where(eligible, np.maximum(free_at, alert_s) + launch_latency_s + out_s, np.inf)
        drone = int(np.argmin(arrival))
        responses[index] = arrival[drone] - alert_s
        occupied_s = launch_latency_s + airborne_s[drone] + cfg["turnaround_s"]
        free_at[drone] = max(free_at[drone], alert_s) + occupied_s
        busy_s += occupied_s
        statuses.append("served")
    return {
        "response_s": responses,
        "status": statuses,
        "utilisation": busy_s / (len(drone_xy) * cfg["season_days"] * 86400),
    }


def nearest_rank(values, probability):
    values = np.asarray(values, dtype=float)
    if not 0 < probability <= 1 or values.ndim != 1 or np.isnan(values).any() or (values < 0).any():
        raise ValueError("Expected nonnegative observations and probability in (0, 1]")
    if not len(values):
        return None
    return float(np.sort(values)[math.ceil(probability * len(values)) - 1])


def success_interval(successes, totals, seed, replicates=1000):
    successes, totals = np.asarray(successes), np.asarray(totals)
    if successes.ndim != 1 or successes.shape != totals.shape or not len(totals):
        raise ValueError("Expected aligned nonempty season counts")
    if (not np.isfinite(successes).all() or not np.isfinite(totals).all()
            or np.any(successes < 0) or np.any(totals < successes)
            or np.any(successes != np.floor(successes)) or np.any(totals != np.floor(totals))):
        raise ValueError("Counts must be finite nonnegative integers with successes <= totals")
    if isinstance(replicates, bool) or not isinstance(replicates, int) or replicates < 1:
        raise ValueError("Bootstrap replicates must be a positive integer")
    if not totals.sum():
        return None, None, None
    estimate = float(successes.sum() / totals.sum())
    if len(totals) < 2:
        return estimate, None, None
    draws = np.random.default_rng(seed).integers(0, len(totals), (replicates, len(totals)))
    denominators = totals[draws].sum(axis=1)
    ratios = successes[draws].sum(axis=1)[denominators > 0] / denominators[denominators > 0]
    if not len(ratios):
        return estimate, None, None
    low, high = np.quantile(ratios, [0.025, 0.975])
    return estimate, float(low), float(high)


def write_rows(path, rows):
    with Path(path).open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_study(output, seasons=200, seed=20260811, ignitions=307.0, fp_rate=0.15):
    if isinstance(seasons, bool) or not isinstance(seasons, int) or seasons < 1:
        raise ValueError("Seasons must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("Seed must be a nonnegative integer")
    if not math.isfinite(ignitions) or ignitions <= 0 or not math.isfinite(fp_rate) or not 0 <= fp_rate < 1:
        raise ValueError("Ignitions must be positive and false-alarm fraction in [0, 1)")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    captures = []
    for season in range(seasons):
        rng = np.random.default_rng(np.random.SeedSequence([seed, season]))
        captures.append(generate_season(rng, CONFIG, ignitions, fp_rate))
    offsets = np.cumsum([0] + [len(c[0]) for c in captures])
    inputs = output / "alerts.npz"
    np.savez_compressed(inputs, offsets=offsets, times=np.concatenate([c[0] for c in captures]),
                        points=np.concatenate([c[1] for c in captures]),
                        is_real=np.concatenate([c[2] for c in captures]))
    scenarios = [("legacy", CONFIG["cruise_mps"], 0.0)] + [
        ("physical", speed, wind) for speed in (18.0, 20.0) for wind in (0.0, 4.0, 8.0, 12.0)
    ]
    summary, season_rows = [], []
    for spacing, drones in ((26.0, 2), (16.0, 1), (12.0, 1), (8.0, 1)):
        bases = base_grid(spacing, CONFIG["domain_km2"])
        for mode, speed, wind in scenarios:
            scenario = f"{mode}-s{spacing:g}-d{drones}-v{speed:g}-w{wind:g}"
            responses, successes, totals, rejected, late = [], [], [], [], []
            mission = MissionConfig(airspeed_mps=speed, wind_mps=(wind, 0.0))
            for season, (times, points, truth) in enumerate(captures):
                if mode == "legacy":
                    response, utilisation = dispatch(times, points, bases, drones, 60.0, CONFIG)
                else:
                    result = dispatch_physical(times, points, bases, drones, 60.0, CONFIG, mission)
                    response, utilisation = result["response_s"], result["utilisation"]
                real = response[truth]
                responses.append(real)
                total = len(real)
                success = int(np.count_nonzero(real <= CONFIG["unserved_threshold_s"]))
                rejection = int(np.count_nonzero(~np.isfinite(real)))
                late_count = total - success - rejection
                totals.append(total)
                successes.append(success)
                rejected.append(rejection)
                late.append(late_count)
                season_rows.append({
                    "scenario": scenario, "season": season, "real_alerts": total,
                    "within_15min": success, "rejected": rejection,
                    "served_late": late_count, "utilisation_workload_ratio": utilisation,
                })
            combined = np.concatenate(responses)
            probability, low, high = success_interval(np.array(successes), np.array(totals), seed=seed)
            p90 = nearest_rank(combined, 0.9)
            np.savez_compressed(output / f"{scenario}.npz", response_s=combined,
                                offsets=np.cumsum([0] + totals))
            summary.append({
                "scenario": scenario, "mode": mode, "nominal_spacing_km": spacing,
                "actual_spacing_km": math.sqrt(CONFIG["domain_km2"] / len(bases)),
                "n_bases": len(bases), "drones_per_base": drones, "airspeed_mps": speed,
                "wind_east_mps": wind, "real_alerts": sum(totals),
                "within_15min_share": probability, "mc_95ci_low": low, "mc_95ci_high": high,
                "rejected_share": sum(rejected) / sum(totals) if sum(totals) else None,
                "served_late_share": sum(late) / sum(totals) if sum(totals) else None,
                "p90_s": p90 if p90 is not None and math.isfinite(p90) else None,
                "p90_unreachable": p90 is not None and math.isinf(p90),
                "eur_per_km2_yr": cost_per_km2_yr(len(bases), drones, CONFIG),
            })
    write_rows(output / "summary.csv", summary)
    write_rows(output / "seasons.csv", season_rows)
    source_paths = [Path(__file__), Path(__file__).with_name("sweep.py")]
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                              capture_output=True, text=True, check=False)
    metadata = {
        "schema_version": 1, "study_type": "synthetic Monte Carlo, not field validation",
        "seasons": seasons, "seed": seed, "ignitions_per_season": ignitions,
        "false_alarm_fraction": fp_rate, "launch_latency_s": 60.0,
        "legacy_config": CONFIG, "physical_defaults": asdict(MissionConfig()),
        "scenarios": scenarios, "python": platform.python_version(), "numpy": np.__version__,
        "git_parent_revision": revision.stdout.strip() if revision.returncode == 0 else None,
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths},
        "alerts_sha256": hashlib.sha256(inputs.read_bytes()).hexdigest(),
        "metric": "event-weighted alert-to-arrival; all real alerts, including rejection",
        "quantile": "pooled nearest rank; blank p90 with p90_unreachable=True means infinity",
        "interval": "1000 season-cluster percentile bootstrap draws, 95%; Monte Carlo error only",
        "assumptions": [
            "Uniform locations/times, Poisson ignitions; no terrain, obstacles or fire growth.",
            "Wind vector blows toward positive x in km-coordinate frame; constant throughout each season.",
            "Track-holding constant airspeed, flat 2D geometry; not a power/drag or gust model.",
            "Airborne time includes outbound, dwell and return; launch and turnaround use no airborne budget.",
            "Full usable battery after each turnaround; no battery ageing or temperature derating.",
            "Weather/battery-infeasible alerts rejected immediately, no future weather retry.",
            "External alerts already exist; upstream detection latency and missed detections excluded.",
            "Legacy costs retained, including unbounded fleet supervision and proxy operating costs.",
            "Intervals exclude model, cost and environmental uncertainty; scenarios are not weather probabilities.",
            "Nearest-rank pooled quantiles differ from legacy mean-of-season interpolated quantiles.",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Separate wind/battery research track; historical outputs untouched")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seasons", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260811)
    parser.add_argument("--ignitions", type=float, default=307.0)
    parser.add_argument("--false-alarm-rate", type=float, default=0.15)
    args = parser.parse_args()
    rows = run_study(args.output, args.seasons, args.seed, args.ignitions, args.false_alarm_rate)
    print(f"Wrote {len(rows)} scenarios to {args.output}; synthetic simulation, not field evidence")


if __name__ == "__main__":
    main()
