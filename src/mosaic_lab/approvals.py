"""Trusted approval contracts for non-executing simulation only.

This module models approval binding and single-use semantics without granting
external authority. It intentionally has no transport, persistence, executor,
or privilege-escalation surface. A production integration must replace the
in-memory ledger with a durable authoritative service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Iterable

from .contracts import token, utc

_ALLOWED_PROFILES = frozenset({"approval_required", "delegated_simulation"})
_MAX_APPROVALS = 4
_MAX_LEDGER_ENTRIES = 4096


def _digest(value: str, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class ApprovalRecord:
    """Trusted server-side approval record bound to one exact proposal state."""

    approval_id: str
    approver_ref: str
    partition: str
    proposal_digest: str
    policy_revision: str
    state_digest: str
    profile: str
    granted_at: datetime
    expires_at: datetime
    revoked: bool = False
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported approval version")
        for value in (
            self.approval_id,
            self.approver_ref,
            self.partition,
            self.policy_revision,
        ):
            token(value)
        _digest(self.proposal_digest, field="proposal_digest")
        _digest(self.state_digest, field="state_digest")
        if self.profile not in _ALLOWED_PROFILES:
            raise ValueError("unsupported approval profile")
        if not isinstance(self.revoked, bool):
            raise ValueError("revoked must be boolean")
        granted = utc(self.granted_at)
        expires = utc(self.expires_at)
        if expires <= granted:
            raise ValueError("approval expiry must follow grant time")


@dataclass(frozen=True)
class ApprovalCheck:
    """Non-authorizing result of validating trusted approval records."""

    status: str
    reason: str
    proposal_digest: str
    consumed_approval_ids: tuple[str, ...] = ()
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.status not in {"accepted_for_simulation", "awaiting_approval", "denied"}:
            raise ValueError("unsupported approval-check status")
        token(self.reason)
        _digest(self.proposal_digest, field="proposal_digest")
        if len(set(self.consumed_approval_ids)) != len(self.consumed_approval_ids):
            raise ValueError("duplicate consumed approval identity")
        for approval_id in self.consumed_approval_ids:
            token(approval_id)
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("public approval checks cannot grant execution authority")
        if self.version != "1":
            raise ValueError("unsupported approval-check version")


class ApprovalUseLedger:
    """Bounded atomic replay guard for deterministic simulation tests.

    The ledger never evicts consumed identities because eviction could permit a
    replay. Capacity exhaustion therefore fails closed. This is deliberately
    not a durable authorization store.
    """

    def __init__(self, *, max_entries: int = 256) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise ValueError("max_entries must be an integer")
        if not 1 <= max_entries <= _MAX_LEDGER_ENTRIES:
            raise ValueError("max_entries outside bounded limit")
        self._max_entries = max_entries
        self._used: set[str] = set()
        self._lock = Lock()

    @property
    def used_count(self) -> int:
        with self._lock:
            return len(self._used)

    def validate_and_consume(
        self,
        records: Iterable[ApprovalRecord],
        *,
        partition: str,
        proposal_digest: str,
        current_policy_revision: str,
        current_state_digest: str,
        current_profile: str,
        now: datetime,
        required_approvals: int = 1,
    ) -> ApprovalCheck:
        token(partition)
        _digest(proposal_digest, field="proposal_digest")
        token(current_policy_revision)
        _digest(current_state_digest, field="current_state_digest")
        if current_profile not in _ALLOWED_PROFILES:
            return ApprovalCheck(
                status="denied",
                reason="profile_reduced",
                proposal_digest=proposal_digest,
            )
        now = utc(now)
        if isinstance(required_approvals, bool) or not isinstance(required_approvals, int):
            raise ValueError("required_approvals must be an integer")
        if not 1 <= required_approvals <= _MAX_APPROVALS:
            raise ValueError("required_approvals outside bounded limit")

        if isinstance(records, (str, bytes)):
            raise ValueError("approval records must be trusted record objects")
        try:
            iterator = iter(records)
        except TypeError as exc:
            raise ValueError("approval records must be a bounded iterable") from exc
        items_list: list[ApprovalRecord] = []
        try:
            for _ in range(required_approvals + 1):
                items_list.append(next(iterator))
        except StopIteration:
            pass
        except Exception as exc:
            raise ValueError("approval record iteration failed") from exc
        items = tuple(items_list)
        if len(items) < required_approvals:
            return ApprovalCheck(
                status="awaiting_approval",
                reason="insufficient_approvals",
                proposal_digest=proposal_digest,
            )
        if len(items) > required_approvals:
            return ApprovalCheck(
                status="denied",
                reason="unexpected_approval_count",
                proposal_digest=proposal_digest,
            )
        if any(not isinstance(item, ApprovalRecord) for item in items):
            raise ValueError("approval records must be trusted record objects")

        approval_ids = tuple(item.approval_id for item in items)
        approvers = tuple(item.approver_ref for item in items)
        if len(set(approval_ids)) != len(approval_ids):
            return ApprovalCheck(status="denied", reason="duplicate_approval", proposal_digest=proposal_digest)
        if len(set(approvers)) != len(approvers):
            return ApprovalCheck(status="denied", reason="duplicate_approver", proposal_digest=proposal_digest)

        for item in items:
            if item.revoked:
                return ApprovalCheck(status="denied", reason="approval_revoked", proposal_digest=proposal_digest)
            if item.partition != partition:
                return ApprovalCheck(status="denied", reason="partition_mismatch", proposal_digest=proposal_digest)
            if item.proposal_digest != proposal_digest:
                return ApprovalCheck(status="denied", reason="proposal_changed", proposal_digest=proposal_digest)
            if item.policy_revision != current_policy_revision:
                return ApprovalCheck(status="denied", reason="policy_changed", proposal_digest=proposal_digest)
            if item.state_digest != current_state_digest:
                return ApprovalCheck(status="denied", reason="state_changed", proposal_digest=proposal_digest)
            if item.profile != current_profile:
                return ApprovalCheck(status="denied", reason="profile_changed", proposal_digest=proposal_digest)
            if utc(item.granted_at) > now:
                return ApprovalCheck(status="denied", reason="future_approval", proposal_digest=proposal_digest)
            if now >= utc(item.expires_at):
                return ApprovalCheck(status="denied", reason="approval_expired", proposal_digest=proposal_digest)

        with self._lock:
            if any(approval_id in self._used for approval_id in approval_ids):
                return ApprovalCheck(status="denied", reason="approval_reused", proposal_digest=proposal_digest)
            if len(self._used) + len(approval_ids) > self._max_entries:
                return ApprovalCheck(status="denied", reason="ledger_capacity", proposal_digest=proposal_digest)
            self._used.update(approval_ids)

        return ApprovalCheck(
            status="accepted_for_simulation",
            reason="trusted_approval_bound",
            proposal_digest=proposal_digest,
            consumed_approval_ids=approval_ids,
        )
