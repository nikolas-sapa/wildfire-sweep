import csv
import itertools
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from factorial import factorial_grid, factorial_interval, run_factorial, sha256
from research import dispatch_physical
from robustness import run_robustness


ROOT = Path(__file__).resolve().parent
PROTOCOL = json.loads((ROOT / "factorial_protocol.json").read_text())


def cube(function, seasons=2):
    result = np.empty((2, 2, 2, seasons), dtype=int)
    for bits in itertools.product((0, 1), repeat=3):
        result[bits] = function(*bits)
    return result


class FactorialIntervalTests(unittest.TestCase):
    def estimate(self, values, factors, totals=None):
        if totals is None:
            totals = np.full(values.shape[-1], 100)
        return factorial_interval(values, totals, factors, seed=17, replicates=100)

    def test_additive_cube_has_zero_interactions(self):
        values = cube(lambda e, l, r: 80 - 10*e - 20*l - 5*r)
        for factors, expected in [((0,), -10), ((1,), -20), ((2,), -5),
                                  ((0, 1), 0), ((0, 2), 0), ((1, 2), 0),
                                  ((0, 1, 2), 0)]:
            with self.subTest(factors=factors):
                for actual in self.estimate(values, factors):
                    self.assertAlmostEqual(actual, expected, places=12)

    def test_pair_interaction_is_full_difference_in_differences(self):
        values = cube(lambda e, l, r: 80 - 10*e - 20*l - 5*r - 8*e*l)
        for factors, expected in [((0,), -14), ((1,), -24), ((2,), -5),
                                  ((0, 1), -8), ((0, 2), 0), ((1, 2), 0),
                                  ((0, 1, 2), 0)]:
            self.assertAlmostEqual(self.estimate(values, factors)[0], expected, places=12)

    def test_triple_term_scales_correctly(self):
        values = cube(lambda e, l, r: 50 + 4*e*l*r)
        for size, expected in [(1, 1), (2, 2), (3, 4)]:
            for factors in itertools.combinations(range(3), size):
                self.assertAlmostEqual(self.estimate(values, factors)[0], expected, places=12)

    def test_event_weighting_not_mean_season_share(self):
        values = np.zeros((2, 2, 2, 2), dtype=int)
        values[1, :, :, 0] = 1
        self.assertAlmostEqual(self.estimate(values, (0,), [1, 100])[0], 100/101, places=12)

    def test_bootstrap_matches_manual_paired_draws(self):
        values = np.arange(24).reshape(2, 2, 2, 3)
        totals = np.array([30, 50, 80])
        factors = (0, 2)
        actual = self.estimate(values, factors, totals)
        draws = np.random.default_rng(17).integers(0, 3, (100, 3))
        signed = []
        for season in range(3):
            numerator = 0.0
            for e, l, r in itertools.product((0, 1), repeat=3):
                numerator += (1 if e == r else -1) * values[e, l, r, season] / 2
            signed.append(numerator)
        expected_draws = [
            100 * sum(signed[i] for i in draw) / sum(totals[i] for i in draw)
            for draw in draws
        ]
        expected = (100*sum(signed)/sum(totals),
                    *np.quantile(expected_draws, [0.025, 0.975]))
        np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-12)

    def test_invalid_inputs_fail(self):
        valid = cube(lambda e, l, r: 10)
        for values, totals in [(valid[0], [100, 100]), (valid, [100]),
                               (valid + 0.5, [100, 100]), (-valid, [100, 100]),
                               (valid * np.nan, [100, 100]), (valid, [9, 100]),
                               (valid, [100.5, 100]), (valid, [np.inf, 100])]:
            with self.subTest(shape=values.shape, totals=totals):
                with self.assertRaises(ValueError):
                    self.estimate(values, (0,), totals)
        for factors in [(), (0, 0), (-1,), (3,), (True,), ("0",)]:
            with self.assertRaises(ValueError):
                self.estimate(valid, factors)
        for replicates in [0, -1, True, 1.5]:
            with self.assertRaises(ValueError):
                factorial_interval(valid, [100, 100], (0,), 17, replicates)

    def test_empty_counts_are_missing(self):
        self.assertEqual(self.estimate(np.zeros((2, 2, 2, 2)), (0,), [0, 0]),
                         (None, None, None))
        self.assertEqual(self.estimate(cube(lambda e, l, r: 80 - 10*e, 1), (0,)),
                         (-10.0, None, None))

    def test_grid_and_reuse(self):
        scenarios = factorial_grid(PROTOCOL)
        self.assertEqual(len(scenarios), 32)
        self.assertEqual(len({row["scenario"] for row in scenarios}), 32)
        self.assertEqual(sum(row["provenance"] == "reused" for row in scenarios), 20)
        for base, wind in itertools.product((9, 25), (8, 12)):
            subset = [row for row in scenarios
                      if row["n_bases"] == base and row["wind_east_mps"] == wind]
            self.assertEqual({tuple(row[f"{name}_stress"] for name in PROTOCOL["factor_order"])
                              for row in subset}, set(itertools.product((0, 1), repeat=3)))


class FactorialCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory()
        cls.root = Path(cls.workspace.name)
        cls.source = cls.root / "source"
        run_robustness(cls.source, seasons=2, seed=7)
        cls.before = {p.name: sha256(p) for p in cls.source.iterdir()}
        cls.output = cls.root / "extension"
        with patch("factorial.dispatch_physical", wraps=dispatch_physical) as dispatcher:
            run_factorial(cls.output, cls.source)
            cls.dispatch_count = dispatcher.call_count

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def rows(self, directory, filename):
        with (directory / filename).open(newline="") as handle:
            return list(csv.DictReader(handle))

    def test_only_missing_cells_are_dispatched(self):
        self.assertEqual(self.dispatch_count, 24)
        self.assertEqual(self.before, {p.name: sha256(p) for p in self.source.iterdir()})

    def test_reused_results_are_copied(self):
        old_summary = {r["scenario"]: r for r in self.rows(self.source, "summary.csv")}
        old_seasons = {(r["scenario"], r["season"]): r
                       for r in self.rows(self.source, "seasons.csv")}
        new_seasons = {(r["scenario"], r["season"]): r
                       for r in self.rows(self.output, "seasons.csv")}
        for row in self.rows(self.output, "summary.csv"):
            if row["provenance"] != "reused":
                continue
            old_id = f"b{row['n_bases']}-w{float(row['wind_east_mps']):g}-{row['condition']}"
            for field in ("within_15min", "real_alerts", "mc_95ci_low", "mc_95ci_high",
                          "p90_s", "p90_unreachable", "within_15min_share"):
                self.assertEqual(row[field], old_summary[old_id][field])
            for season in range(2):
                old = old_seasons[old_id, str(season)]
                new = new_seasons[row["scenario"], str(season)]
                self.assertEqual({k: v for k, v in old.items() if k != "scenario"},
                                 {k: v for k, v in new.items() if k != "scenario"})

    def test_repeat_and_overwrite(self):
        other = self.root / "repeat"
        run_factorial(other, self.source)
        for name in ("summary.csv", "effects.csv", "seasons.csv"):
            self.assertEqual((other / name).read_bytes(), (self.output / name).read_bytes())
        with np.load(other / "new_responses.npz") as a, np.load(self.output / "new_responses.npz") as b:
            self.assertEqual(set(a.files), set(b.files))
            for key in a.files:
                np.testing.assert_array_equal(a[key], b[key])
        with self.assertRaises(FileExistsError):
            run_factorial(self.output, self.source)

    def test_source_tamper_fails_before_output(self):
        for kind in ("hash", "configuration", "incomplete"):
            source = self.root / f"bad-{kind}"
            shutil.copytree(self.source, source)
            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            if kind == "hash":
                with (source / "summary.csv").open("a") as handle:
                    handle.write("\n")
            elif kind == "configuration":
                manifest["legacy_config"]["domain_km2"] += 1
            else:
                lines = (source / "summary.csv").read_text().splitlines(keepends=True)
                (source / "summary.csv").write_text("".join(lines[:-1]))
                manifest["artifact_sha256"]["summary.csv"] = sha256(source / "summary.csv")
            manifest_path.write_text(json.dumps(manifest))
            output = self.root / f"rejected-{kind}"
            with self.assertRaises(ValueError):
                run_factorial(output, source)
            self.assertFalse(output.exists())

    def test_capture_integrity(self):
        manifest = json.loads((self.output / "manifest.json").read_text())
        for name, digest in manifest["artifact_sha256"].items():
            self.assertEqual(sha256(self.output / name), digest)
        summary = self.rows(self.output, "summary.csv")
        self.assertEqual(len(summary), 32)
        self.assertEqual(len(self.rows(self.output, "effects.csv")), 28)
        self.assertEqual(len(self.rows(self.output, "seasons.csv")), 64)
        with np.load(self.output / "new_responses.npz") as capture:
            self.assertEqual(len(capture.files), 13)
            for row in summary:
                self.assertEqual(int(row["real_alerts"]),
                                 sum(int(row[k]) for k in ("within_15min", "rejected", "served_late")))
                if row["provenance"] == "simulated":
                    values = capture[row["scenario"]]
                    self.assertEqual(len(values), int(row["real_alerts"]))
                    self.assertEqual(np.count_nonzero(values <= 900), int(row["within_15min"]))
                    self.assertEqual(np.count_nonzero(np.isinf(values)), int(row["rejected"]))


if __name__ == "__main__":
    unittest.main()
