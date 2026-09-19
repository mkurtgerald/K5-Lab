"""Bounded opaque request-identity bindings for non-authorizing public flows.

This module does not execute work or grant authority. It provides a reusable,
finite replay/collision guard that a caller can place immediately before an
untrusted callback. Bindings intentionally carry only opaque public tokens.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from .contracts import token

_MAX_LEDGER_ENTRIES = 4096


@dataclass(frozen=True)
class RequestBinding:
    """Exact trusted identity of one attempted public operation."""

    request_id: str
    session_id: str
    partition: str
    principal_ref: str
    policy_revision: str
    operation: str
    subject_ref: str
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported request-binding version")
        for value in (
            self.request_id,
            self.session_id,
            self.partition,
            self.principal_ref,
            self.policy_revision,
            self.operation,
            self.subject_ref,
        ):
            token(value)


@dataclass(frozen=True)
class RequestAdmission:
    """Non-authorizing result from atomic request-identity admission."""

    status: str
    reason: str
    request_id: str
    binding: RequestBinding | None = None
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in {"accepted", "denied"}:
            raise ValueError("unsupported request-admission result")
        token(self.reason)
        token(self.request_id)
        if self.binding is not None and type(self.binding) is not RequestBinding:
            raise ValueError("request admission requires exact request binding")
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("request admission cannot grant execution authority")


@dataclass(frozen=True)
class RequestLedgerSnapshot:
    """Canonical bounded state for inclusion in a caller integrity snapshot."""

    max_entries: int
    bindings: tuple[tuple[str, RequestBinding], ...]
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported request-ledger snapshot version")
        if isinstance(self.max_entries, bool) or not isinstance(self.max_entries, int):
            raise ValueError("max_entries must be an integer")
        if not 1 <= self.max_entries <= _MAX_LEDGER_ENTRIES:
            raise ValueError("max_entries outside bounded limit")
        if not isinstance(self.bindings, tuple) or len(self.bindings) > self.max_entries:
            raise ValueError("snapshot bindings outside bounded limit")
        seen: set[str] = set()
        previous = ""
        for item in self.bindings:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("invalid snapshot binding entry")
            request_id, binding = item
            token(request_id)
            if type(binding) is not RequestBinding or binding.request_id != request_id:
                raise ValueError("snapshot request binding mismatch")
            if request_id in seen:
                raise ValueError("duplicate snapshot request identity")
            if previous and request_id < previous:
                raise ValueError("snapshot bindings must be canonical")
            seen.add(request_id)
            previous = request_id


class BoundedRequestLedger:
    """Finite atomic replay/collision guard with no eviction.

    Exact duplicate identities are reported as replay, while reuse of a request
    identity for any different trusted binding is reported as a collision.
    Capacity exhaustion fails closed instead of evicting prior identities.
    """

    def __init__(self, *, max_entries: int = 1024) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int):
            raise ValueError("max_entries must be an integer")
        if not 1 <= max_entries <= _MAX_LEDGER_ENTRIES:
            raise ValueError("max_entries outside bounded limit")
        self._max_entries = max_entries
        self._bindings: dict[str, RequestBinding] = {}
        self._lock = Lock()

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._bindings)

    def admit(self, binding: RequestBinding) -> RequestAdmission:
        if type(binding) is not RequestBinding:
            raise ValueError("exact request binding required")
        with self._lock:
            existing = self._bindings.get(binding.request_id)
            if existing is not None:
                reason = "request_replayed" if existing == binding else "request_identity_collision"
                return RequestAdmission("denied", reason, binding.request_id, existing)
            if len(self._bindings) >= self._max_entries:
                return RequestAdmission("denied", "request_ledger_capacity", binding.request_id)
            self._bindings[binding.request_id] = binding
            return RequestAdmission("accepted", "request_bound", binding.request_id, binding)

    def snapshot(self) -> RequestLedgerSnapshot:
        with self._lock:
            return RequestLedgerSnapshot(self._max_entries, tuple(sorted(self._bindings.items())))
