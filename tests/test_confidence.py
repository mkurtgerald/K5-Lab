from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.confidence import ConfidenceObservation, calibration_report, evidence_receipt


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


class ConfidenceTests(unittest.TestCase):
    def test_observation_rejects_bad_score_and_duplicate_provenance(self):
        with self.assertRaises(ValueError):
            obs(1, score=float("nan"))
        with self.assertRaises(ValueError):
            obs(1, provenance=("e1", "e1"))

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

    def test_insufficient_evidence_never_upgrades_probability_semantics(self):
        rows = tuple(obs(i, score=0.8, label=True) for i in range(20))
        report = calibration_report(rows, minimum_samples=20)
        self.assertFalse(report.evidence_sufficient)
        self.assertIsNone(report.balanced_accuracy)
        self.assertIsNone(report.false_positive_rate)
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
        first = obs(1, provenance=("e2", "e1"))
        second = obs(1, provenance=("e1", "e2"))
        a = evidence_receipt(first)
        b = evidence_receipt(second)
        self.assertEqual(a.receipt_id, b.receipt_id)
        self.assertEqual(a.provenance, ("e1", "e2"))
        self.assertEqual(a.score_semantics, "uncalibrated_score")
        self.assertFalse(a.authorized)
        self.assertEqual(a.external_actions, 0)

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

        receipt = evidence_receipt(obs(1, provenance=("e1",)))
        with self.assertRaises(ValueError):
            replace(receipt, receipt_id="ev_" + ("0" * 32))


if __name__ == "__main__":
    unittest.main()
