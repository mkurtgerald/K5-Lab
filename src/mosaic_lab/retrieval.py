"""Versioned public retrieval facade with per-session checkpoint incarnation binding.

The compatibility core remains non-executing. This facade strengthens checkpoint
continuity so independently constructed sessions cannot become equivalent merely
by presenting the same public identity and cached synthetic evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from secrets import token_hex

from .contracts import token, utc
from .request_ledger import BoundedRequestLedger, RequestLedgerSnapshot
from ._retrieval_core import (
    CheckpointCheck,
    EvidenceRecord,
    EvidenceSource,
    ReadScope,
    RetrievalReceipt,
    RetrievalSession as _CoreRetrievalSession,
    SyntheticEvidenceStore,
    _MAX_CHECKPOINT_RECORDS,
    _clone_record,
    _clone_scope,
    _restore_scope,
    _sha256_digest,
)

__all__ = (
    "CheckpointCheck",
    "EvidenceRecord",
    "EvidenceSource",
    "ReadScope",
    "RetrievalCheckpoint",
    "RetrievalReceipt",
    "RetrievalSession",
    "SyntheticEvidenceStore",
)


@dataclass(frozen=True)
class RetrievalCheckpoint:
    """Read-only checkpoint bound to one concrete session incarnation."""

    session_id: str
    partition: str
    principal_ref: str
    policy_revision: str
    evidence_refs: tuple[str, ...]
    created_at: datetime
    version: str = "3"
    evidence_digests: tuple[str, ...] = ()
    session_incarnation: str = ""

    def __post_init__(self) -> None:
        if self.version != "3":
            raise ValueError("unsupported checkpoint version")
        for value in (
            self.session_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            self.session_incarnation,
        ):
            token(value)
        utc(self.created_at)
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > _MAX_CHECKPOINT_RECORDS:
            raise ValueError("checkpoint evidence refs must be bounded")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("duplicate checkpoint evidence")
        for value in self.evidence_refs:
            token(value)
        if not isinstance(self.evidence_digests, tuple) or len(self.evidence_digests) != len(self.evidence_refs):
            raise ValueError("checkpoint evidence digests must bind every evidence ref")
        for value in self.evidence_digests:
            _sha256_digest(value, field="checkpoint evidence")


def _clone_checkpoint(checkpoint: RetrievalCheckpoint) -> RetrievalCheckpoint:
    return RetrievalCheckpoint(
        session_id=checkpoint.session_id,
        partition=checkpoint.partition,
        principal_ref=checkpoint.principal_ref,
        policy_revision=checkpoint.policy_revision,
        evidence_refs=tuple(checkpoint.evidence_refs),
        created_at=checkpoint.created_at,
        version=checkpoint.version,
        evidence_digests=tuple(checkpoint.evidence_digests),
        session_incarnation=checkpoint.session_incarnation,
    )


@dataclass(frozen=True)
class _RetrievalSessionSnapshot:
    session_id: str
    partition: str
    principal_ref: str
    policy_revision: str
    session_incarnation: str
    max_cache_entries: int
    cache: tuple[tuple[str, EvidenceRecord], ...]
    integrity_failed: bool
    source_active: bool
    lock: object
    source_lock: object
    request_ledger: BoundedRequestLedger
    request_ledger_snapshot: RequestLedgerSnapshot
    request_ledger_lock: object


class RetrievalSession(_CoreRetrievalSession):
    """Bounded retrieval session with non-transferable checkpoint identity."""

    def __init__(
        self,
        *,
        session_id: str,
        partition: str,
        principal_ref: str,
        policy_revision: str,
        max_cache_entries: int = 128,
        max_request_entries: int = 1024,
    ) -> None:
        super().__init__(
            session_id=session_id,
            partition=partition,
            principal_ref=principal_ref,
            policy_revision=policy_revision,
            max_cache_entries=max_cache_entries,
            max_request_entries=max_request_entries,
        )
        self._session_incarnation = token_hex(16)

    def _snapshot_state(self) -> _RetrievalSessionSnapshot:
        with self._lock:
            cache = tuple((record_id, _clone_record(record)) for record_id, record in sorted(self._cache.items()))
        request_ledger = self._request_ledger
        return _RetrievalSessionSnapshot(
            self.session_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            self._session_incarnation,
            self._max_cache_entries,
            cache,
            self._integrity_failed,
            self._source_active,
            self._lock,
            self._source_lock,
            request_ledger,
            request_ledger.snapshot(),
            request_ledger._lock,
        )

    def _matches_snapshot(self, snapshot: _RetrievalSessionSnapshot) -> bool:
        try:
            current_cache = tuple((record_id, _clone_record(record)) for record_id, record in sorted(self._cache.items()))
            request_ledger = self._request_ledger
            return (
                self.session_id == snapshot.session_id
                and self.partition == snapshot.partition
                and self.principal_ref == snapshot.principal_ref
                and self.policy_revision == snapshot.policy_revision
                and self._session_incarnation == snapshot.session_incarnation
                and type(self._max_cache_entries) is int
                and self._max_cache_entries == snapshot.max_cache_entries
                and current_cache == snapshot.cache
                and type(self._integrity_failed) is bool
                and self._integrity_failed is snapshot.integrity_failed
                and type(self._source_active) is bool
                and self._source_active is snapshot.source_active
                and self._lock is snapshot.lock
                and self._source_lock is snapshot.source_lock
                and request_ledger is snapshot.request_ledger
                and request_ledger._lock is snapshot.request_ledger_lock
                and request_ledger.snapshot() == snapshot.request_ledger_snapshot
            )
        except Exception:
            return False

    def _restore_state(self, snapshot: _RetrievalSessionSnapshot) -> None:
        request_ledger = snapshot.request_ledger
        request_ledger._lock = snapshot.request_ledger_lock
        with request_ledger._lock:
            request_ledger._max_entries = snapshot.request_ledger_snapshot.max_entries
            request_ledger._bindings = dict(snapshot.request_ledger_snapshot.bindings)
        self.session_id = snapshot.session_id
        self.partition = snapshot.partition
        self.principal_ref = snapshot.principal_ref
        self.policy_revision = snapshot.policy_revision
        self._session_incarnation = snapshot.session_incarnation
        self._max_cache_entries = snapshot.max_cache_entries
        self._cache = {record_id: _clone_record(record) for record_id, record in snapshot.cache}
        self._integrity_failed = snapshot.integrity_failed
        self._source_active = snapshot.source_active
        self._lock = snapshot.lock
        self._source_lock = snapshot.source_lock
        self._request_ledger = request_ledger

    def create_checkpoint(self, evidence_refs: tuple[str, ...], *, now: datetime) -> RetrievalCheckpoint:
        if not isinstance(evidence_refs, tuple) or len(evidence_refs) > _MAX_CHECKPOINT_RECORDS:
            raise ValueError("checkpoint evidence refs must be bounded")
        if len(set(evidence_refs)) != len(evidence_refs):
            raise ValueError("duplicate checkpoint evidence")
        for record_id in evidence_refs:
            token(record_id)
        with self._lock:
            if self._integrity_failed:
                raise RuntimeError("session_integrity_failure")
            records = tuple(self._cache.get(record_id) for record_id in evidence_refs)
        if any(record is None for record in records):
            raise ValueError("checkpoint cannot reference uncached evidence")
        digests = tuple(record.content_digest for record in records if record is not None)
        return RetrievalCheckpoint(
            self.session_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            evidence_refs,
            utc(now),
            evidence_digests=digests,
            session_incarnation=self._session_incarnation,
        )

    def validate_checkpoint(
        self,
        checkpoint: RetrievalCheckpoint,
        scope: ReadScope,
        *,
        current_policy_revision: str,
        now: datetime,
        max_age_seconds: float = 60.0,
    ) -> CheckpointCheck:
        now = utc(now)
        if (
            isinstance(max_age_seconds, bool)
            or not isinstance(max_age_seconds, (int, float))
            or not isfinite(float(max_age_seconds))
            or max_age_seconds <= 0
        ):
            raise ValueError("max_age_seconds outside bounded limit")
        if self._integrity_failed:
            return CheckpointCheck("denied", "session_integrity_failure", self.session_id)
        if type(checkpoint) is not RetrievalCheckpoint:
            return CheckpointCheck("denied", "invalid_checkpoint", self.session_id)
        try:
            trusted_checkpoint = _clone_checkpoint(checkpoint)
        except Exception:
            return CheckpointCheck("denied", "invalid_checkpoint", self.session_id)
        if type(scope) is not ReadScope:
            return CheckpointCheck("denied", "invalid_scope", self.session_id)
        try:
            trusted_scope = _clone_scope(scope)
        except Exception:
            return CheckpointCheck("denied", "invalid_scope", self.session_id)
        if (
            trusted_checkpoint.session_id != self.session_id
            or trusted_checkpoint.session_incarnation != self._session_incarnation
            or trusted_checkpoint.partition != self.partition
            or trusted_checkpoint.principal_ref != self.principal_ref
        ):
            return CheckpointCheck("denied", "checkpoint_session_mismatch", self.session_id)
        reason = self._scope_reason(trusted_scope, current_policy_revision=current_policy_revision, now=now)
        if reason is not None:
            return CheckpointCheck("denied", reason, self.session_id)
        if trusted_checkpoint.policy_revision != current_policy_revision:
            return CheckpointCheck("denied", "checkpoint_policy_changed", self.session_id)
        checkpoint_age = (now - utc(trusted_checkpoint.created_at)).total_seconds()
        if checkpoint_age < 0:
            return CheckpointCheck("denied", "checkpoint_future", self.session_id)
        if checkpoint_age > float(max_age_seconds):
            return CheckpointCheck("denied", "checkpoint_stale", self.session_id)
        with self._lock:
            records = tuple(self._cache.get(record_id) for record_id in trusted_checkpoint.evidence_refs)
        if any(record is None for record in records):
            return CheckpointCheck("denied", "checkpoint_cache_missing", self.session_id)
        for record_id, expected_digest, record in zip(
            trusted_checkpoint.evidence_refs,
            trusted_checkpoint.evidence_digests,
            records,
            strict=True,
        ):
            if record_id not in trusted_scope.allowed_record_ids:
                return CheckpointCheck("denied", "record_out_of_scope", self.session_id)
            if (
                record is None
                or type(record) is not EvidenceRecord
                or record.partition != self.partition
                or record.record_id != record_id
            ):
                return CheckpointCheck("denied", "checkpoint_binding_invalid", self.session_id)
            try:
                current_digest = record.content_digest
            except Exception:
                return CheckpointCheck("denied", "checkpoint_binding_invalid", self.session_id)
            if current_digest != expected_digest:
                return CheckpointCheck("denied", "checkpoint_evidence_changed", self.session_id)
            evidence_age = (now - utc(record.observed_at)).total_seconds()
            if evidence_age < 0:
                return CheckpointCheck("denied", "checkpoint_evidence_future", self.session_id)
            if evidence_age > float(max_age_seconds):
                return CheckpointCheck("denied", "checkpoint_evidence_stale", self.session_id)
        return CheckpointCheck(
            "accepted_for_read",
            "checkpoint_valid",
            self.session_id,
            trusted_checkpoint.evidence_refs,
        )
