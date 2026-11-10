import copy
import math
from pathlib import Path

from coverage_capture import STUDY_ID, load_capture
from simulator_engine import ROOT, layout_bases


DEFAULT_CAPTURE = ROOT / "research_results" / STUDY_ID


class CoverageData:
    def __init__(self, root=None):
        self._root = Path(DEFAULT_CAPTURE if root is None else root)

    def _load(self):
        loaded = load_capture(self._root)
        manifest = loaded["manifest"]
        summaries = {row["case_id"]: row for row in loaded["summary_rows"]}
        cases = []
        for scenario in loaded["scenarios"]:
            cases.append({
                **copy.deepcopy(scenario),
                "summary": copy.deepcopy(summaries[scenario["case_id"]]),
            })
        return {
            "manifest": manifest,
            "cases": cases,
            "by_id": {case["case_id"]: index for index, case in enumerate(cases)},
            "arrays": loaded["arrays"],
            "capture_sha256": loaded["capture_sha256"],
            "outcomes": {
                code: name for name, code in manifest["outcome_codes"].items()
            },
        }

    def _metadata(self, data, mode):
        manifest = data["manifest"]
        return {
            "schema_version": 1,
            "mode": mode,
            "study_id": manifest["study_id"],
            "capture_sha256": data["capture_sha256"],
            "grid_n": manifest["grid_n"],
            "domain_side_km": manifest["domain_side_km"],
            "timely_threshold_s": manifest["timely_threshold_s"],
            "outcome_codes": copy.deepcopy(manifest["outcome_codes"]),
            "source_sha256": copy.deepcopy(manifest["source_sha256"]),
            "grid": copy.deepcopy(manifest["grid"]),
            "limitations": copy.deepcopy(manifest["limitations"]),
        }

    def catalog(self):
        data = self._load()
        return {
            **self._metadata(data, "coverage_catalog"),
            "layouts": {str(count): layout_bases(count) for count in (9, 25)},
            "cases": copy.deepcopy(data["cases"]),
        }

    def case(self, case_id):
        data = self._load()
        if not isinstance(case_id, str) or case_id not in data["by_id"]:
            raise ValueError("Unknown coverage case")
        index = data["by_id"][case_id]
        scenario = data["cases"][index]
        offline = set(scenario["offline_bases"])
        bases = layout_bases(scenario["n_bases"])
        for base in bases:
            base["available"] = base["id"] not in offline
        grid_n = data["manifest"]["grid_n"]
        x_km = data["arrays"]["x_km"]
        y_km = data["arrays"]["y_km"]
        response = data["arrays"]["response_s"][index]
        selected = data["arrays"]["selected_base_id"][index]
        codes = data["arrays"]["outcome_code"][index]
        outcomes = data["outcomes"]
        cells = []
        for row in range(grid_n):
            for column in range(grid_n):
                value = float(response[row, column])
                base_id = int(selected[row, column])
                cells.append({
                    "index": row * grid_n + column,
                    "row": row,
                    "column": column,
                    "x_km": float(x_km[column]),
                    "y_km": float(y_km[row]),
                    "outcome": outcomes[int(codes[row, column])],
                    "response_s": value if math.isfinite(value) else None,
                    "selected_base_id": base_id if base_id >= 0 else None,
                })
        return {
            **self._metadata(data, "coverage"),
            "case": copy.deepcopy(scenario),
            "bases": bases,
            "cells": cells,
        }
