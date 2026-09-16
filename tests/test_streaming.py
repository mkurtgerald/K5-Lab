from datetime import datetime, timedelta, timezone
import math
import unittest

from mosaic_lab.streaming import (
    MAX_SOURCES,
    RiverBinaryAdapter,
    StreamOutcome,
    StreamSample,
    benchmark_stream,
)

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def sample(index=0, *, partition="p1", source="src1", features=(0.1, -0.2), label=True):
    return StreamSample(
        partition=partition,
        sample_id=f"s{index}",
        source_id=source,
        observed_at=BASE + timedelta(seconds=index + 1),
        features=features,
        label=label,
    )


class StreamContractTests(unittest.TestCase):
    def test_rejects_bad_features_and_versions(self):
        for features in ((), (True,), (math.nan,), (math.inf,), (1_000_001.0,)):
            with self.subTest(features=features):
                with self.assertRaises(ValueError):
                    sample(features=features)
        with self.assertRaises(ValueError):
            StreamSample("p1", "s1", "src1", BASE, (0.1,), True, version="2")
        with self.assertRaises(ValueError):
            sample(label=1)

    def test_outcome_cannot_claim_authority(self):
        with self.assertRaises(ValueError):
            StreamOutcome("p1", "s1", 0.5, True, False, False, 1, authorized=True)


class RiverAdapterTests(unittest.TestCase):
    def test_partition_feature_order_and_budget_are_fail_closed(self):
        adapter = RiverBinaryAdapter("p1", feature_count=2, max_updates=1)
        with self.assertRaises(ValueError):
            adapter.process(sample(partition="p2"))
        with self.assertRaises(ValueError):
            adapter.process(sample(features=(0.1,)))
        adapter.process(sample(0))
        with self.assertRaises(RuntimeError):
            adapter.process(sample(1))

    def test_unlabeled_samples_never_update(self):
        adapter = RiverBinaryAdapter("p1", feature_count=2)
        unlabeled = sample(label=None)
        predicted = adapter.predict(unlabeled)
        self.assertEqual(adapter.updates, 0)
        self.assertFalse(predicted.authorized)
        with self.assertRaises(ValueError):
            adapter.process(unlabeled)
        self.assertEqual(adapter.updates, 0)

    def test_out_of_order_observation_is_rejected_without_update(self):
        adapter = RiverBinaryAdapter("p1", feature_count=2)
        adapter.process(sample(2))
        before = adapter.updates
        with self.assertRaises(ValueError):
            adapter.process(sample(1))
        self.assertEqual(adapter.updates, before)

    def test_source_budget_is_bounded(self):
        adapter = RiverBinaryAdapter("p1", feature_count=2)
        for index in range(MAX_SOURCES):
            adapter.process(sample(index, source=f"src{index}"))
        self.assertEqual(adapter.source_count, MAX_SOURCES)
        with self.assertRaises(RuntimeError):
            adapter.process(sample(MAX_SOURCES, source="overflow"))

    def test_replay_is_deterministic_at_contract_level(self):
        left = RiverBinaryAdapter("p1", feature_count=2)
        right = RiverBinaryAdapter("p1", feature_count=2)
        left_scores = []
        right_scores = []
        for index in range(80):
            features = (index / 100.0, ((index % 9) - 4) / 10.0)
            label = (features[0] - features[1]) > 0.2
            left_scores.append(left.process(sample(index, features=features, label=label)).score)
            right_scores.append(right.process(sample(index, features=features, label=label)).score)
        self.assertEqual(left_scores, right_scores)
        self.assertEqual(left.state_receipt(), right.state_receipt())

    def test_benchmark_is_bounded_and_non_executing(self):
        result = benchmark_stream(size=600, seed=19)
        self.assertEqual(result["scope"], "synthetic_stream_demonstration_only")
        self.assertEqual(result["samples"], 600)
        self.assertEqual(result["updates"], 600)
        self.assertEqual(result["sources"], 1)
        self.assertEqual(result["external_actions"], 0)
        self.assertFalse(result["saved_weights"])
        self.assertFalse(result["production_qualified"])
        self.assertFalse(result["score_calibration_established"])
        self.assertEqual(result["versions"]["river"], "0.26.1")
        for family in ("streaming", "frozen_batch"):
            self.assertTrue(0.0 <= result[family]["balanced_accuracy"] <= 1.0)
            self.assertTrue(0.0 <= result[family]["mean_squared_score_error"] <= 1.0)
        self.assertGreaterEqual(result["update_latency_ms"]["p95"], 0.0)


if __name__ == "__main__":
    unittest.main()
