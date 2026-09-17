import unittest

from mosaic_lab.confidence_benchmark import evaluate_confidence_quality


class ConfidenceBenchmarkTests(unittest.TestCase):
    def test_stationary_and_shifted_multiseed_diagnostics_remain_non_authorizing(self):
        result = evaluate_confidence_quality(size=400, seeds=(7,))
        self.assertTrue(result["passed"])
        self.assertEqual(result["scope"], "synthetic_confidence_diagnostics_only")
        self.assertEqual(
            {row["scenario"] for row in result["scenarios"]},
            {"stationary", "shifted"},
        )
        self.assertEqual(result["score_semantics"], "uncalibrated_score")
        self.assertFalse(result["calibrated_probability_established"])
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["authorized"])
        self.assertEqual(result["external_actions"], 0)
        for row in result["scenarios"]:
            self.assertTrue(row["passed"])
            self.assertFalse(row["report"]["calibrated_probability_established"])
            self.assertFalse(row["report"]["authorized"])

    def test_benchmark_input_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            evaluate_confidence_quality(size=399, seeds=(7,))
        with self.assertRaises(ValueError):
            evaluate_confidence_quality(size=400, seeds=(7, 7))
        with self.assertRaises(ValueError):
            evaluate_confidence_quality(size=400, seeds=())


if __name__ == "__main__":
    unittest.main()
