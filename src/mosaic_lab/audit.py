"""Bounded audit contracts for synthetic/non-executing interaction evidence.

The in-memory buffer is intentionally not durable or tamper-evident. Production
integrations must provide an authoritative durable audit service. This module
stores only opaque identifiers/reason codes and never hidden model reasoning or
free-form secret-bearing detail fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from .contracts import token, utc
from .retrieval import ReadScope

_ALLOWED_PROFILES = frozenset({"read_only", "recommend", "approval_required", "delegated_simulation"})
_ALLOWED_DECISIONS = frozenset({"proposed", "returned", "denied", "abstained", "cancelled", "attempted", "failed"})
_ALLOWED_OUTCOMES = frozenset({
    "proposed",
    "awaiting_approval",
    "denied",
    "cancelled",
    "attempted",
    "verified_complete",
    "failed",
    "outcome_unknown",
    "not_applicable",
})
_MAX_EVIDENCE_REFS = 128
_MAX_APPROVAL_REFS = 4
_MAX_AUDIT_ENTRIES = 4096


def _optional_token(value: str | None, *, field: str) -> None:
    if value is not None:
        try:
            token(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}") from exc


def _sha256_digest(value: str, *, field: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"invalid {field}")


@dataclass(frozen=True)
class AuditEvent:
    event_id: str
    request_id: str
    partition: str
    principal_ref: str
    profile: str
    policy_revision: str
    model_revision: str
    tool_revision: str
    evidence_refs: tuple[str, ...]
    decision: str
    reason: str
    outcome: str
    recorded_at: datetime
    proposal_id: str | None = None
    grant_ref: str | None = None
    approval_ref: str | None = None
    approval_refs: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    reconciliation_binding_version: str | None = None
    reconciliation_delivery_id: str | None = None
    reconciliation_source_ref: str | None = None
    reconciliation_result_ref: str | None = None
    reconciliation_result_digest: str | None = None
    reconciliation_observed_at: datetime | None = None
    version: str = "4"

    def __post_init__(self) -> None:
        if self.version != "4":
            raise ValueError("unsupported audit version")
        for value in (
            self.event_id,
            self.request_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            self.model_revision,
            self.tool_revision,
            self.reason,
        ):
            token(value)
        _optional_token(self.proposal_id, field="proposal_id")
        _optional_token(self.grant_ref, field="grant_ref")
        _optional_token(self.approval_ref, field="approval_ref")
        if (
            not isinstance(self.approval_refs, tuple)
            or len(self.approval_refs) > _MAX_APPROVAL_REFS
            or len(set(self.approval_refs)) != len(self.approval_refs)
        ):
            raise ValueError("invalid audit approval refs")
        for value in self.approval_refs:
            token(value)
        if self.approval_ref is not None and self.approval_refs:
            raise ValueError("ambiguous audit approval identity")
        if self.profile not in _ALLOWED_PROFILES:
            raise ValueError("unsupported audit profile")
        if self.decision not in _ALLOWED_DECISIONS:
            raise ValueError("unsupported audit decision")
        if self.outcome not in _ALLOWED_OUTCOMES:
            raise ValueError("unsupported audit outcome")
        utc(self.recorded_at)
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > _MAX_EVIDENCE_REFS:
            raise ValueError("audit evidence refs must be bounded")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate audit evidence ref")
        for value in self.evidence_refs:
            token(value)
        if not isinstance(self.evidence_digests, tuple) or len(self.evidence_digests) != len(self.evidence_refs):
            raise ValueError("audit evidence digests must bind every evidence ref")
        for value in self.evidence_digests:
            _sha256_digest(value, field="audit evidence")

        reconciliation_values = (
            self.reconciliation_binding_version,
            self.reconciliation_delivery_id,
            self.reconciliation_source_ref,
            self.reconciliation_result_ref,
            self.reconciliation_result_digest,
            self.reconciliation_observed_at,
        )
        has_reconciliation = any(value is not None for value in reconciliation_values)
        has_complete_reconciliation = all(value is not None for value in reconciliation_values)
        if has_reconciliation and not has_complete_reconciliation:
            raise ValueError("partial reconciliation provenance")
        if self.reason == "reconciled" and not has_complete_reconciliation:
            raise ValueError("reconciled audit requires provenance")
        if self.reason != "reconciled" and has_reconciliation:
            raise ValueError("reconciliation provenance only valid for reconciled audit")
        if has_complete_reconciliation:
            token(self.reconciliation_binding_version)
            token(self.reconciliation_delivery_id)
            token(self.reconciliation_source_ref)
            token(self.reconciliation_result_ref)
            _sha256_digest(self.reconciliation_result_digest, field="reconciliation result")
            utc(self.reconciliation_observed_at)

    @property
    def bound_approval_refs(self) -> tuple[str, ...]:
        """Return the exact approval identity tuple carried by this event."""
        if self.approval_refs:
            return self.approval_refs
        if self.approval_ref is not None:
            return (self.approval_ref,)
        return ()


@dataclass(frozen=True)
class AuditRead:
    status: str
    reason: str
    partition: str
    events: tuple[AuditEvent, ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in {"returned", "denied"}:
            raise ValueError("unsupported audit read")
        token(self.reason)
        token(self.partition)
        if not isinstance(self.events, tuple):
            raise ValueError("audit events must be immutable")
        if self.status != "returned" and self.events:
            raise ValueError("denied audit read cannot expose events")
        for item in self.events:
            if not isinstance(item, AuditEvent) or item.partition != self.partition:
                raise ValueError("audit read contains invalid event binding")


class AuditBuffer:
    """Thread-safe bounded local buffer with idempotent event delivery.

    No eviction is performed: capacity exhaustion fails closed. The buffer makes
    no durability or tamper-evidence claim.
    """

    durable = False
    tamper_evident = False

    def __init__(self, *, max_entries: int = 256) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or not 1 <= max_entries <= _MAX_AUDIT_ENTRIES:
            raise ValueError("max_entries outside bounded limit")
        self._max_entries = max_entries
        self._events: list[AuditEvent] = []
        self._by_id: dict[str, AuditEvent] = {}
        self._lock = Lock()

    def append(self, event: AuditEvent) -> bool:
        if not isinstance(event, AuditEvent):
            raise ValueError("audit event required")
        with self._lock:
            existing = self._by_id.get(event.event_id)
            if existing is not None:
                if existing != event:
                    raise ValueError("event identity collision")
                return False
            if len(self._events) >= self._max_entries:
                raise RuntimeError("audit_capacity")
            self._events.append(event)
            self._by_id[event.event_id] = event
            return True

    def snapshot(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def read_partition(
        self,
        partition: str,
        scope: ReadScope,
        *,
        current_policy_revision: str,
        now: datetime,
    ) -> AuditRead:
        token(partition)
        if not isinstance(scope, ReadScope):
            return AuditRead("denied", "audit_invalid_scope", partition)
        token(current_policy_revision)
        now = utc(now)
        if partition != scope.partition:
            return AuditRead("denied", "audit_partition_mismatch", partition)
        if not scope.authenticated:
            return AuditRead("denied", "audit_unauthenticated", partition)
        if scope.policy_revision != current_policy_revision:
            return AuditRead("denied", "audit_policy_context_mismatch", partition)
        if now >= utc(scope.valid_until):
            return AuditRead("denied", "audit_scope_expired", partition)
        with self._lock:
            partition_events = tuple(item for item in self._events if item.partition == partition)
        if any(item.principal_ref != scope.principal_ref for item in partition_events):
            return AuditRead("denied", "audit_principal_mismatch", partition)
        allowed = set(scope.allowed_record_ids)
        if any(any(record_id not in allowed for record_id in item.evidence_refs) for item in partition_events):
            return AuditRead("denied", "audit_evidence_out_of_scope", partition)
        return AuditRead("returned", "audit_returned", partition, partition_events)
