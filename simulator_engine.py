import copy
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from research import MissionConfig, dispatch_physical, flight_times
from sweep import CONFIG, base_grid


ROOT = Path(__file__).parent
PROTOCOL = json.loads((ROOT / "simulator_protocol.json").read_bytes())
SOURCE_NAMES = ("simulator_engine.py", "simulator_protocol.json", "research.py", "sweep.py")
SOURCE_SHA256 = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                 for name in SOURCE_NAMES}
MODEL_CONFIG = copy.deepcopy(CONFIG)
SIDE_KM = math.sqrt(MODEL_CONFIG["domain_km2"])
SPACINGS = {row["n_bases"]: row["nominal_spacing_km"] for row in PROTOCOL["layouts"]}


def _check_sources():
    actual = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
              for name in SOURCE_NAMES}
    if actual != SOURCE_SHA256:
        raise ValueError("Model sources changed; restart the local simulator")


def default_parameters():
    values = copy.deepcopy(PROTOCOL["defaults"])
    values["point_km"] = [fraction * SIDE_KM for fraction in values.pop("point_fraction")]
    return values


def layout_bases(n_bases, offline_base=None):
    if type(n_bases) is not int or n_bases not in SPACINGS:
        raise ValueError("n_bases must be 9 or 25")
    if offline_base is not None and (
            type(offline_base) is not int or not 0 <= offline_base < n_bases):
        raise ValueError("offline_base must be null or an original base index")
    coordinates = base_grid(SPACINGS[n_bases], MODEL_CONFIG["domain_km2"])
    if len(coordinates) != n_bases:
        raise ValueError("Declared layout does not match model geometry")
    return [{"id": index, "x_km": float(point[0]), "y_km": float(point[1]),
             "available": index != offline_base}
            for index, point in enumerate(coordinates)]


def model_metadata():
    _check_sources()
    return {
        "domain_side_km": SIDE_KM,
        "defaults": default_parameters(),
        "parameter_limits": copy.deepcopy(PROTOCOL["parameter_limits"]),
        "layouts": {str(count): layout_bases(count) for count in SPACINGS},
        "assumptions": {
            "dwell_s": MODEL_CONFIG["dwell_s"],
            "turnaround_s": MODEL_CONFIG["turnaround_s"],
            "max_wind_mps": PROTOCOL["max_wind_mps"],
            "queueing": False,
        },
        "source_sha256": dict(SOURCE_SHA256),
        "limitations": list(PROTOCOL["limitations"]),
    }


def _number(value, name, low, high):
    if type(value) not in (int, float) or not low <= value <= high:
        raise ValueError(f"{name} must be a finite number in [{low:g}, {high:g}]")
    return float(value)


def _parameters(payload):
    defaults = default_parameters()
    if not isinstance(payload, dict) or set(payload) - set(defaults):
        raise ValueError("Expected a mission object containing only documented input fields")
    values = {**defaults, **copy.deepcopy(payload)}
    layout_bases(values["n_bases"], values["offline_base"])
    limits = PROTOCOL["parameter_limits"]
    for name in ("airspeed_mps", "endurance_min", "reserve_fraction", "launch_latency_s"):
        values[name] = _number(values[name], name, *limits[name])
    for name in ("point_km", "wind_mps"):
        vector = values[name]
        if not isinstance(vector, (list, tuple)) or len(vector) != 2:
            raise ValueError(f"{name} must contain exactly two numbers")
        bounds = (0, SIDE_KM) if name == "point_km" else limits["wind_component_mps"]
        values[name] = [_number(value, name, *bounds) for value in vector]
    return values


def _finite(value):
    return float(value) if math.isfinite(value) else None


def run_mission(payload):
    _check_sources()
    values = _parameters(payload)
    bases = layout_bases(values["n_bases"], values["offline_base"])
    coordinates = np.array([[base["x_km"], base["y_km"]] for base in bases])
    available = np.array([base["available"] for base in bases])
    mission = MissionConfig(
        airspeed_mps=values["airspeed_mps"], wind_mps=tuple(values["wind_mps"]),
        endurance_min=values["endurance_min"], reserve_fraction=values["reserve_fraction"],
        max_wind_mps=PROTOCOL["max_wind_mps"])
    result = dispatch_physical(
        np.array([0.0]), np.array([values["point_km"]]), coordinates[available],
        1, values["launch_latency_s"], MODEL_CONFIG, mission)
    response = float(result["response_s"][0])
    status = result["status"][0]
    outbound, inbound = flight_times(
        np.asarray(values["point_km"]) - coordinates, mission.airspeed_mps, mission.wind_mps)
    airborne = outbound + MODEL_CONFIG["dwell_s"] + inbound
    usable = mission.endurance_min * 60 * (1 - mission.reserve_fraction)
    weather_closed = math.hypot(*mission.wind_mps) > mission.max_wind_mps
    flight_ok = np.isfinite(airborne)
    battery_ok = flight_ok & (airborne <= usable + 1e-9)
    eligible = available & battery_ok & (not weather_closed)
    arrival = values["launch_latency_s"] + outbound
    selected = int(np.argmin(np.where(eligible, arrival, np.inf))) if eligible.any() else None
    if ((selected is None) != (status != "served")
            or selected is not None and not math.isclose(
                response, float(arrival[selected]), rel_tol=1e-12, abs_tol=1e-9)):
        raise ValueError("Candidate explanation disagrees with the authoritative dispatcher")
    candidates = []
    for index, base in enumerate(bases):
        reason = ("offline" if not base["available"] else "weather" if weather_closed else
                  "flight" if not flight_ok[index] else "battery" if not battery_ok[index] else "eligible")
        candidates.append({
            "base_id": index, "outbound_s": _finite(outbound[index]),
            "return_s": _finite(inbound[index]), "airborne_s": _finite(airborne[index]),
            "arrival_s": _finite(arrival[index]), "flight_ok": bool(flight_ok[index]),
            "battery_ok": bool(battery_ok[index]), "eligible": bool(eligible[index]),
            "reason": reason,
        })
    _check_sources()
    return {
        "schema_version": 1, "mode": "mission", "inputs": values, "domain_side_km": SIDE_KM,
        "point_km": list(values["point_km"]), "bases": bases, "candidates": candidates,
        "selected_base_id": selected, "status": status, "response_s": _finite(response),
        "within_15min": bool(response <= PROTOCOL["timely_threshold_s"]),
        "usable_airborne_s": usable, "assumptions": model_metadata()["assumptions"],
        "source_sha256": dict(SOURCE_SHA256), "limitations": list(PROTOCOL["limitations"]),
    }
