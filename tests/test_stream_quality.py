import unittest

from mosaic_lab.stream_quality import evaluate_stream_quality


class StreamQualityTests(unittest.TestCase):
    def test_margin_sweep_is_bounded_monotonic_and_non_executing(self):
        result = evaluate_stream_quality(size=400, seed=23, margins=(0.01, 0.04, 0.08))
        rows = result["margins"]
        abstention = [row["abstention_rate"] for row in rows]
        answered = [row["answered_rate"] for row in rows]
        self.assertEqual(abstention, sorted(abstention))
        self.assertEqual(answered, sorted(answered, reverse=True))
        self.assertTrue(result["learning_state_identical_across_margin_sweep"])
        self.assertEqual(result["external_actions"], 0)
        self.assertFalse(result["saved_weights"])
        self.assertFalse(result["production_qualified"])
        for row in rows:
            self.assertEqual(row["state_bounds"]["update_count"], 400)
            self.assertLessEqual(
                row["state_bounds"]["source_count"], row["state_bounds"]["source_limit"]
            )
            self.assertGreater(row["python_tracemalloc_peak_bytes"], 0)
            for key in ("false_positive_rate_answered", "false_negative_rate_answered"):
                value = row[key]
                self.assertTrue(value is None or 0.0 <= value <= 1.0)

    def test_rejects_ambiguous_margin_sets(self):
        for margins in ((), (0.1, 0.1), (0.2, 0.1), (-0.1,), (0.5,)):
            with self.subTest(margins=margins):
                with self.assertRaises(ValueError):
                    evaluate_stream_quality(size=400, margins=margins)


if __name__ == "__main__":
    unittest.main()
