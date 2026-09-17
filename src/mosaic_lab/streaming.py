"""Bounded synthetic streaming-learning adapter.

The adapter accepts only opaque numeric features, stays within one partition, and
produces non-executing prediction receipts. Scores are not claimed to be calibrated
probabilities. No remote resources, external actions, or persistence are exposed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.metadata
import json
from math import ceil, isfinite
from time import perf_counter

import numpy as np
from river import drift, linear_model, optim, preprocessing
from sklearn.linear_model import LogisticRegression as BatchLogisticRegression
from sklearn.metrics import balanced_accuracy_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .contracts import token, unit_score, utc

MAX_FEATURES = 32
MAX_SOURCES = 256
MAX_UPDATES = 100_000
MAX_ABS_FEATURE = 1_000_000.0
LEARNING_RATE = 0.1
MODEL_ID = "river-standardized-logistic-0_26_1-sgd0_1-v2"


def _positive_int(name: str, value: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} out of range")
    return value


def _finite_feature(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("features must be numeric")
    value = float(value)
    if not isfinite(value) or abs(value) > MAX_ABS_FEATURE:
        raise ValueError("feature out of range")
    return value


def _new_model():
    """Create the fixed, reviewed River learning pipeline."""
    return preprocessing.StandardScaler() | linear_model.LogisticRegression(
        optimizer=optim.SGD(LEARNING_RATE),
        l2=0.001,
    )


@dataclass(frozen=True)
class StreamSample:
    partition: str
    sample_id: str
    source_id: str
    observed_at: datetime
    features: tuple[float, ...]
    label: bool | None = None
    version: str = "1"

    def __post_init__(self) -> None:
        token(self.partition)
        token(self.sample_id)
        token(self.source_id)
        utc(self.observed_at)
        if self.version != "1":
            raise ValueError("unsupported stream contract version")
        if not isinstance(self.features, tuple) or not 1 <= len(self.features) <= MAX_FEATURES:
            raise ValueError("bounded immutable features required")
        for value in self.features:
            _finite_feature(value)
        if self.label is not None and not isinstance(self.label, bool):
            raise ValueError("label must be boolean when present")


@dataclass(frozen=True)
class StreamOutcome:
    partition: str
    sample_id: str
    score: float
    predicted: bool
    abstained: bool
    drift_detected: bool
    update_index: int
    model_id: str = MODEL_ID
    kind: str = "prediction"
    authorized: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        token(self.partition)
        token(self.sample_id)
        unit_score(self.score)
        if self.model_id != MODEL_ID:
            raise ValueError("unsupported model receipt")
        if self.kind != "prediction":
            raise ValueError("unsupported stream outcome kind")
        if self.version != "1":
            raise ValueError("unsupported stream outcome version")
        if self.authorized is not False or self.external_actions != 0:
            raise ValueError("stream outcomes have no execution authority")
        if not isinstance(self.predicted, bool) or not isinstance(self.abstained, bool):
            raise ValueError("invalid prediction flags")
        if not isinstance(self.drift_detected, bool):
            raise ValueError("invalid drift flag")
        if (
            isinstance(self.update_index, bool)
            or not isinstance(self.update_index, int)
            or not 0 <= self.update_index <= MAX_UPDATES
        ):
            raise ValueError("invalid update index")


class RiverBinaryAdapter:
    """Fixed standardized River logistic learner with bounded state."""

    def __init__(
        self,
        partition: str,
        *,
        feature_count: int,
        abstain_margin: float = 0.08,
        max_updates: int = MAX_UPDATES,
        drift_delta: float = 0.002,
    ) -> None:
        self.partition = token(partition)
        self.feature_count = _positive_int("feature_count", feature_count, MAX_FEATURES)
        self.max_updates = _positive_int("max_updates", max_updates, MAX_UPDATES)
        if isinstance(abstain_margin, bool) or not isinstance(abstain_margin, (int, float)):
            raise ValueError("abstain margin must be numeric")
        self.abstain_margin = float(abstain_margin)
        if not 0.0 <= self.abstain_margin < 0.5:
            raise ValueError("abstain margin out of range")
        if isinstance(drift_delta, bool) or not isinstance(drift_delta, (int, float)):
            raise ValueError("drift delta must be numeric")
        self.drift_delta = float(drift_delta)
        if not 0.0 < self.drift_delta < 1.0:
            raise ValueError("drift delta out of range")
        self._model = _new_model()
        self._drift = drift.ADWIN(delta=self.drift_delta)
        self._last_by_source: dict[str, datetime] = {}
        self._updates = 0

    @property
    def updates(self) -> int:
        return self._updates

    @property
    def source_count(self) -> int:
        return len(self._last_by_source)

    def _validate_sample(self, sample: StreamSample) -> None:
        if not isinstance(sample, StreamSample):
            raise TypeError("StreamSample required")
        if sample.partition != self.partition:
            raise ValueError("partition mismatch")
        if len(sample.features) != self.feature_count:
            raise ValueError("feature count mismatch")

    def _features(self, sample: StreamSample) -> dict[str, float]:
        return {f"f{i}": _finite_feature(value) for i, value in enumerate(sample.features)}

    def predict(self, sample: StreamSample) -> StreamOutcome:
        """Predict without updating temporal/model state."""
        self._validate_sample(sample)
        scores = self._model.predict_proba_one(self._features(sample))
        score = unit_score(float(scores.get(True, 0.5)))
        return StreamOutcome(
            partition=sample.partition,
            sample_id=sample.sample_id,
            score=score,
            predicted=score >= 0.5,
            abstained=abs(score - 0.5) < self.abstain_margin,
            drift_detected=False,
            update_index=self._updates,
        )

    def process(self, sample: StreamSample) -> StreamOutcome:
        """Prequential predict-then-learn for one labeled, ordered observation."""
        self._validate_sample(sample)
        if sample.label is None:
            raise ValueError("labeled sample required for learning")
        if self._updates >= self.max_updates:
            raise RuntimeError("update budget exhausted")
        observed_at = utc(sample.observed_at)
        previous = self._last_by_source.get(sample.source_id)
        if previous is not None and observed_at <= previous:
            raise ValueError("out-of-order observation")
        if previous is None and len(self._last_by_source) >= MAX_SOURCES:
            raise RuntimeError("source budget exhausted")

        features = self._features(sample)
        scores = self._model.predict_proba_one(features)
        score = unit_score(float(scores.get(True, 0.5)))
        predicted = score >= 0.5
        error = float(predicted != sample.label)
        self._model.learn_one(features, sample.label)
        self._drift.update(error)
        self._updates += 1
        self._last_by_source[sample.source_id] = observed_at
        return StreamOutcome(
            partition=sample.partition,
            sample_id=sample.sample_id,
            score=score,
            predicted=predicted,
            abstained=abs(score - 0.5) < self.abstain_margin,
            drift_detected=bool(self._drift.drift_detected),
            update_index=self._updates,
        )

    def state_receipt(self) -> str:
        """Digest bounded wrapper metadata for replay checks; this is not model persistence."""
        payload = {
            "partition": self.partition,
            "feature_count": self.feature_count,
            "updates": self._updates,
            "sources": sorted((key, utc(value).isoformat()) for key, value in self._last_by_source.items()),
            "drift_detections": int(self._drift.n_detections),
            "model_id": MODEL_ID,
            "learning_rate": LEARNING_RATE,
            "standardized": True,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def synthetic_stream(*, size: int = 2400, seed: int = 31) -> tuple[np.ndarray, np.ndarray, int]:
    if isinstance(size, bool) or not isinstance(size, int) or not 400 <= size <= 50_000:
        raise ValueError("stream size out of range")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    rng = np.random.default_rng(seed)
    features = rng.uniform(-1.0, 1.0, (size, 6))
    drift_at = size // 2
    before = 2.2 * features[:, 0] - 1.6 * features[:, 1] + 0.8 * features[:, 2]
    after = -1.8 * features[:, 0] + 2.1 * features[:, 1] - 0.9 * features[:, 3]
    signal = np.where(np.arange(size) < drift_at, before, after)
    labels = signal + rng.normal(0.0, 0.28, size) > 0.0
    return features, labels.astype(bool), drift_at


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def _window_metrics(labels: np.ndarray, scores: np.ndarray, abstained: np.ndarray) -> dict[str, float]:
    predicted = scores >= 0.5
    return {
        "balanced_accuracy": float(balanced_accuracy_score(labels, predicted)),
        "mean_squared_score_error": float(np.mean((scores - labels.astype(float)) ** 2)),
        "abstention_rate": float(np.mean(abstained)),
    }


def benchmark_stream(*, size: int = 2400, seed: int = 31) -> dict[str, object]:
    """Compare bounded streaming adaptation with a frozen batch baseline on synthetic drift."""
    features, labels, drift_at = synthetic_stream(size=size, seed=seed)
    adapter = RiverBinaryAdapter("p1", feature_count=features.shape[1])
    scores: list[float] = []
    abstained: list[bool] = []
    latencies_ms: list[float] = []
    detections: list[int] = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, (row, label) in enumerate(zip(features, labels, strict=True)):
        sample = StreamSample(
            partition="p1",
            sample_id=f"s{index}",
            source_id="src1",
            observed_at=start + timedelta(milliseconds=index + 1),
            features=tuple(float(value) for value in row),
            label=bool(label),
        )
        started = perf_counter()
        outcome = adapter.process(sample)
        latencies_ms.append((perf_counter() - started) * 1000.0)
        scores.append(outcome.score)
        abstained.append(outcome.abstained)
        if outcome.drift_detected:
            detections.append(index)

    train_stop = max(120, drift_at // 2)
    batch = make_pipeline(StandardScaler(), BatchLogisticRegression(max_iter=500, random_state=seed))
    batch.fit(features[:train_stop], labels[:train_stop])
    post_start = drift_at + max(50, (size - drift_at) // 4)
    batch_scores = batch.predict_proba(features[post_start:])[:, 1]
    stream_scores = np.asarray(scores, dtype=float)
    abstain_array = np.asarray(abstained, dtype=bool)
    stream_post = _window_metrics(labels[post_start:], stream_scores[post_start:], abstain_array[post_start:])
    batch_post = _window_metrics(
        labels[post_start:],
        np.asarray(batch_scores, dtype=float),
        np.zeros(len(batch_scores), dtype=bool),
    )
    versions = {name: importlib.metadata.version(name) for name in ("river", "narwhals", "numpy", "scikit-learn")}
    return {
        "scope": "synthetic_stream_demonstration_only",
        "seed": seed,
        "samples": size,
        "drift_index": drift_at,
        "evaluation_start": post_start,
        "streaming": stream_post,
        "frozen_batch": batch_post,
        "drift_detections": detections,
        "update_latency_ms": {
            "p50": round(float(np.median(latencies_ms)), 4),
            "p95": round(_p95(latencies_ms), 4),
        },
        "updates": adapter.updates,
        "sources": adapter.source_count,
        "state_receipt": adapter.state_receipt(),
        "learner": {
            "model_id": MODEL_ID,
            "learning_rate": LEARNING_RATE,
            "standardized": True,
        },
        "versions": versions,
        "score_calibration_established": False,
        "production_qualified": False,
        "saved_weights": False,
        "external_actions": 0,
    }
