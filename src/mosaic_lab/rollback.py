"""Trusted, non-authorizing rollback provenance contracts for synthetic simulation.

These contracts can describe whether a rollback path exists for one exact synthetic
effect and can identify an authoritative rollback result. They do not perform a
rollback, grant permission, or provide external authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import token, utc

_ALLOWED_PROFILE = "delegated_simulation"
_ALLOWED_TERMINAL_STATUS = "verified_complete"
_ALLOWED_ROLLBACK_OUTCOMES = frozenset({"verified_rolled_back", "rollback_failed", "rollback_unknown"})


def _digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class RollbackCapabilityBinding:
    """Trusted immutable claim that one exact synthetic effect has a rollback path."""

    capability_id: str
    session_id: str
    step_id: str
    delivery_id: str
    partition: str
    principal_ref: str
    proposal_digest: str
    policy_revision: str
    state_digest: str
    effect_digest: str
    issued_at: datetime
    expires_at: datetime
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported rollback capability version")
        for value in (
            self.capability_id,
            self.session_id,
            self.step_id,
            self.delivery_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
        ):
            token(value)
        _digest(self.proposal_digest, field="proposal_digest")
        _digest(self.state_digest, field="state_digest")
        _digest(self.effect_digest, field="effect_digest")
        issued = utc(self.issued_at)
        expires = utc(self.expires_at)
        if expires <= issued:
            raise ValueError("rollback capability expiry must follow issue time")


@dataclass(frozen=True)
class RollbackAssessment:
    """Non-authorizing result of validating one trusted rollback capability."""

    status: str
    reason: str
    session_id: str
    step_id: str
    delivery_id: str
    capability_id: str | None = None
    effect_digest: str | None = None
    rollback_available: bool = False
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.status not in {"available_for_simulation", "denied"}:
            raise ValueError("unsupported rollback assessment")
        for value in (self.reason, self.session_id, self.step_id, self.delivery_id):
            token(value)
        if self.capability_id is not None:
            token(self.capability_id)
        if self.effect_digest is not None:
            _digest(self.effect_digest, field="effect_digest")
        if self.status == "available_for_simulation":
            if self.rollback_available is not True or self.capability_id is None or self.effect_digest is None:
                raise ValueError("available rollback assessment requires complete trusted provenance")
        elif self.rollback_available is not False:
            raise ValueError("denied rollback assessment cannot claim availability")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("rollback assessment cannot grant execution authority")
        if self.version != "1":
            raise ValueError("unsupported rollback assessment version")


@dataclass(frozen=True)
class RollbackResultBinding:
    """Trusted immutable identity for an authoritative rollback observation."""

    capability_id: str
    session_id: str
    step_id: str
    delivery_id: str
    result_ref: str
    result_digest: str
    outcome: str
    observed_at: datetime
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported rollback result version")
        for value in (
            self.capability_id,
            self.session_id,
            self.step_id,
            self.delivery_id,
            self.result_ref,
        ):
            token(value)
        _digest(self.result_digest, field="rollback result")
        if self.outcome not in _ALLOWED_ROLLBACK_OUTCOMES:
            raise ValueError("unsupported rollback outcome")
        utc(self.observed_at)


def assess_rollback(
    capability: RollbackCapabilityBinding | None,
    *,
    session_id: str,
    step_id: str,
    delivery_id: str,
    partition: str,
    principal_ref: str,
    proposal_digest: str,
    current_policy_revision: str,
    current_state_digest: str,
    current_profile: str,
    terminal_status: str,
    terminal_effect_digest: str,
    now: datetime,
) -> RollbackAssessment:
    """Validate rollback availability without granting authority or performing an effect."""

    for value in (session_id, step_id, delivery_id, partition, principal_ref, current_policy_revision):
        token(value)
    _digest(proposal_digest, field="proposal_digest")
    _digest(current_state_digest, field="current_state_digest")
    _digest(terminal_effect_digest, field="terminal_effect_digest")
    now = utc(now)

    def denied(reason: str) -> RollbackAssessment:
        return RollbackAssessment(
            status="denied",
            reason=reason,
            session_id=session_id,
            step_id=step_id,
            delivery_id=delivery_id,
        )

    if not isinstance(capability, RollbackCapabilityBinding):
        return denied("rollback_capability_required")
    if current_profile != _ALLOWED_PROFILE:
        return denied("rollback_profile_mismatch")
    if terminal_status != _ALLOWED_TERMINAL_STATUS:
        return denied("rollback_terminal_state_mismatch")
    checks = (
        (capability.session_id != session_id, "rollback_session_mismatch"),
        (capability.step_id != step_id, "rollback_step_mismatch"),
        (capability.delivery_id != delivery_id, "rollback_delivery_mismatch"),
        (capability.partition != partition, "rollback_partition_mismatch"),
        (capability.principal_ref != principal_ref, "rollback_principal_mismatch"),
        (capability.proposal_digest != proposal_digest, "rollback_proposal_mismatch"),
        (capability.policy_revision != current_policy_revision, "rollback_policy_mismatch"),
        (capability.state_digest != current_state_digest, "rollback_state_mismatch"),
        (capability.effect_digest != terminal_effect_digest, "rollback_effect_mismatch"),
        (now < utc(capability.issued_at), "rollback_capability_not_yet_valid"),
        (now >= utc(capability.expires_at), "rollback_capability_expired"),
    )
    for condition, reason in checks:
        if condition:
            return denied(reason)
    return RollbackAssessment(
        status="available_for_simulation",
        reason="trusted_rollback_capability_bound",
        session_id=session_id,
        step_id=step_id,
        delivery_id=delivery_id,
        capability_id=capability.capability_id,
        effect_digest=capability.effect_digest,
        rollback_available=True,
    )
