import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from cohort_registry import COHORT_FIELDS, freeze_cohort, load_registry
from event_evaluation import LABEL_FIELDS
from video_io import FRAME_GEOMETRY


def write_csv(path, fields, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def packet_fixture(root, recording_id, split="test", video_hash=None):
    directory = root / f"packet-{recording_id}"
    directory.mkdir()
    video_hash = video_hash or hashlib.sha256(recording_id.encode()).hexdigest()
    rows = [{"recording_id": recording_id, "split": split, "input_sha256": video_hash,
             "sample_index": i, "sample_time_s": float(i), "fire": ""} for i in range(4)]
    write_csv(directory / "labels.csv", LABEL_FIELDS, rows)
    (directory / "sheet-0001.png").write_bytes(b"hash-only unit-test sheet")
    manifest = {
        "schema_version": 1, "status": "complete", "purpose": "blind annotation packet",
        "recording_id": recording_id, "split": split, "input_sha256": video_hash,
        "geometry": FRAME_GEOMETRY, "sample_fps": 1.0, "decoded_frames": 4,
        "max_frames": 600, "label_fields": list(LABEL_FIELDS),
        "source_sha256": {"video_io.py": digest(Path(__file__).with_name("video_io.py"))},
        "artifact_sha256": {name: digest(directory / name)
                           for name in ("labels.csv", "sheet-0001.png")},
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return directory


class CohortRegistryTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        self.csv = self.root / "cohort.csv"
        self.output = self.root / "registry"
        packet_fixture(self.root, "r1", "train")
        packet_fixture(self.root, "r2", "test")
        self.rows = [
            {"recording_id": "r1", "cluster_id": "g1", "site_id": "s1",
             "capture_date": "2026-01-01", "split": "train",
             "packet_dir": "packet-r1", "event_report_dir": ""},
            {"recording_id": "r2", "cluster_id": "g2", "site_id": "s2",
             "capture_date": "2026-02-01", "split": "test",
             "packet_dir": "packet-r2", "event_report_dir": "planned-events-r2"},
        ]
        self.save()

    def tearDown(self):
        self.workspace.cleanup()

    def save(self):
        write_csv(self.csv, COHORT_FIELDS, self.rows)

    def test_registry_freeze(self):
        before = self.csv.read_bytes()
        manifest = freeze_cohort(self.csv, self.output)
        self.assertEqual((self.output / "cohort.csv").read_bytes(), before)
        self.assertEqual(manifest["artifact_sha256"]["cohort.csv"], digest(self.csv))
        self.assertFalse((self.root / "planned-events-r2").exists())
        loaded, manifest_digest = load_registry(self.output)
        self.assertEqual(loaded, manifest)
        self.assertEqual(manifest_digest, digest(self.output / "manifest.json"))
        self.assertEqual((self.output / loaded["records"][1]["packet_dir"]).resolve(),
                         (self.root / "packet-r2").resolve())

    def test_registry_split_guards(self):
        for key in ("cluster_id", "site_id", "capture_date"):
            original = self.rows[1][key]
            self.rows[1][key] = self.rows[0][key]
            self.save()
            with self.assertRaisesRegex(ValueError, "Cross-split"):
                freeze_cohort(self.csv, self.output)
            self.assertFalse(self.output.exists())
            self.rows[1][key] = original

    def test_duplicate_recording_and_source_hashes_fail(self):
        self.rows.append(dict(self.rows[1]))
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate recording"):
            freeze_cohort(self.csv, self.output)
        self.rows.pop()
        packet_fixture(self.root, "r3", "test",
                       video_hash=hashlib.sha256(b"r2").hexdigest())
        self.rows.append({**self.rows[1], "recording_id": "r3", "packet_dir": "packet-r3"})
        self.save()
        with self.assertRaisesRegex(ValueError, "Duplicate source-video"):
            freeze_cohort(self.csv, self.output)
        self.assertFalse(self.output.exists())

    def test_packet_split_or_identity_disagreement_fails(self):
        self.rows[1]["packet_dir"] = "packet-r1"
        self.save()
        with self.assertRaisesRegex(ValueError, "Packet identity"):
            freeze_cohort(self.csv, self.output)

    def test_invalid_metadata_and_paths_fail(self):
        for key, value in (("capture_date", "2026-02-30"), ("capture_date", "20260201"),
                           ("site_id", "bad id"), ("split", "holdout"),
                           ("event_report_dir", ""), ("packet_dir", str(self.root / "packet-r2")),
                           ("event_report_dir", str(self.root / "events"))):
            original = self.rows[1][key]
            self.rows[1][key] = value
            self.save()
            with self.assertRaises(ValueError):
                freeze_cohort(self.csv, self.output)
            self.assertFalse(self.output.exists())
            self.rows[1][key] = original

    def test_train_report_path_and_missing_test_fail(self):
        self.rows[0]["event_report_dir"] = "not-allowed"
        self.save()
        with self.assertRaises(ValueError):
            freeze_cohort(self.csv, self.output)
        self.rows = [self.rows[0]]
        self.rows[0]["event_report_dir"] = ""
        self.save()
        with self.assertRaisesRegex(ValueError, "at least one"):
            freeze_cohort(self.csv, self.output)

    def test_blank_or_malformed_csv_fails(self):
        for content in ("", ",".join(COHORT_FIELDS) + "\n", "recording_id,split\nr1,test\n"):
            self.csv.write_text(content)
            with self.assertRaises(ValueError):
                freeze_cohort(self.csv, self.output)
            self.assertFalse(self.output.exists())

    def test_changed_csv_or_packet_fails(self):
        freeze_cohort(self.csv, self.output)
        with (self.output / "cohort.csv").open("a") as handle:
            handle.write("\n")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_registry(self.output)
        (self.output / "cohort.csv").write_bytes(self.csv.read_bytes())
        (self.root / "packet-r2/sheet-0001.png").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            load_registry(self.output)

    def test_output_is_exclusive(self):
        self.output.mkdir()
        sentinel = self.output / "sentinel"
        sentinel.write_bytes(b"unchanged")
        with self.assertRaises(FileExistsError):
            freeze_cohort(self.root / "missing.csv", self.output)
        self.assertEqual(list(self.output.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b"unchanged")

    def test_registry_source_provenance_is_required(self):
        freeze_cohort(self.csv, self.output)
        path = self.output / "manifest.json"
        original = path.read_text()
        for key, value in (("source_sha256", {}), ("cohort_protocol.json", "0"*64),
                           ("event_evaluation.py", "invalid-hash")):
            manifest = json.loads(original)
            if key == "source_sha256":
                manifest[key] = value
            else:
                manifest["source_sha256"][key] = value
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "provenance"):
                load_registry(self.output)


if __name__ == "__main__":
    unittest.main()
