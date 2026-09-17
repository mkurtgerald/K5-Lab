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
FALLBACK_REASONS = frozenset({"predictor_error", "invalid_output", "prohibited_action"})


def _receipt_action(value: object, *, name: str, optional: bool = False) -> int | None:
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer action")
    action = int(value)
    if not 0 <= action < MAX_ACTIONS:
        raise ValueError(f"{name} out of range")
    return action


@dataclass(frozen=True)
class PolicyProposalReceipt:
    proposed_action: int | None
    executed_action: int
    accepted: bool
    fallback_reason: str | None
    authorized: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        proposed = _receipt_action(self.proposed_action, name="proposed_action", optional=True)
        executed = _receipt_action(self.executed_action, name="executed_action")
        if not isinstance(self.accepted, bool):
            raise ValueError("accepted must be boolean")
        if self.version != "1":
            raise ValueError("unsupported policy proposal receipt version")
        if self.authorized is not False:
            raise ValueError("policy proposal receipts cannot grant authorization")
        if type(self.external_actions) is not int or self.external_actions != 0:
            raise ValueError("policy proposal receipts cannot record external actions")

        if self.accepted:
            if self.fallback_reason is not None:
                raise ValueError("accepted proposal cannot have a fallback reason")
            if proposed is None or proposed != executed:
                raise ValueError("accepted proposal must execute the proposed action")
            return

        if self.fallback_reason not in FALLBACK_REASONS:
            raise ValueError("rejected proposal requires a known fallback reason")
        if self.fallback_reason == "prohibited_action":
            if proposed is None or proposed == executed:
                raise ValueError("prohibited proposal must record the rejected action")
        elif proposed is not None:
            raise ValueError("runtime/output fallback cannot claim a proposed action")


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
