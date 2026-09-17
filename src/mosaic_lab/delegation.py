"""Bounded, non-executing delegated-simulation contracts.

The module models synthetic effect attempts only. It has no transport, executor,
network access, persistence, or external authority. Trusted state is supplied by
callers and rechecked at every mocked effect boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from threading import Lock

from .contracts import token, utc

_MAX_STEPS = 64
_MAX_DURATION_SECONDS = 300.0
_MAX_RATE_PER_MINUTE = 120
_MAX_TRACKED_DELIVERIES = 4096
_ALLOWED_OUTCOMES = frozenset({"verified_complete", "failed", "outcome_unknown"})


def _digest(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class DelegationGrant:
    """Trusted grant for one bounded synthetic simulation session."""

    grant_id: str
    principal_ref: str
    partition: str
    proposal_digest: str
    policy_revision: str
    state_digest: str
    allowed_actions: tuple[str, ...]
    allowed_targets: tuple[str, ...]
    granted_at: datetime
    expires_at: datetime
    max_steps: int
    max_duration_seconds: float
    max_actions_per_minute: int
    revoked: bool = False
    profile: str = "delegated_simulation"
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported delegation version")
        if self.profile != "delegated_simulation":
            raise ValueError("delegation grant requires delegated_simulation profile")
        for value in (
            self.grant_id,
            self.principal_ref,
            self.partition,
            self.policy_revision,
        ):
            token(value)
        _digest(self.proposal_digest, field="proposal_digest")
        _digest(self.state_digest, field="state_digest")
        for values, field in (
            (self.allowed_actions, "allowed_actions"),
            (self.allowed_targets, "allowed_targets"),
        ):
            if not isinstance(values, tuple) or not values or len(values) > 64:
                raise ValueError(f"{field} must be a non-empty bounded tuple")
            if len(set(values)) != len(values):
                raise ValueError(f"{field} contains duplicates")
            for value in values:
                token(value)
        granted = utc(self.granted_at)
        expires = utc(self.expires_at)
        if expires <= granted:
            raise ValueError("delegation expiry must follow grant time")
        if not isinstance(self.revoked, bool):
            raise ValueError("revoked must be boolean")
        if isinstance(self.max_steps, bool) or not isinstance(self.max_steps, int) or not 1 <= self.max_steps <= _MAX_STEPS:
            raise ValueError("max_steps outside bounded limit")
        if (
            isinstance(self.max_duration_seconds, bool)
            or not isinstance(self.max_duration_seconds, (int, float))
            or not isfinite(self.max_duration_seconds)
            or not 0 < float(self.max_duration_seconds) <= _MAX_DURATION_SECONDS
        ):
            raise ValueError("max_duration_seconds outside bounded limit")
        if (
            isinstance(self.max_actions_per_minute, bool)
            or not isinstance(self.max_actions_per_minute, int)
            or not 1 <= self.max_actions_per_minute <= _MAX_RATE_PER_MINUTE
        ):
            raise ValueError("max_actions_per_minute outside bounded limit")


@dataclass(frozen=True)
class SimulationStep:
    step_id: str
    delivery_id: str
    action_ref: str
    target_ref: str
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported step version")
        for value in (self.step_id, self.delivery_id, self.action_ref, self.target_ref):
            token(value)


@dataclass(frozen=True)
class SimulationReceipt:
    status: str
    reason: str
    session_id: str
    step_id: str
    delivery_id: str
    step_index: int
    mocked_effects: int
    completed_steps: int
    failed_steps: int
    unknown_steps: int
    rollback_available: bool
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.status not in {
            "denied",
            "cancelled",
            "budget_exhausted",
            "rate_limited",
            "reconciliation_required",
            "verified_complete",
            "failed",
            "outcome_unknown",
        }:
            raise ValueError("unsupported simulation status")
        for value in (self.reason, self.session_id, self.step_id, self.delivery_id):
            token(value)
        for value, field in (
            (self.step_index, "step_index"),
            (self.mocked_effects, "mocked_effects"),
            (self.completed_steps, "completed_steps"),
            (self.failed_steps, "failed_steps"),
            (self.unknown_steps, "unknown_steps"),
            (self.external_actions, "external_actions"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if self.mocked_effects not in {0, 1}:
            raise ValueError("receipt may record at most one mocked effect")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("public simulation receipts cannot grant execution authority")
        if not isinstance(self.rollback_available, bool):
            raise ValueError("rollback_available must be boolean")
        if self.version != "1":
            raise ValueError("unsupported simulation receipt version")


class DelegatedSimulation:
    """Thread-safe bounded synthetic session with atomic replay protection."""

    def __init__(
        self,
        grant: DelegationGrant,
        *,
        session_id: str,
        started_at: datetime,
        max_tracked_deliveries: int = 256,
    ) -> None:
        if not isinstance(grant, DelegationGrant):
            raise ValueError("trusted delegation grant required")
        token(session_id)
        started = utc(started_at)
        if started < utc(grant.granted_at) or started >= utc(grant.expires_at):
            raise ValueError("session start outside delegation lifetime")
        if isinstance(max_tracked_deliveries, bool) or not isinstance(max_tracked_deliveries, int):
            raise ValueError("max_tracked_deliveries must be integer")
        if not 1 <= max_tracked_deliveries <= _MAX_TRACKED_DELIVERIES:
            raise ValueError("max_tracked_deliveries outside bounded limit")
        self._grant = grant
        self._session_id = session_id
        self._started_at = started
        self._max_tracked_deliveries = max_tracked_deliveries
        self._receipts: dict[str, SimulationReceipt] = {}
        self._step_receipts: dict[str, SimulationReceipt] = {}
        self._effect_times: list[datetime] = []
        self._lock = Lock()

    def _counts(self) -> tuple[int, int, int]:
        values = self._step_receipts.values()
        complete = sum(item.status == "verified_complete" for item in values)
        failed = sum(item.status == "failed" for item in values)
        unknown = sum(item.status == "outcome_unknown" for item in values)
        return complete, failed, unknown

    def _receipt(
        self,
        *,
        status: str,
        reason: str,
        step: SimulationStep,
        step_index: int,
        mocked_effects: int = 0,
        rollback_available: bool = False,
    ) -> SimulationReceipt:
        complete, failed, unknown = self._counts()
        return SimulationReceipt(
            status=status,
            reason=reason,
            session_id=self._session_id,
            step_id=step.step_id,
            delivery_id=step.delivery_id,
            step_index=step_index,
            mocked_effects=mocked_effects,
            completed_steps=complete,
            failed_steps=failed,
            unknown_steps=unknown,
            rollback_available=rollback_available,
        )

    def attempt_step(
        self,
        step: SimulationStep,
        *,
        now: datetime,
        current_policy_revision: str,
        current_state_digest: str,
        current_profile: str,
        authority_available: bool,
        cancelled: bool,
        grant_revoked: bool,
        mocked_outcome: str,
        reversible: bool,
    ) -> SimulationReceipt:
        if not isinstance(step, SimulationStep):
            raise ValueError("trusted simulation step required")
        now = utc(now)
        token(current_policy_revision)
        _digest(current_state_digest, field="current_state_digest")
        if current_profile not in {"read_only", "recommend", "approval_required", "delegated_simulation"}:
            raise ValueError("unsupported current profile")
        if not isinstance(authority_available, bool) or not isinstance(cancelled, bool) or not isinstance(grant_revoked, bool):
            raise ValueError("authority and cancellation flags must be boolean")
        if mocked_outcome not in _ALLOWED_OUTCOMES:
            raise ValueError("unsupported mocked outcome")
        if not isinstance(reversible, bool):
            raise ValueError("reversible must be boolean")

        with self._lock:
            existing = self._receipts.get(step.delivery_id)
            if existing is not None:
                return existing

            prior_step = self._step_receipts.get(step.step_id)
            next_index = len(self._step_receipts) + 1
            if prior_step is not None:
                if prior_step.status == "outcome_unknown":
                    return self._receipt(
                        status="reconciliation_required",
                        reason="ambiguous_prior_outcome",
                        step=step,
                        step_index=prior_step.step_index,
                    )
                return self._receipt(
                    status="denied",
                    reason="duplicate_step",
                    step=step,
                    step_index=prior_step.step_index,
                )

            if len(self._receipts) >= self._max_tracked_deliveries:
                return self._receipt(
                    status="denied",
                    reason="replay_ledger_capacity",
                    step=step,
                    step_index=next_index,
                )
            if not authority_available:
                return self._receipt(status="denied", reason="authority_unavailable", step=step, step_index=next_index)
            if cancelled:
                return self._receipt(status="cancelled", reason="session_cancelled", step=step, step_index=next_index)
            if self._grant.revoked or grant_revoked:
                return self._receipt(status="denied", reason="grant_revoked", step=step, step_index=next_index)
            if current_profile != self._grant.profile:
                return self._receipt(status="denied", reason="profile_changed", step=step, step_index=next_index)
            if current_policy_revision != self._grant.policy_revision:
                return self._receipt(status="denied", reason="policy_changed", step=step, step_index=next_index)
            if current_state_digest != self._grant.state_digest:
                return self._receipt(status="denied", reason="state_changed", step=step, step_index=next_index)
            if now >= utc(self._grant.expires_at):
                return self._receipt(status="denied", reason="grant_expired", step=step, step_index=next_index)
            elapsed = (now - self._started_at).total_seconds()
            if elapsed < 0:
                return self._receipt(status="denied", reason="time_reversal", step=step, step_index=next_index)
            if elapsed > float(self._grant.max_duration_seconds):
                return self._receipt(status="budget_exhausted", reason="time_budget", step=step, step_index=next_index)
            if len(self._step_receipts) >= self._grant.max_steps:
                return self._receipt(status="budget_exhausted", reason="step_budget", step=step, step_index=next_index)
            if step.action_ref not in self._grant.allowed_actions:
                return self._receipt(status="denied", reason="action_out_of_scope", step=step, step_index=next_index)
            if step.target_ref not in self._grant.allowed_targets:
                return self._receipt(status="denied", reason="target_out_of_scope", step=step, step_index=next_index)

            cutoff = now - timedelta(seconds=60)
            self._effect_times = [item for item in self._effect_times if item > cutoff]
            if len(self._effect_times) >= self._grant.max_actions_per_minute:
                return self._receipt(status="rate_limited", reason="rate_budget", step=step, step_index=next_index)

            self._effect_times.append(now)
            receipt = self._receipt(
                status=mocked_outcome,
                reason="mocked_effect_recorded",
                step=step,
                step_index=next_index,
                mocked_effects=1,
                rollback_available=reversible and mocked_outcome == "verified_complete",
            )
            self._step_receipts[step.step_id] = receipt
            complete, failed, unknown = self._counts()
            receipt = replace(
                receipt,
                completed_steps=complete,
                failed_steps=failed,
                unknown_steps=unknown,
            )
            self._step_receipts[step.step_id] = receipt
            self._receipts[step.delivery_id] = receipt
            return receipt

    def reconcile(
        self,
        step_id: str,
        *,
        authoritative_outcome: str,
        reversible: bool,
    ) -> SimulationReceipt:
        token(step_id)
        if authoritative_outcome not in {"verified_complete", "failed"}:
            raise ValueError("reconciliation requires a terminal authoritative outcome")
        if not isinstance(reversible, bool):
            raise ValueError("reversible must be boolean")
        with self._lock:
            prior = self._step_receipts.get(step_id)
            if prior is None:
                raise ValueError("cannot reconcile an unknown step")
            if prior.status != "outcome_unknown":
                return prior
            resolved = replace(
                prior,
                status=authoritative_outcome,
                reason="reconciled",
                mocked_effects=0,
                rollback_available=reversible and authoritative_outcome == "verified_complete",
            )
            self._step_receipts[step_id] = resolved
            complete, failed, unknown = self._counts()
            resolved = replace(
                resolved,
                completed_steps=complete,
                failed_steps=failed,
                unknown_steps=unknown,
            )
            self._step_receipts[step_id] = resolved
            self._receipts[resolved.delivery_id] = resolved
            return resolved
