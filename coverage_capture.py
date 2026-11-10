import argparse
import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat
import zipfile

import numpy as np

from coverage_engine import OUTCOME_CODES, evaluate_grid, summarize
from coverage_scenarios import make_scenarios
from simulator_engine import PROTOCOL, SIDE_KM, _check_sources


ROOT = Path(__file__).parent
STUDY_ID = "2026-11-10-coverage-atlas-v1"
SOURCE_NAMES = (
    "coverage_scenarios.py", "coverage_engine.py", "coverage_capture.py",
    "simulator_engine.py", "simulator_protocol.json", "research.py", "sweep.py",
)
ARRAY_NAMES = (
    "case_ids", "x_km", "y_km", "response_s", "selected_base_id", "outcome_code",
)
SUMMARY_FIELDS = (
    "case_id", "unreachable_cells", "late_cells", "timely_cells",
    "weather_closed_cells", "total_cells", "timely_area_fraction",
    "reachable_area_fraction",
)
GRID = {"order": "y-major-x-fast", "locations": "cell-centers", "north": "positive-y"}
LIMITATIONS = [
    "Synthetic square, hypothetical aircraft and fixed wind; not real geography or field validation.",
    "Equal-area cell-center approximation; not a season response rate or ignition probability.",
    "Each point is an independent single alert with all available drones initially idle; no queueing.",
    "Selected two-site outages are not exhaustive or worst-pair optimization.",
    "No terrain, time-varying weather, upstream detection latency, detector accuracy or flight control.",
    "Resolution differences are numerical sensitivity, not confidence intervals.",
    "Hashes establish source/artifact consistency, not authenticity or independent scientific validation.",
]


def _read(path, limit):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError(f"Capture component exceeds its byte limit: {Path(path).name}")
        data = handle.read(before.st_size + 1)
        after = os.fstat(handle.fileno())
    if (len(data) != before.st_size or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns or before.st_ino != after.st_ino):
        raise ValueError("Capture/source changed during bounded read")
    return data


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _current_source_hashes():
    _check_sources()
    return {name: _hash(_read(ROOT / name, 4 * 1024 * 1024)) for name in SOURCE_NAMES}


SOURCE_SHA256 = _current_source_hashes()


def _check_generation():
    if _current_source_hashes() != SOURCE_SHA256:
        raise ValueError("Coverage source generation changed; restart before continuing")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate capture JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError(f"Nonfinite capture JSON constant: {value}")


def _json(data):
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_reject_constant)
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Invalid capture JSON") from error


def _encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _registered(scenarios):
    registry = {case["case_id"]: case for case in make_scenarios()}
    if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= len(registry):
        raise ValueError("Capture needs a nonempty subset of registered scenarios")
    ids = []
    for case in scenarios:
        if (not isinstance(case, dict) or not isinstance(case.get("case_id"), str)
                or _encode(case) != _encode(registry.get(case["case_id"]))):
            raise ValueError("Capture scenario differs from the lead-authored registry")
        ids.append(case["case_id"])
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate capture scenario")
    return ids


def write_capture(root, scenarios=None, grid_n=80):
    _check_generation()
    if type(grid_n) is not int or not 1 <= grid_n <= 160:
        raise ValueError("grid_n must be an integer in [1, 160]")
    cases = copy.deepcopy(make_scenarios() if scenarios is None else scenarios)
    ids = _registered(cases)
    root = Path(root)
    root.mkdir()
    shape = (len(cases), grid_n, grid_n)
    response = np.full(shape, np.inf, dtype=np.float64)
    selected = np.full(shape, -1, dtype=np.int16)
    outcome = np.zeros(shape, dtype=np.uint8)
    rows = []
    for index, case in enumerate(cases):
        result = evaluate_grid(case, grid_n)
        response[index] = result["response_s"]
        selected[index] = result["selected_base_id"]
        outcome[index] = result["outcome_code"]
        rows.append(result["summary"])
    centers = result["x_km"]
    with (root / "scenarios.json").open("xb") as handle:
        handle.write(_encode(cases))
    with (root / "summary.csv").open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    with (root / "coverage.npz").open("xb") as handle:
        np.savez_compressed(
            handle, case_ids=np.array(ids, dtype="U128"), x_km=centers, y_km=centers,
            response_s=response, selected_base_id=selected, outcome_code=outcome)
    files = {name: _hash(_read(root / name, 128 * 1024 * 1024))
             for name in ("scenarios.json", "summary.csv", "coverage.npz")}
    _check_generation()
    manifest = {
        "schema_version": 1, "kind": "wildfire-coverage-atlas-capture", "study_id": STUDY_ID,
        "grid_n": grid_n, "domain_side_km": SIDE_KM,
        "timely_threshold_s": PROTOCOL["timely_threshold_s"],
        "outcome_codes": dict(OUTCOME_CODES), "source_sha256": dict(SOURCE_SHA256),
        "files": files, "grid": dict(GRID), "limitations": list(LIMITATIONS),
    }
    with (root / "manifest.json").open("xb") as handle:
        handle.write(_encode(manifest))
    load_capture(root)
    return root


def _summary(data, cases):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    if reader.fieldnames != list(SUMMARY_FIELDS):
        raise ValueError("Unexpected coverage summary columns")
    rows = []
    try:
        for row in reader:
            if set(row) != set(SUMMARY_FIELDS) or any(value is None for value in row.values()):
                raise ValueError("Malformed coverage summary row")
            parsed = {"case_id": row["case_id"]}
            for name in SUMMARY_FIELDS[1:6]:
                parsed[name] = int(row[name])
            for name in SUMMARY_FIELDS[6:]:
                parsed[name] = float(row[name])
            rows.append(parsed)
    except (TypeError, OverflowError) as error:
        raise ValueError("Malformed coverage summary value") from error
    if [row["case_id"] for row in rows] != [case["case_id"] for case in cases]:
        raise ValueError("Coverage summary case order mismatch")
    return rows


def _arrays(data, cases, grid_n):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if (len(members) != len(ARRAY_NAMES)
                or {member.filename for member in members} != {f"{name}.npy" for name in ARRAY_NAMES}
                or sum(member.file_size for member in members) > 256 * 1024 * 1024):
            raise ValueError("Unexpected/oversized coverage archive members")
    with np.load(io.BytesIO(data), allow_pickle=False) as archive:
        arrays = {name: archive[name].copy() for name in ARRAY_NAMES}
    shape = (len(cases), grid_n, grid_n)
    if (arrays["case_ids"].dtype.kind != "U"
            or arrays["case_ids"].shape != (len(cases),)
            or arrays["case_ids"].tolist() != [case["case_id"] for case in cases]):
        raise ValueError("Coverage archive case IDs mismatch")
    centers = (np.arange(grid_n, dtype=float) + .5) * SIDE_KM / grid_n
    for name in ("x_km", "y_km"):
        values = arrays[name]
        if (values.dtype.kind != "f" or values.dtype.itemsize != 8
                or values.shape != (grid_n,) or not np.array_equal(values, centers)):
            raise ValueError("Coverage center-coordinate mismatch")
    for name, kind, size in (
            ("response_s", "f", 8), ("selected_base_id", "i", 2), ("outcome_code", "u", 1)):
        values = arrays[name]
        if values.shape != shape or values.dtype.kind != kind or values.dtype.itemsize != size:
            raise ValueError(f"Coverage archive array mismatch: {name}")
    return arrays


def _validate_arrays(arrays, cases, rows):
    for index, case in enumerate(cases):
        response = arrays["response_s"][index]
        selected = arrays["selected_base_id"][index]
        outcome = arrays["outcome_code"][index]
        finite = np.isfinite(response)
        served = (outcome == OUTCOME_CODES["timely"]) | (outcome == OUTCOME_CODES["late"])
        if (np.isnan(response).any() or np.isneginf(response).any()
                or np.any(response[finite] < case["launch_latency_s"])
                or not np.array_equal(served, finite)
                or np.any(selected[~finite] != -1)
                or np.any(selected[finite] < 0) or np.any(selected[finite] >= case["n_bases"])
                or np.isin(selected[finite], case["offline_bases"]).any()):
            raise ValueError("Inconsistent coverage response/base/outcome arrays")
        if not np.array_equal(outcome == OUTCOME_CODES["timely"],
                              finite & (response <= PROTOCOL["timely_threshold_s"])):
            raise ValueError("Coverage deadline classifications mismatch")
        weather_closed = math.hypot(*case["wind_mps"]) > PROTOCOL["max_wind_mps"]
        if weather_closed:
            if not np.all(outcome == OUTCOME_CODES["weather_closed"]):
                raise ValueError("Weather-closed coverage has served/nonweather cells")
        elif np.any(outcome == OUTCOME_CODES["weather_closed"]):
            raise ValueError("Open-weather scenario contains closure cells")
        if rows[index] != summarize(case["case_id"], outcome):
            raise ValueError("Coverage summary differs from captured array counts")


def load_capture(root):
    _check_generation()
    root = Path(root)
    try:
        manifest_bytes = _read(root / "manifest.json", 65536)
        manifest = _json(manifest_bytes)
        expected_keys = {
            "schema_version", "kind", "study_id", "grid_n", "domain_side_km",
            "timely_threshold_s", "outcome_codes", "source_sha256", "files", "grid",
            "limitations",
        }
        if not isinstance(manifest, dict) or set(manifest) != expected_keys:
            raise ValueError("Unexpected coverage manifest fields")
        grid_n = manifest["grid_n"]
        if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
                or manifest["kind"] != "wildfire-coverage-atlas-capture"
                or manifest["study_id"] != STUDY_ID
                or type(grid_n) is not int or not 1 <= grid_n <= 160
                or manifest["domain_side_km"] != SIDE_KM
                or manifest["timely_threshold_s"] != PROTOCOL["timely_threshold_s"]
                or not isinstance(manifest["outcome_codes"], dict)
                or any(type(value) is not int for value in manifest["outcome_codes"].values())
                or manifest["outcome_codes"] != OUTCOME_CODES
                or manifest["source_sha256"] != SOURCE_SHA256
                or manifest["grid"] != GRID or manifest["limitations"] != LIMITATIONS):
            raise ValueError("Coverage manifest/source generation mismatch")
        expected_files = {"scenarios.json": 4, "summary.csv": 4, "coverage.npz": 128}
        if not isinstance(manifest["files"], dict) or set(manifest["files"]) != set(expected_files):
            raise ValueError("Unexpected coverage capture filenames")
        frozen = {}
        for name, max_mb in expected_files.items():
            data = _read(root / name, max_mb * 1024 * 1024)
            if _hash(data) != manifest["files"][name]:
                raise ValueError(f"Coverage capture checksum mismatch: {name}")
            frozen[name] = data
        cases = _json(frozen["scenarios.json"])
        _registered(cases)
        rows = _summary(frozen["summary.csv"], cases)
        arrays = _arrays(frozen["coverage.npz"], cases, grid_n)
        _validate_arrays(arrays, cases, rows)
        _check_generation()
    except (UnicodeError, zipfile.BadZipFile, EOFError, KeyError, TypeError) as error:
        raise ValueError("Malformed coverage capture") from error
    for array in arrays.values():
        array.setflags(write=False)
    return {
        "manifest": manifest, "scenarios": cases, "summary_rows": rows, "arrays": arrays,
        "capture_sha256": _hash(manifest_bytes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Capture the fixed synthetic coverage atlas")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--grid-n", type=int, default=80, choices=range(1, 161))
    args = parser.parse_args(argv)
    try:
        root = write_capture(args.output, grid_n=args.grid_n)
    except (ValueError, OSError) as error:
        parser.exit(2, f"coverage capture: {error}\n")
    print(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
