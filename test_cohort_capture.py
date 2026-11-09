import csv
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from cohort_evaluation import run_cohort
from cohort_registry import COHORT_FIELDS, freeze_cohort
from event_evaluation import LABEL_FIELDS, run_evaluation
from test_cohort_registry import digest, packet_fixture, write_csv


class CohortCaptureTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        self.csv, self.registry, self.output = (self.root / name for name in ("cohort.csv", "registry", "output"))
        self.rows = []
        for index in (1, 2):
            recording_id = f"r{index}"
            packet = packet_fixture(self.root, recording_id)
            self.rows.append({
                "recording_id": recording_id, "cluster_id": f"g{index}", "site_id": f"s{index}",
                "capture_date": "2026-01-01", "split": "test",
                "packet_dir": packet.name, "event_report_dir": f"event-{recording_id}",
            })
        write_csv(self.csv, COHORT_FIELDS, self.rows)
        freeze_cohort(self.csv, self.registry)
        for row in self.rows:
            recording_id = row["recording_id"]
            packet = self.root / row["packet_dir"]
            with (packet / "labels.csv").open(newline="") as handle:
                labels = list(csv.DictReader(handle))
            for index, label in enumerate(labels):
                label["fire"] = int(index in (1, 2))
            label_path = self.root / f"labels-{recording_id}.csv"
            write_csv(label_path, LABEL_FIELDS, labels)
            predictions = self.root / f"predictions-{recording_id}"
            predictions.mkdir()
            rows = [{"recording_id": recording_id, "sample_index": i, "sample_time_s": float(i),
                     "alarm": str(i == 2)} for i in range(4)]
            write_csv(predictions / "predictions.csv", list(rows[0]), rows)
            manifest = json.loads((packet / "manifest.json").read_text())
            manifest.update({
                "config": {"software_fixture": True},
                "artifact_sha256": {"predictions.csv": digest(predictions / "predictions.csv")},
            })
            (predictions / "manifest.json").write_text(json.dumps(manifest))
            run_evaluation(predictions, packet, label_path,
                           self.root / row["event_report_dir"], "unit-software-fixture")

    def tearDown(self):
        self.workspace.cleanup()

    def test_captured_cohort_and_exact_draws(self):
        result = run_cohort(self.registry, self.output, seed=17)
        self.assertEqual(result["aggregate"]["n_records"], 2)
        self.assertEqual(result["aggregate"]["n_clusters"], 2)
        self.assertEqual(result["aggregate"]["detected_fire_episodes"], 2)
        self.assertEqual(result["aggregate"]["detected_delays_s"], [1, 1])
        self.assertEqual(len(result["recordings"]), 2)
        with (self.output / "summary.csv").open(newline="") as handle:
            summary = list(csv.DictReader(handle))
        self.assertEqual(len(summary), 5)
        with np.load(self.output / "cluster_draws.npz", allow_pickle=False) as draws:
            self.assertEqual(draws["cluster_indices"].shape, (1000, 2))
            self.assertEqual(draws["cluster_ids"].tolist(), ["g1", "g2"])
            self.assertTrue(np.isin(draws["cluster_indices"], [0, 1]).all())
        manifest = json.loads((self.output / "manifest.json").read_text())
        for name, expected in manifest["artifact_sha256"].items():
            self.assertEqual(digest(self.output / name), expected)
        before = (self.output / "report.json").read_bytes()
        with self.assertRaises(FileExistsError):
            run_cohort(self.registry, self.output)
        self.assertEqual((self.output / "report.json").read_bytes(), before)

    def test_report_artifact_tampering_fails(self):
        with (self.root / "event-r2/report.json").open("a") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            run_cohort(self.registry, self.output)
        self.assertFalse(self.output.exists())

    def test_report_packet_binding_fails(self):
        path = self.root / "event-r2/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["input_manifest_sha256"]["annotation"] = "a"*64
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "registered annotation"):
            run_cohort(self.registry, self.output)
        self.assertFalse(self.output.exists())

    def test_incompatible_configs_sources_and_rates_fail(self):
        path = self.root / "event-r2/manifest.json"
        original = path.read_bytes()
        for key, value in (("prediction_config", {"different": True}), ("sample_fps", 2),
                           ("decoded_frames", 3), ("protocol", {"schema_version": 99})):
            manifest = json.loads(original)
            manifest[key] = value
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                run_cohort(self.registry, self.output)
            self.assertFalse(self.output.exists())
        manifest = json.loads(original)
        manifest["source_sha256"]["detection.py"] = "0"*64
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "incompatible"):
            run_cohort(self.registry, self.output)

    def test_missing_planned_report_fails_without_output(self):
        self.rows[0]["event_report_dir"] = "not-yet-created"
        write_csv(self.csv, COHORT_FIELDS, self.rows)
        registry = self.root / "registry-with-planned-missing-report"
        freeze_cohort(self.csv, registry)
        with self.assertRaises(FileNotFoundError):
            run_cohort(registry, self.output)
        self.assertFalse(self.output.exists())

    def test_bad_numeric_closure_rejected_with_updated_hash(self):
        path = self.root / "event-r2/report.json"
        report = json.loads(path.read_text())
        report["metrics"]["fire_episodes"] += 1
        path.write_text(json.dumps(report))
        manifest_path = path.with_name("manifest.json")
        manifest = json.loads(manifest_path.read_text())
        manifest["artifact_sha256"]["report.json"] = digest(path)
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "counts do not close"):
            run_cohort(self.registry, self.output)
        self.assertFalse(self.output.exists())

    def test_frozen_registry_change_is_rejected(self):
        with (self.registry / "cohort.csv").open("a") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            run_cohort(self.registry, self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
