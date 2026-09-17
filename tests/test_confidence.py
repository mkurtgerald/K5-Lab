from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.confidence import ConfidenceObservation, calibration_report, evidence_receipt
from mosaic_lab.memory import BoundedEventMemory, Event, MissingReference


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def obs(
    index: int,
    *,
    partition: str = "p1",
    model_id: str = "model_a",
    score: float = 0.8,
    label: bool = True,
    predicted: bool | None = None,
    abstained: bool = False,
    provenance: tuple[str, ...] = (),
) -> ConfidenceObservation:
    return ConfidenceObservation(
        partition=partition,
        sample_id=f"s{index}",
        source_id="src1",
        model_id=model_id,
        observed_at=BASE + timedelta(seconds=index),
        score=score,
        predicted=(score >= 0.5 if predicted is None else predicted),
        label=label,
        abstained=abstained,
        drift_detected=False,
        provenance=provenance,
    )


def memory_with_refs(*refs: str, partition: str = "p1") -> BoundedEventMemory:
    memory = BoundedEventMemory(max_events_per_partition=64)
    for index, ref in enumerate(refs):
        stamp = BASE + timedelta(seconds=index)
        memory.append(
            Event(
                partition=partition,
                event_id=ref,
                entity_key="entity_a",
                event_type="type_a",
                source_ref="source_a",
                event_at=stamp,
                observed_at=stamp,
                confidence=0.8,
            )
        )
    return memory


class ConfidenceTests(unittest.TestCase):
    def test_observation_rejects_bad_score_and_duplicate_provenance(self):
        with self.assertRaises(ValueError):
            obs(1, score=float("nan"))
        with self.assertRaises(ValueError):
            obs(1, provenance=("e1", "e1"))
        with self.assertRaises(ValueError):
            replace(obs(1), version="2")

    def test_report_keeps_raw_score_semantics_uncalibrated(self):
        rows = tuple(
            obs(i, score=0.9 if i % 2 else 0.1, label=bool(i % 2))
            for i in range(240)
        )
        report = calibration_report(rows, bins=8, minimum_samples=200)
        self.assertTrue(report.evidence_sufficient)
        self.assertEqual(report.sample_count, 240)
        self.assertEqual(report.coverage, 1.0)
        self.assertAlmostEqual(report.balanced_accuracy, 1.0)
        self.assertLess(report.raw_score_brier, 0.02)
        self.assertEqual(report.score_semantics, "uncalibrated_score")
        self.assertFalse(report.calibrated_probability_established)
        self.assertFalse(report.authorized)
        self.assertEqual(report.external_actions, 0)

    def test_insufficient_or_one_class_answered_evidence_stays_insufficient(self):
        all_positive = tuple(obs(i, score=0.8, label=True) for i in range(20))
        report = calibration_report(all_positive, minimum_samples=20)
        self.assertFalse(report.evidence_sufficient)
        self.assertIsNone(report.balanced_accuracy)
        self.assertIsNone(report.false_positive_rate)

        mostly_abstained = tuple(
            obs(
                i,
                score=0.9 if i % 2 else 0.1,
                label=bool(i % 2),
                abstained=i >= 10,
            )
            for i in range(240)
        )
        report = calibration_report(mostly_abstained, minimum_samples=200)
        self.assertFalse(report.evidence_sufficient)
        self.assertEqual(report.answered_count, 10)
        self.assertFalse(report.calibrated_probability_established)

    def test_all_abstained_window_is_valid_and_explicit(self):
        rows = tuple(
            obs(i, score=0.51, label=bool(i % 2), abstained=True)
            for i in range(20)
        )
        report = calibration_report(rows, minimum_samples=20)
        self.assertEqual(report.answered_count, 0)
        self.assertEqual(report.coverage, 0.0)
        self.assertEqual(report.abstention_rate, 1.0)
        self.assertIsNone(report.answered_brier)
        self.assertIsNone(report.balanced_accuracy)
        self.assertFalse(report.evidence_sufficient)

    def test_report_rejects_partition_model_and_sample_mixing(self):
        with self.assertRaises(ValueError):
            calibration_report((obs(1), obs(2, partition="p2")))
        with self.assertRaises(ValueError):
            calibration_report((obs(1), obs(2, model_id="model_b")))
        duplicate = obs(1)
        with self.assertRaises(ValueError):
            calibration_report((duplicate, duplicate))

    def test_evidence_receipt_is_canonical_deterministic_and_non_authorizing(self):
        memory = memory_with_refs("e1", "e2")
        first = obs(1, provenance=("e2", "e1"))
        second = obs(1, provenance=("e1", "e2"))
        a = evidence_receipt(first, memory=memory)
        b = evidence_receipt(second, memory=memory)
        self.assertEqual(a.receipt_id, b.receipt_id)
        self.assertEqual(a.provenance, ("e1", "e2"))
        self.assertEqual(a.score_semantics, "uncalibrated_score")
        self.assertFalse(a.authorized)
        self.assertEqual(a.external_actions, 0)

    def test_provenance_requires_resident_same_partition_events(self):
        observation = obs(1, provenance=("e1",))
        with self.assertRaises(MissingReference):
            evidence_receipt(observation)

        wrong_partition = memory_with_refs("e1", partition="p2")
        with self.assertRaises(MissingReference):
            evidence_receipt(observation, memory=wrong_partition)

        missing = BoundedEventMemory()
        with self.assertRaises(MissingReference):
            evidence_receipt(observation, memory=missing)

    def test_evidence_receipt_changes_when_decision_state_changes(self):
        a = evidence_receipt(obs(1, score=0.9, label=True, abstained=False))
        b = evidence_receipt(obs(1, score=0.9, label=True, abstained=True))
        self.assertNotEqual(a.receipt_id, b.receipt_id)

    def test_tampered_report_and_receipt_fail_closed(self):
        rows = tuple(
            obs(i, score=0.9 if i % 2 else 0.1, label=bool(i % 2))
            for i in range(240)
        )
        report = calibration_report(rows, bins=8, minimum_samples=200)
        with self.assertRaises(ValueError):
            replace(report, coverage=1.1)

        receipt = evidence_receipt(obs(1))
        with self.assertRaises(ValueError):
            replace(receipt, receipt_id="ev_" + ("0" * 32))


if __name__ == "__main__":
    unittest.main()
