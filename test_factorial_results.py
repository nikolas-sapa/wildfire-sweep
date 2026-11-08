import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parent
CAPTURE = ROOT / "research_results/2026-11-08-factorial"


def read_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FrozenFactorialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((CAPTURE / "manifest.json").read_text())
        cls.source = ROOT / cls.manifest["source_capture"]
        cls.summary = read_rows(CAPTURE / "summary.csv")
        cls.seasons = read_rows(CAPTURE / "seasons.csv")
        cls.effects = read_rows(CAPTURE / "effects.csv")
        cls.source_summary = {r["scenario"]: r for r in read_rows(cls.source / "summary.csv")}
        cls.source_seasons = {(r["scenario"], r["season"]): r
                             for r in read_rows(cls.source / "seasons.csv")}
        with np.load(CAPTURE / "new_responses.npz", allow_pickle=False) as archive:
            cls.new = {key: archive[key].copy() for key in archive.files}
        with np.load(cls.source / "responses.npz", allow_pickle=False) as archive:
            cls.old = {key: archive[key].copy() for key in archive.files}
        cls.offsets = cls.old["offsets"]
        cls.totals = np.diff(cls.offsets)
        cls.raw = {
            row["scenario"]: (cls.old[cls.manifest["reused_scenarios"][row["scenario"]]]
                              if row["provenance"] == "reused" else cls.new[row["scenario"]])
            for row in cls.summary
        }

    def test_hashes_and_provenance(self):
        self.assertEqual(self.manifest["status"], "complete")
        self.assertEqual(digest(self.source / "manifest.json"), self.manifest["source_manifest_sha256"])
        source_manifest = json.loads((self.source / "manifest.json").read_text())
        self.assertEqual(source_manifest["artifact_sha256"], self.manifest["source_artifact_sha256"])
        for name, value in self.manifest["source_artifact_sha256"].items():
            self.assertEqual(digest(self.source / name), value)
        for name, value in self.manifest["artifact_sha256"].items():
            self.assertEqual(digest(CAPTURE / name), value)
        for name, value in self.manifest["source_sha256"].items():
            self.assertEqual(digest(ROOT / name), value)
        self.assertEqual(json.loads((ROOT / "factorial_protocol.json").read_text()),
                         self.manifest["protocol"])

    def test_complete_design_inventory(self):
        self.assertEqual(len(self.summary), 32)
        self.assertEqual(len(self.seasons), 6400)
        self.assertEqual(len(self.effects), 28)
        self.assertEqual(self.manifest["seasons"], 200)
        self.assertEqual(self.manifest["real_alerts_per_scenario"], 61084)
        self.assertEqual(len(self.manifest["reused_scenarios"]), 20)
        self.assertEqual(len(self.manifest["simulated_scenarios"]), 12)
        self.assertEqual(set(self.new), {"offsets", *self.manifest["simulated_scenarios"]})
        self.assertEqual(len({r["scenario"] for r in self.summary}), 32)
        for bases, wind in itertools.product((9, 25), (8, 12)):
            rows = [r for r in self.summary if int(r["n_bases"]) == bases
                    and float(r["wind_east_mps"]) == wind]
            actual = {tuple(int(r[f"{name}_stress"]) for name in ("endurance", "launch", "reserve"))
                      for r in rows}
            self.assertEqual(actual, set(itertools.product((0, 1), repeat=3)))
        with np.load(self.source / "alerts.npz", allow_pickle=False) as alerts:
            actual_totals = [alerts["is_real"][a:b].sum()
                             for a, b in zip(alerts["offsets"][:-1], alerts["offsets"][1:])]
        np.testing.assert_array_equal(actual_totals, self.totals)
        np.testing.assert_array_equal(self.offsets, self.new["offsets"])

    def test_counts_against_every_raw_response(self):
        captured_seasons = {(r["scenario"], int(r["season"])): r for r in self.seasons}
        self.assertEqual(len(captured_seasons), 6400)
        for row in self.summary:
            values = self.raw[row["scenario"]]
            self.assertEqual(len(values), 61084)
            self.assertFalse(np.isnan(values).any())
            self.assertFalse((values < 0).any())
            timely = int(np.count_nonzero(values <= 900))
            rejected = int(np.count_nonzero(np.isinf(values)))
            late = len(values) - timely - rejected
            for name, count in (("real_alerts", len(values)), ("within_15min", timely),
                                ("rejected", rejected), ("served_late", late)):
                self.assertEqual(int(row[name]), count)
            self.assertAlmostEqual(float(row["within_15min_share"]), timely / len(values), places=14)
            for season, (a, b) in enumerate(zip(self.offsets[:-1], self.offsets[1:])):
                saved = captured_seasons[row["scenario"], season]
                response = values[a:b]
                within = int(np.count_nonzero(response <= 900))
                reject = int(np.count_nonzero(np.isinf(response)))
                self.assertEqual([int(saved[k]) for k in
                                  ("real_alerts", "within_15min", "rejected", "served_late")],
                                 [len(response), within, reject, len(response)-within-reject])
            p90 = np.sort(values)[math.ceil(0.9*len(values))-1]
            self.assertEqual(row["p90_unreachable"], str(bool(np.isinf(p90))))
            if np.isinf(p90):
                self.assertEqual(row["p90_s"], "")
            else:
                self.assertEqual(float(row["p90_s"]), p90)

    def test_reused_values_are_copied_not_reestimated(self):
        for row in self.summary:
            if row["provenance"] != "reused":
                continue
            old_id = self.manifest["reused_scenarios"][row["scenario"]]
            for key, value in self.source_summary[old_id].items():
                if key != "scenario":
                    self.assertEqual(row[key], value)
            for season in range(200):
                old = self.source_seasons[old_id, str(season)]
                new = next(r for r in self.seasons
                           if r["scenario"] == row["scenario"] and r["season"] == str(season))
                self.assertEqual({k: v for k, v in old.items() if k != "scenario"},
                                 {k: v for k, v in new.items() if k != "scenario"})

    def test_all_contrasts_against_independent_finite_differences(self):
        names = ("endurance", "launch", "reserve")
        draws = np.random.default_rng([1, self.manifest["seed"]]).integers(0, 200, (1000, 200))
        denominators = self.totals[draws].sum(axis=1)
        actual = {(int(r["n_bases"]), float(r["wind_east_mps"]), r["factors"]): r
                  for r in self.effects}
        self.assertEqual(len(actual), 28)
        for bases, wind in itertools.product((9, 25), (8, 12)):
            cube = np.empty((2, 2, 2, 200))
            for row in self.summary:
                if int(row["n_bases"]) != bases or float(row["wind_east_mps"]) != wind:
                    continue
                bits = tuple(int(row[f"{name}_stress"]) for name in names)
                values = self.raw[row["scenario"]]
                cube[bits] = [np.count_nonzero(values[a:b] <= 900)
                              for a, b in zip(self.offsets[:-1], self.offsets[1:])]
            for size in range(1, 4):
                for subset in itertools.combinations(range(3), size):
                    differences = cube.copy()
                    for axis in subset:
                        differences = np.diff(differences, axis=axis)
                    signed = differences.mean(axis=(0, 1, 2))
                    estimate = 100 * signed.sum() / self.totals.sum()
                    intervals = np.quantile(100*signed[draws].sum(axis=1)/denominators,
                                            [0.025, 0.975])
                    row = actual[bases, wind, "+".join(names[i] for i in subset)]
                    self.assertEqual(int(row["difference_order"]), size)
                    self.assertEqual(int(row["real_alerts"]), 61084)
                    np.testing.assert_allclose(
                        [float(row[k]) for k in
                         ("contrast_pp", "mc_95ci_low_pp", "mc_95ci_high_pp")],
                        [estimate, *intervals], rtol=0, atol=1e-12,
                    )

    def test_new_cell_marginal_intervals(self):
        draws = np.random.default_rng([1, self.manifest["seed"]]).integers(0, 200, (1000, 200))
        for row in self.summary:
            if row["provenance"] != "simulated":
                continue
            values = self.raw[row["scenario"]]
            timely = np.array([np.count_nonzero(values[a:b] <= 900)
                               for a, b in zip(self.offsets[:-1], self.offsets[1:])])
            expected = np.quantile(timely[draws].sum(axis=1)/self.totals[draws].sum(axis=1),
                                   [0.025, 0.975])
            np.testing.assert_allclose([float(row["mc_95ci_low"]), float(row["mc_95ci_high"])],
                                       expected, rtol=0, atol=1e-14)


if __name__ == "__main__":
    unittest.main()
