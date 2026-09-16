import unittest

from mosaic_lab.stream_robustness import evaluate_stream_robustness
from mosaic_lab.streaming import RiverBinaryAdapter, StreamSample
from datetime import datetime, timezone


class StreamRobustnessTests(unittest.TestCase):
    def test_robustness_observation_is_bounded_and_non_executing(self):
        result = evaluate_stream_robustness(size=600, seed=31)
        self.assertEqual(result["external_actions"], 0)
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["performance_gate_established"])
        self.assertTrue(result["poisoning_stops_before_evaluation"])
        self.assertGreater(result["poisoned_training_samples"], 0)
        self.assertGreater(result["rare_clean"]["count"], 0)
        for group in ("clean", "poisoned_history"):
            for key, value in result[group].items():
                self.assertGreaterEqual(value, 0.0, key)
                self.assertLessEqual(value, 1.0, key)

    def test_invalid_robustness_parameters_fail_closed(self):
        for interval in (True, 0, 4, 101):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    evaluate_stream_robustness(size=400, poison_interval=interval)
        for threshold in (True, 0.89, 1.0, float("nan")):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    evaluate_stream_robustness(size=400, rare_abs_feature=threshold)

    def test_missing_and_nonfinite_features_are_rejected_without_update(self):
        adapter = RiverBinaryAdapter("p1", feature_count=2)
        base = dict(
            partition="p1",
            sample_id="x1",
            source_id="s1",
            observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            label=True,
        )
        short = StreamSample(**base, features=(0.1,))
        with self.assertRaises(ValueError):
            adapter.process(short)
        self.assertEqual(adapter.updates, 0)
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    StreamSample(**base, features=(0.1, value))
        self.assertEqual(adapter.updates, 0)


if __name__ == "__main__":
    unittest.main()
