from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.confidence import ConfidenceObservation, calibration_report, evidence_receipt
from mosaic_lab.memory import BoundedEventMemory, Event


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(event_id: str, offset: int) -> Event:
    stamp = BASE + timedelta(seconds=offset)
    return Event(
        partition="p1",
        event_id=event_id,
        entity_key="entity_a",
        event_type="type_a",
        source_ref="source_a",
        event_at=stamp,
        observed_at=stamp,
        confidence=0.9,
    )


def _observation(index: int) -> ConfidenceObservation:
    label = bool(index % 2)
    score = 0.9 if label else 0.1
    return ConfidenceObservation(
        partition="p1",
        sample_id=f"s{index}",
        source_id="src1",
        model_id="model_a",
        observed_at=BASE + timedelta(seconds=index),
        score=score,
        predicted=label,
        label=label,
        abstained=False,
        drift_detected=False,
    )


class ReceiptIntegrityTests(unittest.TestCase):
    def test_correlation_receipt_direct_tampering_fails_closed(self):
        memory = BoundedEventMemory(max_query_window_seconds=30)
        memory.append(_event("e1", 1))
        memory.append(_event("e2", 2))
        receipt = memory.correlate(
            partition="p1", event_ids=("e1", "e2"), window_seconds=10
        )
        self.assertFalse(receipt.authorized)
        self.assertEqual(receipt.external_actions, 0)
        for changes in (
            {"correlation_id": "corr_" + ("0" * 32)},
            {"partition": "p2"},
            {"entity_key": "entity_b"},
            {"event_ids": ("e2", "e1")},
            {"event_ids": ("e1", "e1")},
            {"version": "2"},
            {"authorized": True},
            {"external_actions": 1},
            {"ended_at": receipt.started_at - timedelta(seconds=1)},
            {"started_at": datetime(2026, 1, 1)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(receipt, **changes)

    def test_confidence_report_direct_tampering_fails_closed(self):
        rows = tuple(_observation(index) for index in range(240))
        report = calibration_report(rows, bins=8, minimum_samples=200)
        for changes in (
            {"authorized": True},
            {"external_actions": 1},
            {"version": "2"},
            {"score_semantics": "probability"},
            {"calibrated_probability_established": True},
            {"coverage": 0.9},
            {"answered_count": report.sample_count + 1},
            {"bins": 1},
            {"evidence_sufficient": 1},
            {"answered_brier": None},
            {"balanced_accuracy": 1.1},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(report, **changes)

    def test_evidence_receipt_direct_tampering_fails_closed(self):
        receipt = evidence_receipt(_observation(1))
        for changes in (
            {"receipt_id": "ev_" + ("0" * 32)},
            {"authorized": True},
            {"external_actions": 1},
            {"version": "2"},
            {"score_semantics": "probability"},
            {"predicted": 1},
            {"provenance": ("bad id",)},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(receipt, **changes)


if __name__ == "__main__":
    unittest.main()
