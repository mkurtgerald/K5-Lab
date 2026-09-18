"""Partition-safe, non-executing retrieval/session/checkpoint contracts.

Retrieved text and source objects are untrusted data. Trusted scope is supplied
separately by the caller and is revalidated before lookup, after source return,
and immediately before evidence is returned. This module has no network client,
external executor, durable store, or authority-granting behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isfinite
from threading import Lock, RLock
from typing import Protocol

from .contracts import token, utc

_ALLOWED_PROFILES = frozenset({"read_only", "recommend", "approval_required", "delegated_simulation"})
_ALLOWED_ORIGINS = frozenset({"record", "retrieved_text", "message", "tool_result"})
_MAX_TEXT_CHARS = 4096
_MAX_ALLOWED_RECORDS = 128
_MAX_CACHE_ENTRIES = 4096
_MAX_STORE_ENTRIES = 4096
_MAX_CHECKPOINT_RECORDS = 128


def _bounded_text(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > _MAX_TEXT_CHARS:
        raise ValueError(f"{field} outside bounded text limit")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{field} contains unsupported control characters")
    return value


def _sha256_digest(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field} requires lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class EvidenceRecord:
    """Untrusted evidence payload with opaque identity and bounded content."""

    partition: str
    record_id: str
    source_ref: str
    observed_at: datetime
    text: str
    origin: str = "record"
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported evidence version")
        for value in (self.partition, self.record_id, self.source_ref):
            token(value)
        utc(self.observed_at)
        _bounded_text(self.text, field="evidence text")
        if self.origin not in _ALLOWED_ORIGINS:
            raise ValueError("unsupported evidence origin")

    @property
    def content_digest(self) -> str:
        encoded = "\x1f".join(
            (
                self.version,
                self.partition,
                self.record_id,
                self.source_ref,
                utc(self.observed_at).isoformat(),
                self.origin,
                self.text,
            )
        ).encode()
        return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ReadScope:
    """Trusted read scope supplied independently of retrieved/model text."""

    partition: str
    principal_ref: str
    profile: str
    policy_revision: str
    allowed_record_ids: tuple[str, ...]
    valid_until: datetime
    authenticated: bool = True
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported read-scope version")
        for value in (self.partition, self.principal_ref, self.policy_revision):
            token(value)
        if self.profile not in _ALLOWED_PROFILES:
            raise ValueError("unsupported read profile")
        if not isinstance(self.authenticated, bool):
            raise ValueError("authenticated must be boolean")
        utc(self.valid_until)
        if not isinstance(self.allowed_record_ids, tuple) or len(self.allowed_record_ids) > _MAX_ALLOWED_RECORDS:
            raise ValueError("allowed_record_ids must be a bounded tuple")
        if len(set(self.allowed_record_ids)) != len(self.allowed_record_ids):
            raise ValueError("duplicate allowed record")
        for record_id in self.allowed_record_ids:
            token(record_id)


@dataclass(frozen=True)
class RetrievalReceipt:
    status: str
    reason: str
    request_id: str
    partition: str
    record_id: str
    text: str = ""
    content_digest: str = ""
    observed_at: datetime | None = None
    cached: bool = False
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in {"returned", "denied", "abstain", "unavailable"}:
            raise ValueError("unsupported retrieval receipt")
        for value in (self.reason, self.request_id, self.partition, self.record_id):
            token(value)
        if not isinstance(self.cached, bool):
            raise ValueError("cached must be boolean")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("retrieval cannot grant execution authority")
        if self.status == "returned":
            _bounded_text(self.text, field="returned text")
            if len(self.content_digest) != 64 or any(char not in "0123456789abcdef" for char in self.content_digest):
                raise ValueError("returned evidence requires sha256 digest")
            if self.observed_at is None:
                raise ValueError("returned evidence requires observed_at")
            utc(self.observed_at)
        elif self.text or self.content_digest or self.observed_at is not None:
            raise ValueError("non-returned receipt cannot expose evidence")


@dataclass(frozen=True)
class RetrievalCheckpoint:
    session_id: str
    partition: str
    principal_ref: str
    policy_revision: str
    evidence_refs: tuple[str, ...]
    created_at: datetime
    version: str = "2"
    evidence_digests: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.version != "2":
            raise ValueError("unsupported checkpoint version")
        for value in (self.session_id, self.partition, self.principal_ref, self.policy_revision):
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


@dataclass(frozen=True)
class CheckpointCheck:
    status: str
    reason: str
    session_id: str
    evidence_refs: tuple[str, ...] = ()
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in {"accepted_for_read", "denied"}:
            raise ValueError("unsupported checkpoint check")
        token(self.reason)
        token(self.session_id)
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("checkpoint validation cannot grant execution authority")
        for value in self.evidence_refs:
            token(value)


class EvidenceSource(Protocol):
    def get(self, partition: str, record_id: str) -> EvidenceRecord | None: ...


def _clone_record(record: EvidenceRecord) -> EvidenceRecord:
    return EvidenceRecord(
        partition=record.partition,
        record_id=record.record_id,
        source_ref=record.source_ref,
        observed_at=record.observed_at,
        text=record.text,
        origin=record.origin,
        version=record.version,
    )


def _clone_scope(scope: ReadScope) -> ReadScope:
    return ReadScope(
        partition=scope.partition,
        principal_ref=scope.principal_ref,
        profile=scope.profile,
        policy_revision=scope.policy_revision,
        allowed_record_ids=tuple(scope.allowed_record_ids),
        valid_until=scope.valid_until,
        authenticated=scope.authenticated,
        version=scope.version,
    )


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
    )


def _restore_scope(scope: ReadScope, trusted: ReadScope) -> None:
    for field in (
        "partition",
        "principal_ref",
        "profile",
        "policy_revision",
        "allowed_record_ids",
        "valid_until",
        "authenticated",
        "version",
    ):
        object.__setattr__(scope, field, getattr(trusted, field))


@dataclass(frozen=True)
class _RetrievalSessionSnapshot:
    session_id: str
    partition: str
    principal_ref: str
    policy_revision: str
    max_cache_entries: int
    cache: tuple[tuple[str, EvidenceRecord], ...]
    integrity_failed: bool
    source_active: bool
    lock: object
    source_lock: object


class SyntheticEvidenceStore:
    """Bounded in-memory synthetic store; not a production persistence layer."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or not 1 <= max_entries <= _MAX_STORE_ENTRIES:
            raise ValueError("max_entries outside bounded limit")
        self._max_entries = max_entries
        self._records: dict[tuple[str, str], EvidenceRecord] = {}
        self._read_count = 0
        self._lock = Lock()

    @property
    def read_count(self) -> int:
        with self._lock:
            return self._read_count

    def add(self, record: EvidenceRecord) -> None:
        if not isinstance(record, EvidenceRecord):
            raise ValueError("evidence record required")
        key = (record.partition, record.record_id)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                if existing != record:
                    raise ValueError("record identity collision")
                return
            if len(self._records) >= self._max_entries:
                raise RuntimeError("store_capacity")
            self._records[key] = record

    def get(self, partition: str, record_id: str) -> EvidenceRecord | None:
        token(partition)
        token(record_id)
        with self._lock:
            self._read_count += 1
            return self._records.get((partition, record_id))


class RetrievalSession:
    """Bounded session and cache bound to one principal, partition and policy revision."""

    def __init__(
        self,
        *,
        session_id: str,
        partition: str,
        principal_ref: str,
        policy_revision: str,
        max_cache_entries: int = 128,
    ) -> None:
        for value in (session_id, partition, principal_ref, policy_revision):
            token(value)
        if isinstance(max_cache_entries, bool) or not isinstance(max_cache_entries, int) or not 1 <= max_cache_entries <= _MAX_CACHE_ENTRIES:
            raise ValueError("max_cache_entries outside bounded limit")
        self.session_id = session_id
        self.partition = partition
        self.principal_ref = principal_ref
        self.policy_revision = policy_revision
        self._max_cache_entries = max_cache_entries
        self._cache: dict[str, EvidenceRecord] = {}
        self._integrity_failed = False
        self._source_active = False
        self._lock = Lock()
        self._source_lock = RLock()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)

    def _snapshot_state(self) -> _RetrievalSessionSnapshot:
        with self._lock:
            cache = tuple((record_id, _clone_record(record)) for record_id, record in sorted(self._cache.items()))
        return _RetrievalSessionSnapshot(
            self.session_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            self._max_cache_entries,
            cache,
            self._integrity_failed,
            self._source_active,
            self._lock,
            self._source_lock,
        )

    def _matches_snapshot(self, snapshot: _RetrievalSessionSnapshot) -> bool:
        try:
            current_cache = tuple((record_id, _clone_record(record)) for record_id, record in sorted(self._cache.items()))
            return (
                self.session_id == snapshot.session_id
                and self.partition == snapshot.partition
                and self.principal_ref == snapshot.principal_ref
                and self.policy_revision == snapshot.policy_revision
                and type(self._max_cache_entries) is int
                and self._max_cache_entries == snapshot.max_cache_entries
                and current_cache == snapshot.cache
                and type(self._integrity_failed) is bool
                and self._integrity_failed is snapshot.integrity_failed
                and type(self._source_active) is bool
                and self._source_active is snapshot.source_active
                and self._lock is snapshot.lock
                and self._source_lock is snapshot.source_lock
            )
        except Exception:
            return False

    def _restore_state(self, snapshot: _RetrievalSessionSnapshot) -> None:
        self.session_id = snapshot.session_id
        self.partition = snapshot.partition
        self.principal_ref = snapshot.principal_ref
        self.policy_revision = snapshot.policy_revision
        self._max_cache_entries = snapshot.max_cache_entries
        self._cache = {record_id: _clone_record(record) for record_id, record in snapshot.cache}
        self._integrity_failed = snapshot.integrity_failed
        self._source_active = snapshot.source_active
        self._lock = snapshot.lock
        self._source_lock = snapshot.source_lock

    def _scope_reason(self, scope: ReadScope, *, current_policy_revision: str, now: datetime) -> str | None:
        if self._integrity_failed:
            return "session_integrity_failure"
        if not isinstance(scope, ReadScope):
            return "invalid_scope"
        token(current_policy_revision)
        now = utc(now)
        if scope.partition != self.partition or scope.principal_ref != self.principal_ref:
            return "session_scope_mismatch"
        if not scope.authenticated:
            return "unauthenticated"
        if scope.policy_revision != current_policy_revision:
            return "policy_context_mismatch"
        if current_policy_revision != self.policy_revision:
            return "session_policy_changed"
        if now >= utc(scope.valid_until):
            return "scope_expired"
        return None

    def _receipt(self, request_id: str, record_id: str, status: str, reason: str, *, record: EvidenceRecord | None = None, cached: bool = False) -> RetrievalReceipt:
        if record is None:
            return RetrievalReceipt(status, reason, request_id, self.partition, record_id)
        return RetrievalReceipt(
            status,
            reason,
            request_id,
            self.partition,
            record_id,
            record.text,
            record.content_digest,
            record.observed_at,
            cached,
        )

    def retrieve(
        self,
        request_id: str,
        record_id: str,
        source: EvidenceSource,
        scope: ReadScope,
        *,
        current_policy_revision: str,
        now: datetime,
        max_age_seconds: float = 60.0,
    ) -> RetrievalReceipt:
        token(request_id)
        token(record_id)
        now = utc(now)
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)) or not isfinite(float(max_age_seconds)) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds outside bounded limit")
        if type(scope) is not ReadScope:
            return self._receipt(request_id, record_id, "denied", "invalid_scope")
        try:
            trusted_scope = _clone_scope(scope)
        except Exception:
            return self._receipt(request_id, record_id, "denied", "invalid_scope")

        reason = self._scope_reason(trusted_scope, current_policy_revision=current_policy_revision, now=now)
        if reason is not None:
            return self._receipt(request_id, record_id, "denied", reason)
        if record_id not in trusted_scope.allowed_record_ids:
            return self._receipt(request_id, record_id, "denied", "record_out_of_scope")

        with self._source_lock:
            if self._source_active:
                return self._receipt(request_id, record_id, "denied", "source_reentry")
            with self._lock:
                if self._integrity_failed:
                    return self._receipt(request_id, record_id, "denied", "session_integrity_failure")
                record = self._cache.get(record_id)
                if record is None and len(self._cache) >= self._max_cache_entries:
                    return self._receipt(request_id, record_id, "denied", "cache_capacity")
            cached = record is not None
            if record is None:
                self._source_active = True
                snapshot = self._snapshot_state()
                try:
                    record = source.get(snapshot.partition, record_id)
                except Exception:
                    session_ok = self._matches_snapshot(snapshot)
                    scope_ok = scope == trusted_scope
                    if not session_ok or not scope_ok:
                        if not session_ok:
                            self._restore_state(snapshot)
                        if not scope_ok:
                            try:
                                _restore_scope(scope, trusted_scope)
                            except Exception:
                                pass
                        self._source_active = False
                        self._integrity_failed = True
                        return self._receipt(request_id, record_id, "denied", "session_integrity_failure")
                    self._source_active = False
                    return self._receipt(request_id, record_id, "unavailable", "source_unavailable")
                session_ok = self._matches_snapshot(snapshot)
                scope_ok = scope == trusted_scope
                if not session_ok or not scope_ok:
                    if not session_ok:
                        self._restore_state(snapshot)
                    if not scope_ok:
                        try:
                            _restore_scope(scope, trusted_scope)
                        except Exception:
                            pass
                    self._source_active = False
                    self._integrity_failed = True
                    return self._receipt(request_id, record_id, "denied", "session_integrity_failure")
                self._source_active = False
                if record is None:
                    return self._receipt(request_id, record_id, "abstain", "missing_evidence")
                if type(record) is not EvidenceRecord:
                    return self._receipt(request_id, record_id, "denied", "invalid_evidence_type")
                try:
                    record = _clone_record(record)
                except Exception:
                    return self._receipt(request_id, record_id, "denied", "invalid_evidence_type")

            reason = self._scope_reason(trusted_scope, current_policy_revision=current_policy_revision, now=now)
            if reason is not None:
                return self._receipt(request_id, record_id, "denied", reason)
            if record_id not in trusted_scope.allowed_record_ids:
                return self._receipt(request_id, record_id, "denied", "record_out_of_scope")
            if type(record) is not EvidenceRecord:
                return self._receipt(request_id, record_id, "denied", "invalid_evidence_type")
            if record.partition != self.partition:
                return self._receipt(request_id, record_id, "denied", "cross_partition_evidence")
            if record.record_id != record_id:
                return self._receipt(request_id, record_id, "denied", "reference_mismatch")
            age = (now - utc(record.observed_at)).total_seconds()
            if age < 0:
                return self._receipt(request_id, record_id, "abstain", "future_evidence")
            if age > float(max_age_seconds):
                return self._receipt(request_id, record_id, "abstain", "stale_evidence")

            if not cached:
                with self._lock:
                    existing = self._cache.get(record_id)
                    if existing is not None and existing != record:
                        return self._receipt(request_id, record_id, "denied", "cache_identity_collision")
                    if existing is None:
                        if len(self._cache) >= self._max_cache_entries:
                            return self._receipt(request_id, record_id, "denied", "cache_capacity")
                        self._cache[record_id] = record

            reason = self._scope_reason(trusted_scope, current_policy_revision=current_policy_revision, now=now)
            if reason is not None:
                return self._receipt(request_id, record_id, "denied", reason)
            if record_id not in trusted_scope.allowed_record_ids:
                return self._receipt(request_id, record_id, "denied", "record_out_of_scope")
            return self._receipt(request_id, record_id, "returned", "evidence_returned", record=record, cached=cached)

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
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, (int, float)) or not isfinite(float(max_age_seconds)) or max_age_seconds <= 0:
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
            if record is None or type(record) is not EvidenceRecord or record.partition != self.partition or record.record_id != record_id:
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
        return CheckpointCheck("accepted_for_read", "checkpoint_valid", self.session_id, trusted_checkpoint.evidence_refs)
