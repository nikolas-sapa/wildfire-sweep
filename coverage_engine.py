import math
import re

import numpy as np

from coverage_scenarios import PROFILES
from research import MissionConfig, flight_times
from simulator_engine import (
    MODEL_CONFIG, PROTOCOL, SIDE_KM, _check_sources, _parameters, layout_bases,
)


OUTCOME_CODES = {"unreachable": 0, "late": 1, "timely": 2, "weather_closed": 3}
SCENARIO_KEYS = {
    "case_id", "n_bases", "wind_mps", "wind_speed_mps", "heading_deg", "profile",
    "offline_bases", "airspeed_mps", "endurance_min", "reserve_fraction",
    "launch_latency_s",
}


def validate_scenario(scenario):
    if not isinstance(scenario, dict) or set(scenario) != SCENARIO_KEYS:
        raise ValueError("Expected exactly the documented coverage scenario fields")
    case_id = scenario["case_id"]
    if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", case_id):
        raise ValueError("Invalid coverage case ID")
    values = _parameters({
        key: scenario[key] for key in (
            "n_bases", "wind_mps", "airspeed_mps", "endurance_min",
            "reserve_fraction", "launch_latency_s")
    })
    offline = scenario["offline_bases"]
    if (not isinstance(offline, list) or any(
            type(site) is not int or not 0 <= site < values["n_bases"] for site in offline)
            or offline != sorted(set(offline))):
        raise ValueError("offline_bases must be unique sorted original base IDs")
    speed = scenario["wind_speed_mps"]
    if (type(speed) not in (int, float) or not math.isfinite(speed)
            or speed < 0 or not math.isclose(
                speed, math.hypot(*values["wind_mps"]), rel_tol=0, abs_tol=1e-12)):
        raise ValueError("Declared wind speed disagrees with vector")
    heading = scenario["heading_deg"]
    if heading is None:
        if speed != 0:
            raise ValueError("Only calm cases have no heading")
    elif (type(heading) not in (int, float) or not math.isfinite(heading)
          or not 0 <= heading < 360):
        raise ValueError("Invalid wind heading")
    if not isinstance(scenario["profile"], str) or scenario["profile"] not in PROFILES:
        raise ValueError("Unknown coverage profile")
    return values


def evaluate_points(scenario, points_km):
    _check_sources()
    values = validate_scenario(scenario)
    points = np.asarray(points_km, dtype=float)
    if (points.ndim != 2 or points.shape[1] != 2 or not len(points)
            or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > SIDE_KM)):
        raise ValueError("Expected finite N x 2 points inside the synthetic domain")
    bases = layout_bases(values["n_bases"])
    active = [base for base in bases if base["id"] not in scenario["offline_bases"]]
    response = np.full(len(points), np.inf)
    selected = np.full(len(points), -1, dtype=np.int16)
    outcomes = np.zeros(len(points), dtype=np.uint8)
    mission = MissionConfig(
        airspeed_mps=values["airspeed_mps"], wind_mps=tuple(values["wind_mps"]),
        endurance_min=values["endurance_min"], reserve_fraction=values["reserve_fraction"],
        max_wind_mps=PROTOCOL["max_wind_mps"])
    if math.hypot(*mission.wind_mps) > mission.max_wind_mps:
        outcomes.fill(OUTCOME_CODES["weather_closed"])
    elif active:
        coordinates = np.array([[base["x_km"], base["y_km"]] for base in active])
        displacements = points[:, None, :] - coordinates[None, :, :]
        # Each point is a separate idle-network mission, never a queued sequence.
        outbound, inbound = flight_times(
            displacements.reshape(-1, 2), mission.airspeed_mps, mission.wind_mps)
        outbound = outbound.reshape(len(points), len(active))
        inbound = inbound.reshape(len(points), len(active))
        airborne = outbound + MODEL_CONFIG["dwell_s"] + inbound
        budget = mission.endurance_min * 60 * (1 - mission.reserve_fraction)
        eligible = np.isfinite(airborne) & (airborne <= budget + 1e-9)
        arrivals = np.where(eligible, values["launch_latency_s"] + outbound, np.inf)
        local_choice = np.argmin(arrivals, axis=1)
        response = arrivals[np.arange(len(points)), local_choice]
        reachable = np.isfinite(response)
        ids = np.array([base["id"] for base in active], dtype=np.int16)
        selected[reachable] = ids[local_choice[reachable]]
        outcomes[reachable] = OUTCOME_CODES["late"]
        outcomes[response <= PROTOCOL["timely_threshold_s"]] = OUTCOME_CODES["timely"]
    _check_sources()
    return {"response_s": response, "selected_base_id": selected, "outcome_code": outcomes}


def summarize(case_id, outcomes):
    counts = {f"{name}_cells": int(np.count_nonzero(outcomes == code))
              for name, code in OUTCOME_CODES.items()}
    total = int(outcomes.size)
    if not total or sum(counts.values()) != total:
        raise ValueError("Coverage outcomes must be exhaustive and nonempty")
    return {
        "case_id": case_id, **counts, "total_cells": total,
        "timely_area_fraction": counts["timely_cells"] / total,
        "reachable_area_fraction": (counts["timely_cells"] + counts["late_cells"]) / total,
    }


def evaluate_grid(scenario, grid_n=80):
    if type(grid_n) is not int or not 1 <= grid_n <= 160:
        raise ValueError("grid_n must be an integer in [1, 160]")
    centers = (np.arange(grid_n, dtype=float) + .5) * SIDE_KM / grid_n
    x, y = np.meshgrid(centers, centers)
    result = evaluate_points(scenario, np.column_stack([x.ravel(), y.ravel()]))
    result = {name: array.reshape(grid_n, grid_n) for name, array in result.items()}
    result.update(x_km=centers.copy(), y_km=centers.copy())
    result["summary"] = summarize(scenario["case_id"], result["outcome_code"])
    return result
