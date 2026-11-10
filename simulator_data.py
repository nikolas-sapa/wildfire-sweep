import copy
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import stat

import numpy as np

from capture_integrity import verify_capture
from simulator_engine import ROOT, model_metadata


DEFAULT_CAPTURE = ROOT / "research_results" / "2026-11-09-resilience"
SNAPSHOT_FILES = (
    "manifest.json", "config.json", "protocol.json", "summary.csv", "contrasts.csv",
    "heldout_counts.csv", "base_sites.csv", "heldout_alerts.npz", "heldout_responses.npz",
)
INTEGER_COLUMNS = {
    "n_bases", "drones_per_base", "offline_base", "active_bases", "real_alerts",
    "within_15min", "rejected", "served_late", "season", "site_id",
}
TEXT_COLUMNS = {"case_id", "contrast", "kind", "candidate", "reference"}


def _snapshot(path, expected):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > 64 * 1024 * 1024:
            raise ValueError("Replay inputs must be regular files no larger than 64 MiB")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1048576))
            if not chunk:
                raise ValueError("Replay input truncated during snapshot")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise ValueError("Replay input grew during snapshot")
        after = os.fstat(descriptor)
        signature = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                  info.st_mtime_ns, info.st_ctime_ns)
        content = b"".join(chunks)
        if signature(before) != signature(after) or hashlib.sha256(content).hexdigest() != expected:
            raise ValueError("Replay input changed during snapshot")
        return content
    finally:
        os.close(descriptor)


def _rows(content):
    rows = []
    for row in csv.DictReader(io.StringIO(content.decode("utf-8"))):
        values = {}
        for key, value in row.items():
            if value == "" and key not in TEXT_COLUMNS:
                values[key] = None
            elif key in TEXT_COLUMNS:
                values[key] = value
            elif key in INTEGER_COLUMNS:
                values[key] = int(value)
            else:
                values[key] = float(value)
                if not math.isfinite(values[key]):
                    raise ValueError("Non-finite captured CSV number")
        rows.append(values)
    return rows


def _arrays(content, expected_keys):
    with np.load(io.BytesIO(content), allow_pickle=False) as archive:
        if set(archive.files) != set(expected_keys):
            raise ValueError("Unexpected captured array keys")
        result = {name: archive[name].copy() for name in expected_keys}
    for array in result.values():
        array.setflags(write=False)
    return result


class ExplorerData:
    def __init__(self, capture_dir=DEFAULT_CAPTURE):
        root = Path(capture_dir)
        receipt = verify_capture(str(root))
        digests = {**receipt["artifact_sha256"], "manifest.json": receipt["manifest_sha256"]}
        if set(SNAPSHOT_FILES) - set(digests):
            raise ValueError("Capture lacks required replay artifacts")
        content = {name: _snapshot(root / name, digests[name]) for name in SNAPSHOT_FILES}
        manifest = json.loads(content["manifest.json"])
        protocol = json.loads(content["protocol.json"])
        config = json.loads(content["config.json"])
        if protocol != manifest["protocol"] or config != manifest["config"]:
            raise ValueError("Capture configuration disagrees with manifest")
        self._alerts = _arrays(content["heldout_alerts.npz"], ("offsets", "times", "points", "is_real"))
        self._responses = _arrays(content["heldout_responses.npz"], ("case_ids", "responses_s"))
        self._summary = _rows(content["summary.csv"])
        self._contrasts = _rows(content["contrasts.csv"])
        cases = self._summary
        if len(cases) != manifest["heldout_cases"]:
            raise ValueError("Capture case count disagrees with manifest")
        self._case_lookup = {case["case_id"]: copy.deepcopy(case) for case in cases}
        self._case_indices = {str(case): index for index, case in enumerate(self._responses["case_ids"])}
        self._seasons = protocol["heldout_seasons"]
        self._season_days = config["season_days"]
        self._side = math.sqrt(config["domain_km2"])
        self._threshold = protocol["timely_threshold_s"]
        self._counts = {(row["case_id"], row["season"]): row
                        for row in _rows(content["heldout_counts.csv"])}
        self._sites = _rows(content["base_sites.csv"])
        self._validate()
        if verify_capture(str(root)) != receipt:
            raise ValueError("Capture changed while loading replay")
        self._manifest_sha256 = receipt["manifest_sha256"]
        self._limitations = [
            *manifest["limitations"],
            "Read-only captured synthetic outcomes, not live simulation or field validation.",
            "Replay includes all alerts; captured counts and study rates concern real ignitions only.",
            "Captured responses do not identify dispatch bases, trajectories or rejection causes.",
            "Checksums verify consistency, not authenticity or correctness of a supplied capture.",
        ]
        self._study = {
            "id": "2026-11-09-resilience", "manifest_sha256": self._manifest_sha256,
            "heldout_seasons": self._seasons, "training_seasons": protocol["training_seasons"],
            "heldout_real_alerts": manifest["heldout_real_alerts"],
            "cases": [{
                "case_id": case["case_id"], "n_bases": case["n_bases"],
                "wind_east_mps": case["wind_east_mps"],
                "offline_base": None if case["offline_base"] == -1 else case["offline_base"],
                "active_bases": case["n_bases"] - (case["offline_base"] != -1),
            } for case in cases],
            "summary": self._summary, "contrasts": self._contrasts,
            "limitations": self._limitations,
        }

    def _validate(self):
        offsets = self._alerts["offsets"]
        times = self._alerts["times"]
        points = self._alerts["points"]
        real = self._alerts["is_real"]
        responses = self._responses["responses_s"]
        if (offsets.shape != (self._seasons + 1,) or offsets.dtype.kind not in "iu"
                or offsets[0] != 0 or offsets[-1] != len(times) or np.any(np.diff(offsets) < 0)
                or points.shape != (len(times), 2) or real.shape != (len(times),)
                or real.dtype.kind != "b" or not np.isfinite(times).all()
                or not np.isfinite(points).all() or np.any(points < 0) or np.any(points > self._side)
                or np.any(times < 0) or np.any(times > self._season_days * 86400)
                or responses.shape != (len(self._case_lookup), len(times))
                or np.isnan(responses).any() or np.any(responses < 0)
                or set(self._case_lookup) != set(self._case_indices)
                or len(self._case_indices) != len(self._responses["case_ids"])):
            raise ValueError("Invalid captured replay array alignment")
        for season in range(self._seasons):
            start, stop = offsets[season:season + 2]
            if np.any(np.diff(times[start:stop]) < 0):
                raise ValueError("Captured alerts are not sorted")
        expected = {(case, season) for case in self._case_lookup for season in range(self._seasons)}
        if set(self._counts) != expected:
            raise ValueError("Captured season counts do not cover every case and season")

    def catalog(self):
        return {
            "schema_version": 1, "mode": "catalog", **model_metadata(),
            "study": copy.deepcopy(self._study),
        }

    def replay(self, case_id, season):
        if (not isinstance(case_id, str) or case_id not in self._case_lookup
                or type(season) is not int or not 0 <= season < self._seasons):
            raise ValueError("Expected a captured case and integer season in range")
        start, stop = self._alerts["offsets"][season:season + 2]
        case = self._case_lookup[case_id]
        responses = self._responses["responses_s"][self._case_indices[case_id], start:stop]
        alerts = []
        for local, (index, response) in enumerate(zip(range(start, stop), responses)):
            timely = bool(response <= self._threshold)
            alerts.append({
                "index": local, "alert_s": float(self._alerts["times"][index]),
                "x_km": float(self._alerts["points"][index, 0]),
                "y_km": float(self._alerts["points"][index, 1]),
                "is_real": bool(self._alerts["is_real"][index]),
                "response_s": float(response) if math.isfinite(response) else None,
                "within_15min": timely,
                "status": "within_15min" if timely else "late" if math.isfinite(response) else "unreachable",
            })
        return {
            "schema_version": 1, "mode": "replay", "case_id": case_id, "season": season,
            "domain_side_km": self._side, "season_days": self._season_days,
            "bases": [{
                "id": row["site_id"], "x_km": row["x_km"], "y_km": row["y_km"],
                "available": row["site_id"] != case["offline_base"],
            } for row in self._sites if row["n_bases"] == case["n_bases"]],
            "counts": copy.deepcopy(self._counts[case_id, season]),
            "study_manifest_sha256": self._manifest_sha256, "alerts": alerts,
            "limitations": list(self._limitations),
        }
