"""Bounded confidence, abstention and evidence diagnostics.

Raw model scores remain explicitly uncalibrated unless a future reviewed
calibration stage establishes probability semantics. This module provides only
bounded empirical diagnostics and deterministic non-authorizing receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from .contracts import token, unit_score, utc
from .memory import BoundedEventMemory, MissingReference

MAX_PROVENANCE = 32
MAX_OBSERVATIONS = 50_000
MAX_BINS = 32


def _bool(value: object, *, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    return value


def _optional_unit(value: float | None, *, name: str) -> float | None:
    if value is None:
        return None
    try:
        return unit_score(value)
    except ValueError as exc:
        raise ValueError(f"{name} out of range") from exc


def _evidence_id(
    *,
    partition: str,
    sample_id: str,
    model_id: str,
    score: float,
    predicted: bool,
    abstained: bool,
    drift_detected: bool,
    rule_id: str,
    provenance: tuple[str, ...],
) -> str:
    payload = {
        "version": "1",
        "partition": partition,
        "sample_id": sample_id,
        "model_id": model_id,
        "score": format(score, ".17g"),
        "score_semantics": "uncalibrated_score",
        "predicted": predicted,
        "abstained": abstained,
        "drift_detected": drift_detected,
        "rule_id": rule_id,
        "provenance": provenance,
    }
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:32]
    return "ev_" + digest


@dataclass(frozen=True)
class ConfidenceObservation:
    partition: str
    sample_id: str
    source_id: str
    model_id: str
    observed_at: datetime
    score: float
    predicted: bool
    label: bool
    abstained: bool
    drift_detected: bool
    provenance: tuple[str, ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        for value in (self.partition, self.sample_id, self.source_id, self.model_id):
            token(value)
        utc(self.observed_at)
        unit_score(self.score)
        _bool(self.predicted, name="predicted")
        _bool(self.label, name="label")
        _bool(self.abstained, name="abstained")
        _bool(self.drift_detected, name="drift_detected")
        if self.version != "1":
            raise ValueError("unsupported confidence observation version")
        if not isinstance(self.provenance, tuple) or len(self.provenance) > MAX_PROVENANCE:
            raise ValueError("bounded immutable provenance required")
        if len(set(self.provenance)) != len(self.provenance):
            raise ValueError("duplicate provenance reference")
        for ref in self.provenance:
            token(ref)


@dataclass(frozen=True)
class CalibrationReport:
    partition: str
    model_id: str
    sample_count: int
    answered_count: int
    coverage: float
    abstention_rate: float
    balanced_accuracy: float | None
    false_positive_rate: float | None
    false_negative_rate: float | None
    raw_score_brier: float
    answered_brier: float | None
    raw_score_ece: float
    bins: int
    evidence_sufficient: bool
    score_semantics: str = "uncalibrated_score"
    calibrated_probability_established: bool = False
    authorized: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        token(self.partition)
        token(self.model_id)
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or not 1 <= self.sample_count <= MAX_OBSERVATIONS
        ):
            raise ValueError("sample_count out of range")
        if (
            isinstance(self.answered_count, bool)
            or not isinstance(self.answered_count, int)
            or not 0 <= self.answered_count <= self.sample_count
        ):
            raise ValueError("answered_count out of range")
        if (
            isinstance(self.bins, bool)
            or not isinstance(self.bins, int)
            or not 2 <= self.bins <= MAX_BINS
        ):
            raise ValueError("bins out of range")
        coverage = unit_score(self.coverage)
        abstention = unit_score(self.abstention_rate)
        if abs((coverage + abstention) - 1.0) > 1e-12:
            raise ValueError("coverage and abstention are inconsistent")
        _optional_unit(self.balanced_accuracy, name="balanced_accuracy")
        _optional_unit(self.false_positive_rate, name="false_positive_rate")
        _optional_unit(self.false_negative_rate, name="false_negative_rate")
        unit_score(self.raw_score_brier)
        _optional_unit(self.answered_brier, name="answered_brier")
        unit_score(self.raw_score_ece)
        _bool(self.evidence_sufficient, name="evidence_sufficient")
        if self.answered_count == 0 and self.answered_brier is not None:
            raise ValueError("answered_brier requires answered observations")
        if self.answered_count > 0 and self.answered_brier is None:
            raise ValueError("answered observations require answered_brier")
        if self.version != "1":
            raise ValueError("unsupported calibration report version")
        if self.score_semantics != "uncalibrated_score":
            raise ValueError("raw score probability semantics are not established")
        if self.calibrated_probability_established is not False:
            raise ValueError("this stage does not establish calibrated probability")
        if self.authorized is not False or self.external_actions != 0:
            raise ValueError("confidence reports have no execution authority")


@dataclass(frozen=True)
class EvidenceReceipt:
    receipt_id: str
    partition: str
    sample_id: str
    model_id: str
    score: float
    score_semantics: str
    predicted: bool
    abstained: bool
    drift_detected: bool
    rule_id: str
    provenance: tuple[str, ...]
    authorized: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        for value in (
            self.receipt_id,
            self.partition,
            self.sample_id,
            self.model_id,
            self.rule_id,
        ):
            token(value)
        score = unit_score(self.score)
        if self.score_semantics != "uncalibrated_score":
            raise ValueError("unsupported score semantics")
        for name, value in (
            ("predicted", self.predicted),
            ("abstained", self.abstained),
            ("drift_detected", self.drift_detected),
        ):
            _bool(value, name=name)
        if not isinstance(self.provenance, tuple) or len(self.provenance) > MAX_PROVENANCE:
            raise ValueError("bounded immutable provenance required")
        if tuple(sorted(self.provenance)) != self.provenance:
            raise ValueError("evidence provenance must be canonical")
        if len(set(self.provenance)) != len(self.provenance):
            raise ValueError("duplicate provenance reference")
        for ref in self.provenance:
            token(ref)
        if self.version != "1":
            raise ValueError("unsupported evidence receipt version")
        if self.authorized is not False or self.external_actions != 0:
            raise ValueError("evidence receipts have no execution authority")
        expected = _evidence_id(
            partition=self.partition,
            sample_id=self.sample_id,
            model_id=self.model_id,
            score=score,
            predicted=self.predicted,
            abstained=self.abstained,
            drift_detected=self.drift_detected,
            rule_id=self.rule_id,
            provenance=self.provenance,
        )
        if self.receipt_id != expected:
            raise ValueError("evidence receipt integrity mismatch")


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _ece(rows: tuple[ConfidenceObservation, ...], bins: int) -> float:
    total = len(rows)
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        bucket = [
            row
            for row in rows
            if row.score >= lower
            and (row.score < upper or (index == bins - 1 and row.score <= upper))
        ]
        if not bucket:
            continue
        mean_score = sum(row.score for row in bucket) / len(bucket)
        empirical = sum(1.0 if row.label else 0.0 for row in bucket) / len(bucket)
        error += (len(bucket) / total) * abs(mean_score - empirical)
    return error


def calibration_report(
    observations: tuple[ConfidenceObservation, ...],
    *,
    bins: int = 10,
    minimum_samples: int = 200,
) -> CalibrationReport:
    if not isinstance(observations, tuple) or not 1 <= len(observations) <= MAX_OBSERVATIONS:
        raise ValueError("bounded non-empty observations tuple required")
    if isinstance(bins, bool) or not isinstance(bins, int) or not 2 <= bins <= MAX_BINS:
        raise ValueError("bins out of range")
    if (
        isinstance(minimum_samples, bool)
        or not isinstance(minimum_samples, int)
        or not 2 <= minimum_samples <= MAX_OBSERVATIONS
    ):
        raise ValueError("minimum_samples out of range")
    if not all(isinstance(row, ConfidenceObservation) for row in observations):
        raise TypeError("ConfidenceObservation entries required")

    first = observations[0]
    if any(row.partition != first.partition for row in observations):
        raise ValueError("partition mixing is not allowed")
    if any(row.model_id != first.model_id for row in observations):
        raise ValueError("model mixing is not allowed")
    sample_ids = [row.sample_id for row in observations]
    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("duplicate sample identifier")

    rows = tuple(sorted(observations, key=lambda row: (utc(row.observed_at), row.sample_id)))
    answered = tuple(row for row in rows if not row.abstained)
    answered_count = len(answered)
    sample_count = len(rows)
    coverage = answered_count / sample_count
    abstention_rate = 1.0 - coverage

    tp = sum(1 for row in answered if row.predicted and row.label)
    tn = sum(1 for row in answered if not row.predicted and not row.label)
    fp = sum(1 for row in answered if row.predicted and not row.label)
    fn = sum(1 for row in answered if not row.predicted and row.label)
    positives = tp + fn
    negatives = tn + fp
    tpr = _rate(tp, positives)
    tnr = _rate(tn, negatives)
    balanced = None if tpr is None or tnr is None else (tpr + tnr) / 2.0

    raw_brier = sum((row.score - float(row.label)) ** 2 for row in rows) / sample_count
    answered_brier = (
        None
        if not answered
        else sum((row.score - float(row.label)) ** 2 for row in answered) / answered_count
    )
    evidence_sufficient = (
        answered_count >= minimum_samples
        and positives > 0
        and negatives > 0
    )

    return CalibrationReport(
        partition=first.partition,
        model_id=first.model_id,
        sample_count=sample_count,
        answered_count=answered_count,
        coverage=coverage,
        abstention_rate=abstention_rate,
        balanced_accuracy=balanced,
        false_positive_rate=_rate(fp, negatives),
        false_negative_rate=_rate(fn, positives),
        raw_score_brier=raw_brier,
        answered_brier=answered_brier,
        raw_score_ece=_ece(rows, bins),
        bins=bins,
        evidence_sufficient=evidence_sufficient,
    )


def evidence_receipt(
    observation: ConfidenceObservation,
    *,
    rule_id: str = "threshold_abstain_v1",
    memory: BoundedEventMemory | None = None,
) -> EvidenceReceipt:
    if not isinstance(observation, ConfidenceObservation):
        raise TypeError("ConfidenceObservation required")
    token(rule_id)
    provenance = tuple(sorted(observation.provenance))
    if provenance:
        if memory is None:
            raise MissingReference("resident provenance verification required")
        if not isinstance(memory, BoundedEventMemory):
            raise TypeError("BoundedEventMemory required")
        for ref in provenance:
            memory.get(observation.partition, ref)
    receipt_id = _evidence_id(
        partition=observation.partition,
        sample_id=observation.sample_id,
        model_id=observation.model_id,
        score=observation.score,
        predicted=observation.predicted,
        abstained=observation.abstained,
        drift_detected=observation.drift_detected,
        rule_id=rule_id,
        provenance=provenance,
    )
    return EvidenceReceipt(
        receipt_id=receipt_id,
        partition=observation.partition,
        sample_id=observation.sample_id,
        model_id=observation.model_id,
        score=observation.score,
        score_semantics="uncalibrated_score",
        predicted=observation.predicted,
        abstained=observation.abstained,
        drift_detected=observation.drift_detected,
        rule_id=rule_id,
        provenance=provenance,
    )
