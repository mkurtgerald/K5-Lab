"""Multi-seed synthetic acceptance sweep for the bounded streaming candidate."""
from __future__ import annotations

from math import isfinite

from .stream_quality import evaluate_stream_quality

DEFAULT_SEEDS = (7, 19, 31, 43, 59)
DEFAULT_MARGIN = 0.04
MIN_ANSWERED_RATE = 0.75
MAX_FALSE_RATE = 0.25
MAX_SELECTIVE_MSE = 0.20


def _seeds(values: tuple[int, ...]) -> tuple[int, ...]:
    if not isinstance(values, tuple) or not 2 <= len(values) <= 8:
        raise ValueError("bounded seed tuple required")
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise ValueError("seeds must be integers")
    if len(set(values)) != len(values):
        raise ValueError("seeds must be unique")
    return values


def _margin(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("margin must be numeric")
    parsed = float(value)
    if not isfinite(parsed) or not 0.0 <= parsed < 0.5:
        raise ValueError("margin out of range")
    return parsed


def _required_rate(name: str, value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeError(f"{name} unavailable")
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise RuntimeError(f"{name} out of range")
    return parsed


def evaluate_multi_seed_quality(
    *,
    size: int = 600,
    seeds: tuple[int, ...] = DEFAULT_SEEDS,
    margin: float = DEFAULT_MARGIN,
) -> dict[str, object]:
    """Evaluate one fixed abstention margin across several independent synthetic seeds."""
    seeds = _seeds(seeds)
    margin = _margin(margin)
    runs: list[dict[str, object]] = []
    for seed in seeds:
        result = evaluate_stream_quality(size=size, seed=seed, margins=(margin,))
        row = result["margins"][0]
        answered = _required_rate("answered_rate", row["answered_rate"])
        false_positive = _required_rate(
            "false_positive_rate_answered", row["false_positive_rate_answered"]
        )
        false_negative = _required_rate(
            "false_negative_rate_answered", row["false_negative_rate_answered"]
        )
        selective_mse = _required_rate(
            "selective_mean_squared_score_error", row["selective_mean_squared_score_error"]
        )
        runs.append(
            {
                "seed": seed,
                "answered_rate": answered,
                "false_positive_rate_answered": false_positive,
                "false_negative_rate_answered": false_negative,
                "selective_mean_squared_score_error": selective_mse,
                "python_tracemalloc_peak_bytes": int(row["python_tracemalloc_peak_bytes"]),
            }
        )

    summary = {
        "min_answered_rate": min(float(row["answered_rate"]) for row in runs),
        "max_false_positive_rate_answered": max(
            float(row["false_positive_rate_answered"]) for row in runs
        ),
        "max_false_negative_rate_answered": max(
            float(row["false_negative_rate_answered"]) for row in runs
        ),
        "max_selective_mean_squared_score_error": max(
            float(row["selective_mean_squared_score_error"]) for row in runs
        ),
        "max_python_tracemalloc_peak_bytes": max(
            int(row["python_tracemalloc_peak_bytes"]) for row in runs
        ),
    }
    criteria = {
        "min_answered_rate": MIN_ANSWERED_RATE,
        "max_false_positive_rate_answered": MAX_FALSE_RATE,
        "max_false_negative_rate_answered": MAX_FALSE_RATE,
        "max_selective_mean_squared_score_error": MAX_SELECTIVE_MSE,
    }
    passed = (
        summary["min_answered_rate"] >= MIN_ANSWERED_RATE
        and summary["max_false_positive_rate_answered"] <= MAX_FALSE_RATE
        and summary["max_false_negative_rate_answered"] <= MAX_FALSE_RATE
        and summary["max_selective_mean_squared_score_error"] <= MAX_SELECTIVE_MSE
    )
    return {
        "scope": "synthetic_stream_multiseed_acceptance_only",
        "samples_per_seed": size,
        "seeds": list(seeds),
        "margin": margin,
        "runs": runs,
        "summary": summary,
        "criteria": criteria,
        "passed": passed,
        "python_memory_measurement_includes_native_allocations": False,
        "score_calibration_established": False,
        "production_qualified": False,
        "saved_weights": False,
        "external_actions": 0,
    }
