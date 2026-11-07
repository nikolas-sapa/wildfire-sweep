import unittest

import numpy as np

from detection import CandidateConfig, candidate_fraction, frame_metrics, predict_frames, validate_labels


class DetectionTests(unittest.TestCase):
    def test_black_and_red_only_are_not_fire_candidates(self):
        black = np.zeros((10, 10, 3), dtype=np.uint8)
        red = black.copy()
        red[:, :, 0] = 255
        self.assertEqual(candidate_fraction(black), 0)
        self.assertEqual(candidate_fraction(red), 0)

    def test_orange_patch_fraction_is_exact_not_probability(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        frame[:2, :5] = [220, 120, 20]
        self.assertEqual(candidate_fraction(frame), 0.1)

    def test_requires_three_consecutive_candidates_and_resets(self):
        candidate = np.full((2, 2, 3), [220, 120, 20], dtype=np.uint8)
        black = np.zeros_like(candidate)
        frames = [candidate, candidate, candidate, black, candidate]
        rows = list(predict_frames(((i, float(i), f) for i, f in enumerate(frames)), CandidateConfig()))
        self.assertEqual([r["alarm"] for r in rows], [False, False, True, False, False])

    def test_rejects_non_rgb_or_wrong_dtype(self):
        for frame in (np.zeros((2, 2)), np.zeros((2, 2, 3)), np.empty((0, 2, 3), dtype=np.uint8)):
            with self.assertRaises(ValueError):
                candidate_fraction(frame)

    def test_invalid_thresholds_fail(self):
        for kwargs in ({"min_fraction": float("nan")}, {"min_fraction": 0},
                       {"consecutive_frames": 0}, {"consecutive_frames": True}):
            with self.assertRaises(ValueError):
                CandidateConfig(**kwargs)

    def test_confusion_matrix_and_undefined_metrics(self):
        result = frame_metrics([1, 1, 0, 0], [True, False, True, False])
        self.assertEqual([result[k] for k in ("tp", "fn", "fp", "tn")], [1, 1, 1, 1])
        self.assertEqual(result["precision"], 0.5)
        self.assertEqual(result["recall"], 0.5)
        self.assertEqual(frame_metrics([0], [False])["precision"], None)
        self.assertEqual(frame_metrics([0], [False])["recall"], None)

    def test_mismatched_metric_arrays_fail(self):
        with self.assertRaises(ValueError):
            frame_metrics([1, 0], [True])

    def test_labels_require_complete_coverage_and_recording_split(self):
        rows = [{"recording_id": "r1", "sample_index": str(i), "fire": str(i % 2), "split": "test"}
                for i in range(3)]
        self.assertEqual(validate_labels(rows, "r1", 3), [0, 1, 0])
        with self.assertRaises(ValueError):
            validate_labels(rows[:2], "r1", 3)
        with self.assertRaises(ValueError):
            validate_labels(rows + [dict(rows[0], split="train", sample_index="4")], "r1", 3)
        with self.assertRaises(ValueError):
            validate_labels(rows + [rows[0]], "r1", 3)


if __name__ == "__main__":
    unittest.main()
