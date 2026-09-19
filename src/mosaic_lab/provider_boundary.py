"""Admission contract for provider calls that require a hard execution boundary.

This module does not implement or claim process/container isolation. It prevents
hardened callers from silently falling back to the cooperative provider path
unless a separately qualified trusted adapter declares bounded, terminable
timeout and cancellation behavior. A shared admission gate enforces the
contract's declared in-flight call bound before provider entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import BoundedSemaphore, RLock
from time import monotonic
from typing import Callable
from weakref import WeakValueDictionary

from .contracts import token
from .text_interaction import (
    ActionPresentation,
    CancellationFlag,
    InteractionInput,
    InteractionResult,
    InteractionSession,
    TextProvider,
    run_interaction_turn,
)


@dataclass(frozen=True)
class ProviderBoundaryContract:
    """Trusted adapter admission facts; never model/provider-generated data."""

    boundary_id: str
    hard_timeout_enforced: bool
    hard_cancellation_enforced: bool
    worker_termination_enforced: bool
    max_inflight_calls: int
    version: str = "1"

    def __post_init__(self) -> None:
        token(self.boundary_id)
        if self.version != "1":
            raise ValueError("unsupported provider boundary contract")
        for value, field in (
            (self.hard_timeout_enforced, "hard_timeout_enforced"),
            (self.hard_cancellation_enforced, "hard_cancellation_enforced"),
            (self.worker_termination_enforced, "worker_termination_enforced"),
        ):
            if type(value) is not bool:
                raise ValueError(f"{field} must be boolean")
        if type(self.max_inflight_calls) is not int or not 0 < self.max_inflight_calls <= 64:
            raise ValueError("max_inflight_calls outside bounded limit")

    @property
    def hard_boundary_ready(self) -> bool:
        return (
            self.hard_timeout_enforced
            and self.hard_cancellation_enforced
            and self.worker_termination_enforced
        )


def _validated_contract(value: object) -> ProviderBoundaryContract | None:
    if type(value) is not ProviderBoundaryContract:
        return None
    try:
        return ProviderBoundaryContract(
            boundary_id=value.boundary_id,
            hard_timeout_enforced=value.hard_timeout_enforced,
            hard_cancellation_enforced=value.hard_cancellation_enforced,
            worker_termination_enforced=value.worker_termination_enforced,
            max_inflight_calls=value.max_inflight_calls,
            version=value.version,
        )
    except (TypeError, ValueError, OverflowError):
        return None


class _ProviderAdmissionState:
    """Process-local permit pool shared by every live gate for one boundary."""

    __slots__ = ("permits", "__weakref__")

    def __init__(self, max_inflight_calls: int) -> None:
        self.permits = BoundedSemaphore(max_inflight_calls)


_GATE_REGISTRY_LOCK = RLock()
_GATE_REGISTRY: WeakValueDictionary[
    tuple[str, str, int],
    _ProviderAdmissionState,
] = WeakValueDictionary()


def _shared_admission_state(
    contract: ProviderBoundaryContract,
) -> _ProviderAdmissionState:
    key = (contract.boundary_id, contract.version, contract.max_inflight_calls)
    with _GATE_REGISTRY_LOCK:
        state = _GATE_REGISTRY.get(key)
        if state is None:
            state = _ProviderAdmissionState(contract.max_inflight_calls)
            _GATE_REGISTRY[key] = state
        return state


class ProviderBoundaryGate:
    """Shared non-blocking admission state for one trusted boundary identity.

    Multiple live gate objects for the same qualified boundary intentionally
    share one process-local permit pool, so reconstructing a gate cannot bypass
    the declared max_inflight_calls bound. The gate never authorizes an action;
    it only bounds provider entry.
    """

    __slots__ = ("_boundary_id", "_max_inflight_calls", "_version", "_state")

    def __init__(self, contract: ProviderBoundaryContract) -> None:
        trusted = _validated_contract(contract)
        if trusted is None or not trusted.hard_boundary_ready:
            raise ValueError("qualified provider boundary contract required")
        self._boundary_id = trusted.boundary_id
        self._max_inflight_calls = trusted.max_inflight_calls
        self._version = trusted.version
        self._state = _shared_admission_state(trusted)

    def matches(self, contract: ProviderBoundaryContract) -> bool:
        trusted = _validated_contract(contract)
        return (
            trusted is not None
            and trusted.hard_boundary_ready
            and self._boundary_id == trusted.boundary_id
            and self._max_inflight_calls == trusted.max_inflight_calls
            and self._version == trusted.version
        )

    def acquire(self) -> bool:
        return self._state.permits.acquire(blocking=False)

    def release(self) -> None:
        self._state.permits.release()


def _validated_gate(
    value: object,
    contract: ProviderBoundaryContract,
) -> ProviderBoundaryGate | None:
    if type(value) is not ProviderBoundaryGate:
        return None
    try:
        return value if value.matches(contract) else None
    except Exception:
        return None


def _trusted_item(item: InteractionInput) -> InteractionInput:
    if type(item) is not InteractionInput:
        raise ValueError("interaction input required")
    return InteractionInput(
        partition=item.partition,
        session_id=item.session_id,
        request_id=item.request_id,
        text=item.text,
        evidence_refs=tuple(item.evidence_refs),
        action=ActionPresentation(
            status=item.action.status,
            receipt_ref=item.action.receipt_ref,
            authoritative=item.action.authoritative,
            version=item.action.version,
        ),
        version=item.version,
    )


def run_hardened_interaction_turn(
    session: InteractionSession,
    item: InteractionInput,
    provider: TextProvider,
    *,
    execution_contract: ProviderBoundaryContract | None,
    admission_gate: ProviderBoundaryGate | None = None,
    cancellation: CancellationFlag | None = None,
    clock: Callable[[], float] = monotonic,
) -> InteractionResult:
    """Admit a provider call only behind a qualified, bounded hard boundary.

    The contract and shared admission gate are trusted integration
    configuration, never provider/model data. Actual isolation/termination
    remains an adapter qualification requirement outside this public generic
    module. The public gate enforces the declared concurrent-entry bound.
    Per-session serialization is acquired before a global provider permit so
    queued same-session work cannot consume capacity needed by other sessions.
    """
    if type(session) is not InteractionSession:
        raise ValueError("interaction session required")
    trusted_item = _trusted_item(item)
    contract = _validated_contract(execution_contract)
    if contract is None or not contract.hard_boundary_ready:
        return InteractionResult(
            "unavailable",
            "provider_hard_boundary_required",
            trusted_item.request_id,
            "",
            trusted_item.evidence_refs,
            trusted_item.action,
            session.calls_used,
            session.tokens_used,
            session.elapsed_seconds,
        )
    gate = _validated_gate(admission_gate, contract)
    if gate is None:
        return InteractionResult(
            "unavailable",
            "provider_inflight_gate_required",
            trusted_item.request_id,
            "",
            trusted_item.evidence_refs,
            trusted_item.action,
            session.calls_used,
            session.tokens_used,
            session.elapsed_seconds,
        )
    with session._lock:
        if not gate.acquire():
            return InteractionResult(
                "unavailable",
                "provider_inflight_limit_reached",
                trusted_item.request_id,
                "",
                trusted_item.evidence_refs,
                trusted_item.action,
                session.calls_used,
                session.tokens_used,
                session.elapsed_seconds,
            )
        try:
            return run_interaction_turn(
                session,
                trusted_item,
                provider,
                cancellation=cancellation,
                clock=clock,
            )
        finally:
            gate.release()
