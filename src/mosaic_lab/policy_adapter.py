"""Fail-closed adapter for learned-policy proposal outputs.

This module deliberately has no training, persistence, network, or execution path.
It normalizes an in-process predictor result into a bounded proposal receipt and
falls back to a caller-supplied safe action on any prediction/output failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

MAX_OBSERVATION_ITEMS = 64
MAX_ACTIONS = 32


@dataclass(frozen=True)
class PolicyProposalReceipt:
    proposed_action: int | None
    executed_action: int
    accepted: bool
    fallback_reason: str | None
    authorized: bool = False
    external_actions: int = 0


def _bounded_observation(value: object) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 1 or not 1 <= array.size <= MAX_OBSERVATION_ITEMS:
        raise ValueError("observation must be a bounded one-dimensional vector")
    if not np.issubdtype(array.dtype, np.number):
        raise ValueError("observation must be numeric")
    array = array.astype(np.float32, copy=True)
    if not np.all(np.isfinite(array)):
        raise ValueError("observation must be finite")
    return array


def _bounded_action_count(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_ACTIONS:
        raise ValueError("action_count out of range")
    return value


def _normalize_action(value: object, *, action_count: int) -> int:
    if isinstance(value, np.ndarray):
        if value.shape == ():
            value = value.item()
        elif value.shape == (1,):
            value = value[0].item()
        else:
            raise ValueError("policy output must contain exactly one action")
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError("policy action must be an integer")
    action = int(value)
    if not 0 <= action < action_count:
        raise ValueError("policy action out of range")
    return action


def _allowed_actions(values: tuple[int, ...], *, action_count: int) -> tuple[int, ...]:
    if not isinstance(values, tuple) or not values or len(values) > action_count:
        raise ValueError("allowed_actions must be a non-empty bounded tuple")
    parsed = tuple(_normalize_action(value, action_count=action_count) for value in values)
    if len(set(parsed)) != len(parsed):
        raise ValueError("allowed_actions must be unique")
    return parsed


def evaluate_policy_proposal(
    predictor: Callable[[np.ndarray], object],
    observation: object,
    *,
    allowed_actions: tuple[int, ...],
    action_count: int,
    fallback_action: int = 0,
) -> PolicyProposalReceipt:
    """Evaluate one proposal without granting authority or external execution.

    Configuration and observation errors are caller errors and raise before the
    predictor is invoked. Predictor/runtime/output failures instead produce a
    safe fallback receipt so a learned component cannot escape the caller's hard
    action boundary.
    """

    count = _bounded_action_count(action_count)
    allowed = _allowed_actions(allowed_actions, action_count=count)
    fallback = _normalize_action(fallback_action, action_count=count)
    if fallback not in allowed:
        raise ValueError("fallback_action must be allowed")
    bounded = _bounded_observation(observation)

    try:
        raw_action = predictor(bounded.copy())
    except Exception:
        return PolicyProposalReceipt(None, fallback, False, "predictor_error")

    try:
        proposed = _normalize_action(raw_action, action_count=count)
    except ValueError:
        return PolicyProposalReceipt(None, fallback, False, "invalid_output")

    if proposed not in allowed:
        return PolicyProposalReceipt(proposed, fallback, False, "prohibited_action")
    return PolicyProposalReceipt(proposed, proposed, True, None)
