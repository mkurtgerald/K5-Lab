"""Synthetic robustness evidence for the bounded S2 streaming candidate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import isfinite

import numpy as np
from sklearn.metrics import balanced_accuracy_score

from .streaming import RiverBinaryAdapter, StreamSample, synthetic_stream

DEFAULT_POISON_INTERVAL = 17
DEFAULT_RARE_ABS_FEATURE = 0.99
DEFAULT_ROBUSTNESS_SEEDS = (7, 19, 31, 43, 59)


def _bounded_rate(name: str, value: float) -> float:
    parsed = float(value)
    if not isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise RuntimeError(f"{name} out of range")
    return parsed


def _validate_seeds(seeds: tuple[int, ...]) -> tuple[int, ...]:
    if not isinstance(seeds, tuple) or not 3 <= len(seeds) <= 16:
        raise ValueError("robustness seeds must be a tuple containing 3 to 16 values")
    if any(isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2_147_483_647 for seed in seeds):
        raise ValueError("robustness seeds must be bounded non-negative integers")
    if len(set(seeds)) != len(seeds):
        raise ValueError("robustness seeds must be unique")
    return seeds


def _selective_metrics(labels: np.ndarray, scores: np.ndarray, abstained: np.ndarray) -> dict[str, float]:
    answered = ~abstained
    answered_rate = float(np.mean(answered))
    if not np.any(answered):
        raise RuntimeError("robustness evaluation has no answered samples")
    y = labels[answered]
    predicted = scores[answered] >= 0.5
    false_positive = np.logical_and(predicted, ~y)
    false_negative = np.logical_and(~predicted, y)
    negatives = max(1, int(np.sum(~y)))
    positives = max(1, int(np.sum(y)))
    return {
        "answered_rate": _bounded_rate("answered_rate", answered_rate),
        "balanced_accuracy": _bounded_rate(
            "balanced_accuracy", float(balanced_accuracy_score(y, predicted))
        ),
        "false_positive_rate_answered": _bounded_rate(
            "false_positive_rate_answered", float(np.sum(false_positive)) / negatives
        ),
        "false_negative_rate_answered": _bounded_rate(
            "false_negative_rate_answered", float(np.sum(false_negative)) / positives
        ),
        "selective_mean_squared_score_error": _bounded_rate(
            "selective_mean_squared_score_error",
            float(np.mean((scores[answered] - y.astype(float)) ** 2)),
        ),
    }


def _rare_metrics(labels: np.ndarray, scores: np.ndarray, features: np.ndarray, threshold: float) -> dict[str, float | int]:
    mask = np.max(np.abs(features), axis=1) >= threshold
    count = int(np.sum(mask))
    if count == 0:
        raise RuntimeError("rare-case fixture produced no rare samples")
    predicted = scores[mask] >= 0.5
    return {
        "count": count,
        "fraction": _bounded_rate("rare_fraction", count / len(labels)),
        "error_rate": _bounded_rate("rare_error_rate", float(np.mean(predicted != labels[mask]))),
        "mean_squared_score_error": _bounded_rate(
            "rare_mean_squared_score_error",
            float(np.mean((scores[mask] - labels[mask].astype(float)) ** 2)),
        ),
    }


def evaluate_stream_robustness(
    *,
    size: int = 600,
    seed: int = 31,
    poison_interval: int = DEFAULT_POISON_INTERVAL,
    rare_abs_feature: float = DEFAULT_RARE_ABS_FEATURE,
) -> dict[str, object]:
    """Measure bounded recovery from deterministic label poisoning plus rare-tail behavior.

    Poisoning is synthetic label corruption applied only before the held-out evaluation
    window. The learner receives clean labels again during evaluation so this measures
    recovery from prior corrupted supervision rather than a permanently adversarial feed.
    A third adapter starts cold at the held-out boundary to expose recovery without prior
    state instead of allowing warm-history aggregate quality to hide cold-start behavior.
    """
    if isinstance(poison_interval, bool) or not isinstance(poison_interval, int) or not 5 <= poison_interval <= 100:
        raise ValueError("poison_interval out of range")
    if isinstance(rare_abs_feature, bool) or not isinstance(rare_abs_feature, (int, float)):
        raise ValueError("rare_abs_feature must be numeric")
    rare_abs_feature = float(rare_abs_feature)
    if not isfinite(rare_abs_feature) or not 0.90 <= rare_abs_feature < 1.0:
        raise ValueError("rare_abs_feature out of range")

    features, labels, drift_at = synthetic_stream(size=size, seed=seed)
    evaluation_start = drift_at + max(50, (size - drift_at) // 4)
    poison_indexes = set(range(5, evaluation_start, poison_interval))
    if not poison_indexes:
        raise RuntimeError("poison fixture empty")

    clean = RiverBinaryAdapter("p1", feature_count=features.shape[1], abstain_margin=0.04)
    poisoned = RiverBinaryAdapter("p1", feature_count=features.shape[1], abstain_margin=0.04)
    cold_start = RiverBinaryAdapter("p1", feature_count=features.shape[1], abstain_margin=0.04)
    clean_scores: list[float] = []
    clean_abstain: list[bool] = []
    poisoned_scores: list[float] = []
    poisoned_abstain: list[bool] = []
    cold_scores: list[float] = []
    cold_abstain: list[bool] = []
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for index, (row, true_label) in enumerate(zip(features, labels, strict=True)):
        common = {
            "partition": "p1",
            "sample_id": f"r{index}",
            "source_id": "src1",
            "observed_at": start + timedelta(milliseconds=index + 1),
            "features": tuple(float(value) for value in row),
        }
        clean_sample = StreamSample(**common, label=bool(true_label))
        clean_outcome = clean.process(clean_sample)
        poison_label = (not bool(true_label)) if index in poison_indexes else bool(true_label)
        poison_outcome = poisoned.process(StreamSample(**common, label=poison_label))
        if index >= evaluation_start:
            cold_outcome = cold_start.process(clean_sample)
            clean_scores.append(clean_outcome.score)
            clean_abstain.append(clean_outcome.abstained)
            poisoned_scores.append(poison_outcome.score)
            poisoned_abstain.append(poison_outcome.abstained)
            cold_scores.append(cold_outcome.score)
            cold_abstain.append(cold_outcome.abstained)

    evaluation_labels = labels[evaluation_start:]
    evaluation_features = features[evaluation_start:]
    clean_score_array = np.asarray(clean_scores, dtype=float)
    poisoned_score_array = np.asarray(poisoned_scores, dtype=float)
    cold_score_array = np.asarray(cold_scores, dtype=float)
    clean_metrics = _selective_metrics(
        evaluation_labels, clean_score_array, np.asarray(clean_abstain, dtype=bool)
    )
    poisoned_metrics = _selective_metrics(
        evaluation_labels, poisoned_score_array, np.asarray(poisoned_abstain, dtype=bool)
    )
    cold_metrics = _selective_metrics(
        evaluation_labels, cold_score_array, np.asarray(cold_abstain, dtype=bool)
    )
    rare_clean = _rare_metrics(
        evaluation_labels, clean_score_array, evaluation_features, rare_abs_feature
    )
    rare_poisoned = _rare_metrics(
        evaluation_labels, poisoned_score_array, evaluation_features, rare_abs_feature
    )
    return {
        "scope": "synthetic_stream_robustness_observation_only",
        "seed": seed,
        "samples": size,
        "drift_index": drift_at,
        "evaluation_start": evaluation_start,
        "poison_interval": poison_interval,
        "poisoned_training_samples": len(poison_indexes),
        "poisoning_stops_before_evaluation": max(poison_indexes) < evaluation_start,
        "clean": clean_metrics,
        "poisoned_history": poisoned_metrics,
        "cold_start": cold_metrics,
        "cold_start_updates": cold_start.updates,
        "rare_abs_feature_threshold": rare_abs_feature,
        "rare_clean": rare_clean,
        "rare_poisoned_history": rare_poisoned,
        "missing_or_nonfinite_features_fail_closed": True,
        "performance_gate_established": False,
        "production_qualified": False,
        "saved_weights": False,
        "external_actions": 0,
    }


def evaluate_stream_robustness_multiseed(
    *,
    size: int = 600,
    seeds: tuple[int, ...] = DEFAULT_ROBUSTNESS_SEEDS,
    poison_interval: int = DEFAULT_POISON_INTERVAL,
    rare_abs_feature: float = DEFAULT_RARE_ABS_FEATURE,
) -> dict[str, object]:
    """Evaluate the fixed-seed synthetic robustness acceptance envelope."""
    seeds = _validate_seeds(seeds)
    runs = tuple(
        evaluate_stream_robustness(
            size=size,
            seed=seed,
            poison_interval=poison_interval,
            rare_abs_feature=rare_abs_feature,
        )
        for seed in seeds
    )

    criteria = {
        "min_poisoned_answered_rate": 0.75,
        "min_poisoned_balanced_accuracy": 0.75,
        "max_poisoned_false_positive_rate_answered": 0.25,
        "max_poisoned_false_negative_rate_answered": 0.25,
        "max_poisoned_selective_mean_squared_score_error": 0.20,
        "max_balanced_accuracy_drop_from_clean": 0.15,
        "max_answered_rate_drop_from_clean": 0.15,
        "max_score_error_increase_from_clean": 0.10,
        "min_cold_start_balanced_accuracy": 0.70,
        "max_cold_start_selective_mean_squared_score_error": 0.25,
        "min_total_rare_samples": 50,
        "max_mean_rare_poisoned_error_rate": 0.50,
        "max_mean_rare_error_increase": 0.20,
    }

    poisoned = tuple(run["poisoned_history"] for run in runs)
    clean = tuple(run["clean"] for run in runs)
    cold = tuple(run["cold_start"] for run in runs)
    rare_clean = tuple(run["rare_clean"] for run in runs)
    rare_poisoned = tuple(run["rare_poisoned_history"] for run in runs)
    total_rare = sum(int(item["count"]) for item in rare_poisoned)
    weighted_rare_clean_error = sum(
        int(item["count"]) * float(item["error_rate"]) for item in rare_clean
    ) / total_rare
    weighted_rare_poisoned_error = sum(
        int(item["count"]) * float(item["error_rate"]) for item in rare_poisoned
    ) / total_rare

    summary = {
        "min_poisoned_answered_rate": min(float(item["answered_rate"]) for item in poisoned),
        "min_poisoned_balanced_accuracy": min(float(item["balanced_accuracy"]) for item in poisoned),
        "max_poisoned_false_positive_rate_answered": max(
            float(item["false_positive_rate_answered"]) for item in poisoned
        ),
        "max_poisoned_false_negative_rate_answered": max(
            float(item["false_negative_rate_answered"]) for item in poisoned
        ),
        "max_poisoned_selective_mean_squared_score_error": max(
            float(item["selective_mean_squared_score_error"]) for item in poisoned
        ),
        "max_balanced_accuracy_drop_from_clean": max(
            max(0.0, float(c["balanced_accuracy"]) - float(p["balanced_accuracy"]))
            for c, p in zip(clean, poisoned, strict=True)
        ),
        "max_answered_rate_drop_from_clean": max(
            max(0.0, float(c["answered_rate"]) - float(p["answered_rate"]))
            for c, p in zip(clean, poisoned, strict=True)
        ),
        "max_score_error_increase_from_clean": max(
            max(
                0.0,
                float(p["selective_mean_squared_score_error"])
                - float(c["selective_mean_squared_score_error"]),
            )
            for c, p in zip(clean, poisoned, strict=True)
        ),
        "min_cold_start_balanced_accuracy": min(float(item["balanced_accuracy"]) for item in cold),
        "max_cold_start_selective_mean_squared_score_error": max(
            float(item["selective_mean_squared_score_error"]) for item in cold
        ),
        "total_rare_samples": total_rare,
        "mean_rare_clean_error_rate": _bounded_rate(
            "mean_rare_clean_error_rate", weighted_rare_clean_error
        ),
        "mean_rare_poisoned_error_rate": _bounded_rate(
            "mean_rare_poisoned_error_rate", weighted_rare_poisoned_error
        ),
        "mean_rare_error_increase": _bounded_rate(
            "mean_rare_error_increase",
            max(0.0, weighted_rare_poisoned_error - weighted_rare_clean_error),
        ),
    }

    passed = (
        summary["min_poisoned_answered_rate"] >= criteria["min_poisoned_answered_rate"]
        and summary["min_poisoned_balanced_accuracy"] >= criteria["min_poisoned_balanced_accuracy"]
        and summary["max_poisoned_false_positive_rate_answered"]
        <= criteria["max_poisoned_false_positive_rate_answered"]
        and summary["max_poisoned_false_negative_rate_answered"]
        <= criteria["max_poisoned_false_negative_rate_answered"]
        and summary["max_poisoned_selective_mean_squared_score_error"]
        <= criteria["max_poisoned_selective_mean_squared_score_error"]
        and summary["max_balanced_accuracy_drop_from_clean"]
        <= criteria["max_balanced_accuracy_drop_from_clean"]
        and summary["max_answered_rate_drop_from_clean"]
        <= criteria["max_answered_rate_drop_from_clean"]
        and summary["max_score_error_increase_from_clean"]
        <= criteria["max_score_error_increase_from_clean"]
        and summary["min_cold_start_balanced_accuracy"] >= criteria["min_cold_start_balanced_accuracy"]
        and summary["max_cold_start_selective_mean_squared_score_error"]
        <= criteria["max_cold_start_selective_mean_squared_score_error"]
        and summary["total_rare_samples"] >= criteria["min_total_rare_samples"]
        and summary["mean_rare_poisoned_error_rate"] <= criteria["max_mean_rare_poisoned_error_rate"]
        and summary["mean_rare_error_increase"] <= criteria["max_mean_rare_error_increase"]
    )

    return {
        "scope": "synthetic_stream_multiseed_robustness_acceptance_only",
        "seeds": seeds,
        "samples_per_seed": size,
        "poison_interval": poison_interval,
        "rare_abs_feature_threshold": rare_abs_feature,
        "criteria": criteria,
        "summary": summary,
        "runs": runs,
        "passed": passed,
        "performance_gate_established": True,
        "production_qualified": False,
        "saved_weights": False,
        "external_actions": 0,
    }


def require_stream_robustness_acceptance(**kwargs: object) -> dict[str, object]:
    """Return exact acceptance evidence or fail the caller closed."""
    result = evaluate_stream_robustness_multiseed(**kwargs)
    if result["passed"] is not True:
        raise RuntimeError("synthetic stream robustness acceptance failed")
    return result
