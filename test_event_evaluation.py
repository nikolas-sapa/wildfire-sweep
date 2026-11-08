import csv
import hashlib
import itertools
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import event_evaluation
from event_evaluation import episode_metrics, run_evaluation
from video_io import FRAME_GEOMETRY


class EpisodeMetricTests(unittest.TestCase):
    def test_two_perfect_episodes(self):
        result = episode_metrics([0, 1, 1, 0, 1, 1, 0], [0, 1, 1, 0, 1, 1, 0], 2)
        self.assertEqual(result["detected_fire_episodes"], 2)
        self.assertEqual(result["event_recall"], 1)
        self.assertEqual(result["alarm_precision"], 1)
        self.assertEqual(result["sampled_exposure_s"], 3.5)
        self.assertEqual(result["detected_delay_p90_s"], 0)

    def test_quantized_delays_and_nearest_rank(self):
        result = episode_metrics([0, 1, 1, 1, 0, 1, 1, 1, 1, 0],
                                 [0, 0, 1, 1, 0, 0, 0, 1, 1, 0], 2)
        self.assertEqual([r["delay_s"] for r in result["fire_episode_details"]], [0.5, 1.0])
        self.assertEqual(result["detected_delay_p50_s"], 0.5)
        self.assertEqual(result["detected_delay_p90_s"], 1)

    def test_preexisting_alarm_does_not_detect_later_fire(self):
        result = episode_metrics([0, 0, 1, 1, 0], [1, 1, 1, 1, 1], 1)
        self.assertEqual(result["detected_fire_episodes"], 0)
        self.assertEqual(result["missed_fire_episodes"], 1)
        self.assertEqual(result["false_alarm_episodes"], 1)
        self.assertEqual(result["nonfire_exposure_s"], 3)
        self.assertEqual(result["false_alarms_per_nonfire_hour"], 1200)
        self.assertEqual(result["event_recall"], 0)
        self.assertEqual(result["alarm_precision"], 0)

    def test_duplicates_are_not_negative_exposure_false_alarms(self):
        result = episode_metrics([0, 1, 1, 1, 1, 1, 0], [0, 1, 0, 1, 0, 1, 0], 1)
        self.assertEqual(result["detected_fire_episodes"], 1)
        self.assertEqual(result["duplicate_alarm_episodes"], 2)
        self.assertEqual(result["false_alarm_episodes"], 0)
        self.assertEqual(result["unmatched_alarm_episodes"], 2)
        self.assertEqual(result["event_recall"], 1)
        self.assertEqual(result["alarm_precision"], 1/3)
        self.assertEqual(result["false_alarms_per_nonfire_hour"], 0)

    def test_no_fire_has_undefined_recall(self):
        result = episode_metrics([0]*5, [0, 1, 1, 0, 1], 1)
        self.assertEqual(result["false_alarm_episodes"], 2)
        self.assertIsNone(result["event_recall"])
        self.assertEqual(result["alarm_precision"], 0)
        self.assertEqual(result["false_alarms_per_nonfire_hour"], 1440)

    def test_no_alarm_and_no_negative_exposure(self):
        result = episode_metrics([1]*3, [0]*3, 1)
        self.assertEqual(result["event_recall"], 0)
        for key in ("alarm_precision", "false_alarms_per_nonfire_hour",
                    "detected_delay_p50_s", "detected_delay_p90_s"):
            self.assertIsNone(result[key])
        self.assertEqual(result["left_censored_fire_episodes"], 1)
        self.assertEqual(result["right_censored_fire_episodes"], 1)
        self.assertTrue(result["fire_episode_details"][0]["left_censored"])
        self.assertTrue(result["fire_episode_details"][0]["right_censored"])

    def test_half_open_end_excludes_post_fire_alarm(self):
        result = episode_metrics([0, 1, 1, 0], [0, 0, 0, 1], 1)
        self.assertEqual(result["missed_fire_episodes"], 1)
        self.assertEqual(result["false_alarm_episodes"], 1)

    def test_misses_do_not_become_zero_delays(self):
        result = episode_metrics([1, 0, 1, 1, 1, 0, 1], [0, 0, 0, 1, 1, 0, 0], 1)
        self.assertEqual(result["event_recall"], 1/3)
        self.assertEqual(result["missed_fire_episodes"], 2)
        self.assertEqual(result["detected_delay_p50_s"], 1)
        self.assertEqual(result["detected_delay_p90_s"], 1)

    def test_invalid_sequences_and_rates_fail(self):
        for truth, alarms in [([], []), ([1], []), ([2], [0]), ([0], [float("nan")]),
                              (["1"], [0]), ([0], [3])]:
            with self.assertRaises(ValueError):
                episode_metrics(truth, alarms, 1)
        for fps in (True, 0, -1, float("nan"), float("inf"), 31, 1e-320):
            with self.assertRaises(ValueError):
                episode_metrics([0, 1], [0, 1], fps)

    def test_exhaustive_count_closure(self):
        sequences = list(itertools.product((0, 1), repeat=5))
        for truth, alarms in itertools.product(sequences, repeat=2):
            result = episode_metrics(truth, alarms, 2)
            self.assertEqual(result["fire_episodes"],
                             result["detected_fire_episodes"] + result["missed_fire_episodes"])
            self.assertEqual(result["alarm_episodes"], result["detected_fire_episodes"]
                             + result["duplicate_alarm_episodes"] + result["false_alarm_episodes"])
            self.assertLessEqual(result["detected_fire_episodes"],
                                 min(result["fire_episodes"], result["alarm_episodes"]))


def write_csv(path, fields, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EventCaptureTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        self.packet, self.predictions = self.root / "packet", self.root / "predictions"
        self.packet.mkdir()
        self.predictions.mkdir()
        self.labels = self.root / "completed.csv"
        self.fields = ["recording_id", "split", "input_sha256", "sample_index", "sample_time_s", "fire"]
        self.rows = [{"recording_id": "r1", "split": "test", "input_sha256": "a"*64,
                      "sample_index": i, "sample_time_s": i/2, "fire": value}
                     for i, value in enumerate([0, 1, 1, 0])]
        template = [{**row, "fire": ""} for row in self.rows]
        write_csv(self.packet / "labels.csv", self.fields, template)
        (self.packet / "sheet-0001.png").write_bytes(b"hash-only unit-test sheet fixture")
        predictions = [{"recording_id": "r1", "sample_index": i, "sample_time_s": i/2,
                        "alarm": str(bool(value))} for i, value in enumerate([0, 0, 1, 0])]
        write_csv(self.predictions / "predictions.csv", list(predictions[0]), predictions)
        write_csv(self.labels, self.fields, self.rows)
        common = {"schema_version": 1, "status": "complete", "recording_id": "r1",
                  "input_sha256": "a"*64, "sample_fps": 2.0, "decoded_frames": 4,
                  "geometry": FRAME_GEOMETRY, "max_frames": 600,
                  "source_sha256": {"video_io.py": "c"*64}}
        self.packet_manifest = {**common, "purpose": "blind annotation packet", "split": "test",
                                "label_fields": self.fields,
                                "artifact_sha256": {name: sha256(self.packet / name)
                                                   for name in ("labels.csv", "sheet-0001.png")}}
        self.prediction_manifest = {**common, "config": {"test_fixture": True},
                                    "artifact_sha256": {
                                        "predictions.csv": sha256(self.predictions / "predictions.csv")}}
        self.save_manifests()

    def tearDown(self):
        self.workspace.cleanup()

    def save_manifests(self):
        for directory, manifest in ((self.packet, self.packet_manifest),
                                     (self.predictions, self.prediction_manifest)):
            (directory / "manifest.json").write_text(json.dumps(manifest))

    def evaluate(self, name="output"):
        return run_evaluation(self.predictions, self.packet, self.labels, self.root / name, "reviewer-01")

    def test_capture_binding_and_exclusive_outputs(self):
        result = self.evaluate()
        self.assertEqual(result["metrics"]["detected_fire_episodes"], 1)
        self.assertEqual(result["metrics"]["detected_delay_p90_s"], 0.5)
        manifest = json.loads((self.root / "output/manifest.json").read_text())
        self.assertEqual(manifest["artifact_sha256"]["report.json"], sha256(self.root / "output/report.json"))
        self.assertEqual(manifest["annotator_id"], "reviewer-01")
        before = (self.root / "output/report.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.evaluate()
        self.assertEqual((self.root / "output/report.json").read_bytes(), before)

    def test_reordered_labels_are_valid(self):
        write_csv(self.labels, self.fields, list(reversed(self.rows)))
        self.assertEqual(self.evaluate()["metrics"]["detected_fire_episodes"], 1)

    def test_provenance_hashes_the_parsed_label_snapshot(self):
        original_digest = sha256(self.labels)
        original_reader = event_evaluation._csv_rows

        def read_then_change(path, *args, **kwargs):
            result = original_reader(path, *args, **kwargs)
            if path == self.labels:
                write_csv(self.labels, self.fields, [{**row, "fire": 0} for row in self.rows])
            return result

        with patch("event_evaluation._csv_rows", side_effect=read_then_change):
            result = self.evaluate()
        manifest = json.loads((self.root / "output/manifest.json").read_text())
        self.assertEqual(result["metrics"]["detected_fire_episodes"], 1)
        self.assertEqual(manifest["input_artifact_sha256"]["completed_labels.csv"], original_digest)
        self.assertNotEqual(original_digest, sha256(self.labels))

    def test_blank_duplicate_missing_or_modified_labels_fail(self):
        cases = [self.rows[:-1], self.rows + [self.rows[0]],
                 [{**r, "fire": ""} for r in self.rows],
                 [{**r, "sample_time_s": 20} for r in self.rows],
                 [{**r, "input_sha256": "b"*64} for r in self.rows]]
        for i, rows in enumerate(cases):
            write_csv(self.labels, self.fields, rows)
            with self.assertRaises(ValueError):
                self.evaluate(f"bad-{i}")
            self.assertFalse((self.root / f"bad-{i}").exists())

    def test_input_hash_tampering_fails_before_output(self):
        with (self.predictions / "predictions.csv").open("a") as handle:
            handle.write("\n")
        with self.assertRaises(ValueError):
            self.evaluate()
        self.assertFalse((self.root / "output").exists())

    def test_packet_sheet_tampering_fails_before_output(self):
        (self.packet / "sheet-0001.png").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.evaluate()
        self.assertFalse((self.root / "output").exists())

    def test_decoder_fingerprint_must_match(self):
        for fingerprints in ({"video_io.py": "b"*64}, None, {}, {"video_io.py": "bad"}):
            self.packet_manifest["source_sha256"] = fingerprints
            self.save_manifests()
            with self.assertRaisesRegex(ValueError, "same captured decoder"):
                self.evaluate()
            self.assertFalse((self.root / "output").exists())

    def test_mismatched_manifest_metadata_and_non_test_split_fail(self):
        for i, (key, value) in enumerate((("input_sha256", "b"*64), ("sample_fps", 1),
                                          ("decoded_frames", 3), ("recording_id", "other"),
                                          ("geometry", "other"), ("split", "train"))):
            original = dict(self.packet_manifest)
            self.packet_manifest[key] = value
            self.save_manifests()
            with self.assertRaises(ValueError):
                self.evaluate(f"mismatch-{i}")
            self.assertFalse((self.root / f"mismatch-{i}").exists())
            self.packet_manifest = original

    def test_invalid_alarm_or_time_is_rejected_even_with_updated_hash(self):
        for i, (key, value) in enumerate((("alarm", "1"), ("sample_time_s", 4),
                                         ("sample_index", 9), ("recording_id", "other"))):
            path = self.predictions / "predictions.csv"
            with path.open(newline="") as handle:
                rows = list(csv.DictReader(handle))
            original = [dict(row) for row in rows]
            rows[0][key] = value
            write_csv(path, list(rows[0]), rows)
            self.prediction_manifest["artifact_sha256"]["predictions.csv"] = sha256(path)
            self.save_manifests()
            with self.assertRaises(ValueError):
                self.evaluate(f"invalid-prediction-{i}")
            self.assertFalse((self.root / f"invalid-prediction-{i}").exists())
            write_csv(path, list(original[0]), original)


if __name__ == "__main__":
    unittest.main()
