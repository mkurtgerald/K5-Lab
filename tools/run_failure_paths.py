from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.confidence import ConfidenceObservation, evidence_receipt
from mosaic_lab.memory import BoundedEventMemory, Event, MissingReference
from mosaic_lab.policy_adapter import evaluate_policy_proposal

BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(event_id: str, second: int, *, partition: str = "p1") -> Event:
    stamp = BASE + timedelta(seconds=second)
    return Event(
        partition=partition,
        event_id=event_id,
        entity_key="entity_a",
        event_type="type_a",
        source_ref="source_a",
        event_at=stamp,
        observed_at=stamp,
        confidence=0.9,
    )


def _observation(
    sample_id: str,
    *,
    score: float,
    predicted: bool,
    provenance: tuple[str, ...] = (),
) -> ConfidenceObservation:
    return ConfidenceObservation(
        partition="p1",
        sample_id=sample_id,
        source_id="source_a",
        model_id="model_a",
        observed_at=BASE + timedelta(seconds=20),
        score=score,
        predicted=predicted,
        label=predicted,
        abstained=False,
        drift_detected=False,
        provenance=provenance,
    )


def _raises(exc_type: type[BaseException], callback) -> bool:
    try:
        callback()
    except exc_type:
        return True
    return False


def run() -> dict[str, object]:
    eviction_memory = BoundedEventMemory(
        max_events_per_partition=3,
        max_partitions=1,
        max_age_seconds=1000,
        max_query_window_seconds=60,
    )
    for index in range(1, 4):
        eviction_memory.append(_event(f"e{index}", index))

    correlation_before = eviction_memory.correlate(
        partition="p1", event_ids=("e1", "e2"), window_seconds=10
    )
    evidence_before = evidence_receipt(
        _observation(
            "sample_before",
            score=0.9,
            predicted=True,
            provenance=("e1", "e2"),
        ),
        memory=eviction_memory,
    )
    eviction_memory.append(_event("e4", 4))

    correlation_fails_closed = _raises(
        MissingReference,
        lambda: eviction_memory.correlate(
            partition="p1", event_ids=("e1", "e2"), window_seconds=10
        ),
    )
    evidence_fails_closed = _raises(
        MissingReference,
        lambda: evidence_receipt(
            _observation(
                "sample_after",
                score=0.9,
                predicted=True,
                provenance=("e1", "e2"),
            ),
            memory=eviction_memory,
        ),
    )
    provenance_eviction = {
        "resident_bound_preserved": eviction_memory.resident_count("p1") == 3,
        "correlation_fails_closed": correlation_fails_closed,
        "evidence_fails_closed": evidence_fails_closed,
        "prior_receipts_non_authorizing": (
            correlation_before.authorized is False
            and correlation_before.external_actions == 0
            and evidence_before.authorized is False
            and evidence_before.external_actions == 0
        ),
    }

    fan_in_memory = BoundedEventMemory(
        max_events_per_partition=64,
        max_partitions=1,
        max_age_seconds=1000,
        max_query_window_seconds=60,
    )
    fan_in_ids = tuple(f"fan_{index:02d}" for index in range(33))
    for index, event_id in enumerate(fan_in_ids):
        fan_in_memory.append(_event(event_id, index))
    max_receipt = fan_in_memory.correlate(
        partition="p1", event_ids=fan_in_ids[:32], window_seconds=60
    )
    replay_receipt = fan_in_memory.correlate(
        partition="p1", event_ids=fan_in_ids[:32], window_seconds=60
    )
    high_fan_in = {
        "accepted_event_count": len(max_receipt.event_ids),
        "deterministic": max_receipt == replay_receipt,
        "oversized_rejected": _raises(
            ValueError,
            lambda: fan_in_memory.correlate(
                partition="p1", event_ids=fan_in_ids, window_seconds=60
            ),
        ),
        "non_authorizing": (
            max_receipt.authorized is False and max_receipt.external_actions == 0
        ),
    }

    edge_receipts = (
        evidence_receipt(_observation("score_zero", score=0.0, predicted=False)),
        evidence_receipt(_observation("score_one", score=1.0, predicted=True)),
    )
    confidence_edges = {
        "scores": [receipt.score for receipt in edge_receipts],
        "uncalibrated": all(
            receipt.score_semantics == "uncalibrated_score" for receipt in edge_receipts
        ),
        "non_authorizing": all(
            receipt.authorized is False and receipt.external_actions == 0
            for receipt in edge_receipts
        ),
    }

    prohibited = evaluate_policy_proposal(
        lambda _: 2,
        np.array([0.0, 1.0], dtype=np.float32),
        allowed_actions=(0, 1),
        action_count=3,
        fallback_action=0,
    )

    def predictor_error(_):
        raise RuntimeError("synthetic predictor failure")

    runtime_failure = evaluate_policy_proposal(
        predictor_error,
        np.array([0.0, 1.0], dtype=np.float32),
        allowed_actions=(0, 1),
        action_count=3,
        fallback_action=0,
    )
    malformed = evaluate_policy_proposal(
        lambda _: np.array([0, 1], dtype=np.int64),
        np.array([0.0, 1.0], dtype=np.float32),
        allowed_actions=(0, 1),
        action_count=3,
        fallback_action=0,
    )
    policy_failures = {
        "prohibited_fallback": (
            prohibited.accepted is False
            and prohibited.fallback_reason == "prohibited_action"
            and prohibited.executed_action == 0
        ),
        "predictor_error_fallback": (
            runtime_failure.accepted is False
            and runtime_failure.fallback_reason == "predictor_error"
            and runtime_failure.executed_action == 0
        ),
        "invalid_output_fallback": (
            malformed.accepted is False
            and malformed.fallback_reason == "invalid_output"
            and malformed.executed_action == 0
        ),
        "non_authorizing": all(
            receipt.authorized is False and receipt.external_actions == 0
            for receipt in (prohibited, runtime_failure, malformed)
        ),
    }

    sections = (provenance_eviction, high_fan_in, confidence_edges, policy_failures)
    passed = all(
        value is True
        for section in sections
        for key, value in section.items()
        if key not in {"accepted_event_count", "scores"}
    )
    passed = (
        passed
        and high_fan_in["accepted_event_count"] == 32
        and confidence_edges["scores"] == [0.0, 1.0]
    )
    if not passed:
        raise RuntimeError("cross-stage failure-path qualification failed")

    return {
        "scope": "synthetic_cross_stage_failure_paths_only",
        "provenance_eviction": provenance_eviction,
        "high_fan_in": high_fan_in,
        "confidence_edges": confidence_edges,
        "policy_failures": policy_failures,
        "passed": True,
        "production_qualified": False,
        "authorized": False,
        "external_actions": 0,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
