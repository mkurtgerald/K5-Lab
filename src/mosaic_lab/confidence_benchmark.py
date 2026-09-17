"""Synthetic multi-seed confidence/abstention diagnostics for S5."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
from time import perf_counter
import tracemalloc

import numpy as np

from .confidence import ConfidenceObservation, calibration_report, evidence_receipt
from .streaming import MODEL_ID, RiverBinaryAdapter, StreamSample, synthetic_stream

DEFAULT_SEEDS = (7, 19, 31, 43, 59)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def _stationary_stream(*, size: int, seed: int) -> tuple[np.ndarray, np.ndarray, int]:
    rng = np.random.default_rng(seed)
    features = rng.uniform(-1.0, 1.0, (size, 6))
    signal = 2.2 * features[:, 0] - 1.6 * features[:, 1] + 0.8 * features[:, 2]
    labels = signal + rng.normal(0.0, 0.28, size) > 0.0
    return features, labels.astype(bool), size // 2


def _observations(
    *,
    scenario: str,
    size: int,
    seed: int,
) -> tuple[ConfidenceObservation, ...]:
    if scenario == "stationary":
        features, labels, marker = _stationary_stream(size=size, seed=seed)
        evaluation_start = marker
    elif scenario == "shifted":
        features, labels, drift_at = synthetic_stream(size=size, seed=seed)
        evaluation_start = drift_at + max(50, (size - drift_at) // 4)
    else:
        raise ValueError("unsupported confidence scenario")

    adapter = RiverBinaryAdapter("p1", feature_count=features.shape[1])
    started_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows: list[ConfidenceObservation] = []
    for index, (features_row, label) in enumerate(zip(features, labels, strict=True)):
        sample = StreamSample(
            partition="p1",
            sample_id=f"{scenario}_{seed}_{index}",
            source_id="src1",
            observed_at=started_at + timedelta(milliseconds=index + 1),
            features=tuple(float(value) for value in features_row),
            label=bool(label),
        )
        outcome = adapter.process(sample)
        if index >= evaluation_start:
            rows.append(
                ConfidenceObservation(
                    partition=outcome.partition,
                    sample_id=outcome.sample_id,
                    source_id=sample.source_id,
                    model_id=MODEL_ID,
                    observed_at=sample.observed_at,
                    score=outcome.score,
                    predicted=outcome.predicted,
                    label=bool(label),
                    abstained=outcome.abstained,
                    drift_detected=outcome.drift_detected,
                )
            )
    return tuple(rows)


def _quality_passed(report: dict[str, object]) -> bool:
    balanced = report["balanced_accuracy"]
    fpr = report["false_positive_rate"]
    fnr = report["false_negative_rate"]
    return bool(
        report["evidence_sufficient"]
        and isinstance(balanced, float)
        and balanced >= 0.65
        and report["coverage"] >= 0.65
        and (fpr is None or fpr <= 0.35)
        and (fnr is None or fnr <= 0.35)
        and report["raw_score_brier"] <= 0.30
        and report["raw_score_ece"] <= 0.35
        and report["calibrated_probability_established"] is False
        and report["authorized"] is False
        and report["external_actions"] == 0
    )


def evaluate_confidence_quality(
    *,
    size: int = 600,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
) -> dict[str, object]:
    if isinstance(size, bool) or not isinstance(size, int) or not 400 <= size <= 5000:
        raise ValueError("confidence benchmark size out of range")
    if (
        not isinstance(seeds, tuple)
        or not 1 <= len(seeds) <= 16
        or any(isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise ValueError("bounded unique integer seeds required")

    scenarios: list[dict[str, object]] = []
    diagnostic_latencies_ms: list[float] = []
    receipt_latencies_ms: list[float] = []
    diagnostic_peak_kib: list[float] = []

    for scenario in ("stationary", "shifted"):
        for seed in seeds:
            rows = _observations(scenario=scenario, size=size, seed=seed)
            minimum_samples = max(100, ceil(len(rows) * 0.5))

            tracemalloc.start()
            report_started = perf_counter()
            report_obj = calibration_report(
                rows, bins=10, minimum_samples=minimum_samples
            )
            diagnostic_latencies_ms.append((perf_counter() - report_started) * 1000.0)
            receipts = []
            for row in rows[: min(32, len(rows))]:
                receipt_started = perf_counter()
                receipt = evidence_receipt(row)
                receipt_latencies_ms.append((perf_counter() - receipt_started) * 1000.0)
                receipts.append(receipt.receipt_id)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            diagnostic_peak_kib.append(peak / 1024.0)

            report = asdict(report_obj)
            scenario_result = {
                "scenario": scenario,
                "seed": seed,
                "evaluation_samples": len(rows),
                "minimum_answered_samples": minimum_samples,
                "report": report,
                "receipt_digest": sha256(
                    "\n".join(receipts).encode("utf-8")
                ).hexdigest(),
                "passed": _quality_passed(report),
            }
            scenarios.append(scenario_result)

    stable_payload = [
        {
            "scenario": row["scenario"],
            "seed": row["seed"],
            "evaluation_samples": row["evaluation_samples"],
            "minimum_answered_samples": row["minimum_answered_samples"],
            "report": row["report"],
            "receipt_digest": row["receipt_digest"],
        }
        for row in scenarios
    ]
    quality_digest = sha256(
        json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return {
        "scope": "synthetic_confidence_diagnostics_only",
        "samples_per_stream": size,
        "seeds": list(seeds),
        "scenarios": scenarios,
        "quality_digest": quality_digest,
        "diagnostic_latency_ms": {
            "p50": round(float(np.median(diagnostic_latencies_ms)), 6),
            "p95": round(_p95(diagnostic_latencies_ms), 6),
        },
        "receipt_latency_ms": {
            "p50": round(float(np.median(receipt_latencies_ms)), 6),
            "p95": round(_p95(receipt_latencies_ms), 6),
        },
        "diagnostic_python_peak_kib": {
            "max": round(max(diagnostic_peak_kib), 3),
        },
        "score_semantics": "uncalibrated_score",
        "calibrated_probability_established": False,
        "production_qualified": False,
        "authorized": False,
        "external_actions": 0,
        "passed": all(bool(row["passed"]) for row in scenarios),
    }
