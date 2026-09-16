"""Synthetic held-out quality evaluation for the bounded streaming candidate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite
import tracemalloc

import numpy as np

from .streaming import MAX_SOURCES, RiverBinaryAdapter, StreamSample, synthetic_stream

DEFAULT_MARGINS = (0.02, 0.04, 0.08)


def _margins(values: tuple[float, ...]) -> tuple[float, ...]:
    if not isinstance(values, tuple) or not values or len(values) > 8:
        raise ValueError("bounded margin tuple required")
    parsed = tuple(float(value) for value in values)
    if any((not isfinite(value)) or not 0.0 <= value < 0.5 for value in parsed):
        raise ValueError("margin out of range")
    if tuple(sorted(set(parsed))) != parsed:
        raise ValueError("margins must be unique and increasing")
    return parsed


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else float(numerator / denominator)


def evaluate_stream_quality(
    *,
    size: int = 1200,
    seed: int = 31,
    margins: tuple[float, ...] = DEFAULT_MARGINS,
) -> dict[str, object]:
    """Measure held-out coverage/error tradeoffs without changing the learner."""
    margins = _margins(margins)
    features, labels, drift_at = synthetic_stream(size=size, seed=seed)
    post_start = drift_at + max(50, (size - drift_at) // 4)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    results: list[dict[str, object]] = []
    receipts: list[str] = []

    for margin in margins:
        adapter = RiverBinaryAdapter("p1", feature_count=features.shape[1], abstain_margin=margin)
        scores: list[float] = []
        abstained: list[bool] = []
        tracemalloc.start()
        try:
            for index, (row, label) in enumerate(zip(features, labels, strict=True)):
                outcome = adapter.process(
                    StreamSample(
                        partition="p1",
                        sample_id=f"q{index}",
                        source_id="src1",
                        observed_at=start + timedelta(milliseconds=index + 1),
                        features=tuple(float(value) for value in row),
                        label=bool(label),
                    )
                )
                scores.append(outcome.score)
                abstained.append(outcome.abstained)
            _, peak_bytes = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        post_scores = np.asarray(scores[post_start:], dtype=float)
        post_labels = labels[post_start:].astype(bool)
        post_abstained = np.asarray(abstained[post_start:], dtype=bool)
        answered = ~post_abstained
        predicted = post_scores >= 0.5
        answered_count = int(np.sum(answered))
        positives = int(np.sum(post_labels & answered))
        negatives = int(np.sum((~post_labels) & answered))
        false_positives = int(np.sum(predicted & (~post_labels) & answered))
        false_negatives = int(np.sum((~predicted) & post_labels & answered))
        selective_mse = (
            None
            if answered_count == 0
            else float(np.mean((post_scores[answered] - post_labels[answered].astype(float)) ** 2))
        )
        results.append(
            {
                "margin": margin,
                "answered_rate": float(np.mean(answered)),
                "abstention_rate": float(np.mean(post_abstained)),
                "selective_mean_squared_score_error": selective_mse,
                "false_positive_rate_answered": _rate(false_positives, negatives),
                "false_negative_rate_answered": _rate(false_negatives, positives),
                "python_tracemalloc_peak_bytes": int(peak_bytes),
                "state_bounds": {
                    "feature_count": int(adapter.feature_count),
                    "source_count": int(adapter.source_count),
                    "source_limit": MAX_SOURCES,
                    "update_count": int(adapter.updates),
                    "update_limit": int(adapter.max_updates),
                },
            }
        )
        receipts.append(adapter.state_receipt())

    return {
        "scope": "synthetic_stream_quality_only",
        "seed": seed,
        "samples": size,
        "drift_index": drift_at,
        "evaluation_start": post_start,
        "margins": results,
        "learning_state_identical_across_margin_sweep": len(set(receipts)) == 1,
        "python_memory_measurement_includes_native_allocations": False,
        "score_calibration_established": False,
        "production_qualified": False,
        "saved_weights": False,
        "external_actions": 0,
    }
