import unittest

from mosaic_lab.stream_multiseed import evaluate_multi_seed_quality


class StreamMultiSeedTests(unittest.TestCase):
    def test_multiseed_acceptance_is_bounded_and_non_executing(self):
        result = evaluate_multi_seed_quality(size=600, seeds=(19, 31, 43), margin=0.04)
        self.assertEqual(result["seeds"], [19, 31, 43])
        self.assertEqual(len(result["runs"]), 3)
        self.assertTrue(result["passed"])
        self.assertEqual(result["external_actions"], 0)
        self.assertFalse(result["saved_weights"])
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["score_calibration_established"])
        summary = result["summary"]
        criteria = result["criteria"]
        self.assertGreaterEqual(summary["min_answered_rate"], criteria["min_answered_rate"])
        self.assertLessEqual(
            summary["max_false_positive_rate_answered"],
            criteria["max_false_positive_rate_answered"],
        )
        self.assertLessEqual(
            summary["max_false_negative_rate_answered"],
            criteria["max_false_negative_rate_answered"],
        )
        self.assertLessEqual(
            summary["max_selective_mean_squared_score_error"],
            criteria["max_selective_mean_squared_score_error"],
        )

    def test_invalid_seed_and_margin_inputs_fail_closed(self):
        for seeds in ((), (1,), (1, 1), (1, True)):
            with self.subTest(seeds=seeds):
                with self.assertRaises(ValueError):
                    evaluate_multi_seed_quality(size=400, seeds=seeds)
        for margin in (-0.1, 0.5, True):
            with self.subTest(margin=margin):
                with self.assertRaises(ValueError):
                    evaluate_multi_seed_quality(size=400, seeds=(1, 2), margin=margin)


if __name__ == "__main__":
    unittest.main()
