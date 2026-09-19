"""Admission contract for provider calls that require a hard execution boundary.

This module does not implement or claim process/container isolation. It prevents
hardened callers from silently falling back to the cooperative provider path
unless a separately qualified trusted adapter declares bounded, terminable
timeout and cancellation behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Callable

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
    cancellation: CancellationFlag | None = None,
    clock: Callable[[], float] = monotonic,
) -> InteractionResult:
    """Admit a provider call only behind a separately qualified hard boundary.

    The contract is supplied by trusted integration configuration, never by the
    provider reply or generated text. Actual isolation/termination remains an
    adapter qualification requirement outside this public generic module.
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
    return run_interaction_turn(
        session,
        trusted_item,
        provider,
        cancellation=cancellation,
        clock=clock,
    )
