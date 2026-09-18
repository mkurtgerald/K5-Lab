"""Delegated-simulation public surface with trusted v5 audit persistence binding.

The implementation remains in the frozen core module so this boundary can add one
narrow admission guarantee without duplicating or weakening the established
simulation contracts.
"""
from __future__ import annotations

from dataclasses import replace as _replace

from . import _delegation_core as _core
from ._delegation_core import *  # noqa: F401,F403


class _ProposalDigestAuditSink:
    """Bind persisted effect/reconciliation events to the trusted proposal digest."""

    def __init__(self, sink, proposal_digest: str) -> None:
        self._sink = sink
        self._proposal_digest = proposal_digest

    def append(self, event):
        if not isinstance(event, AuditEvent):
            return self._sink.append(event)
        if event.version == "5":
            if event.proposal_digest != self._proposal_digest:
                raise ValueError("audit proposal digest mismatch")
            bound = event
        elif event.version == "4":
            bound = _replace(
                event,
                proposal_digest=self._proposal_digest,
                version="5",
            )
        else:  # AuditEvent rejects unsupported versions; retain a fail-closed guard.
            raise ValueError("unsupported audit version")
        return self._sink.append(bound)

    def __getattr__(self, name):
        return getattr(self._sink, name)


class AuditedDelegatedSimulation(_core.AuditedDelegatedSimulation):
    """Audited simulation that persists exact content-bound proposal identity."""

    def __init__(
        self,
        grant: DelegationGrant,
        *,
        session_id: str,
        started_at,
        audit_sink: AuditBuffer | None,
        audit_binding: AuditAdmissionBinding,
        max_tracked_deliveries: int = 256,
    ) -> None:
        bound_sink = (
            None
            if audit_sink is None
            else _ProposalDigestAuditSink(audit_sink, audit_binding.proposal_digest)
            if isinstance(audit_binding, AuditAdmissionBinding)
            else audit_sink
        )
        super().__init__(
            grant,
            session_id=session_id,
            started_at=started_at,
            audit_sink=bound_sink,
            audit_binding=audit_binding,
            max_tracked_deliveries=max_tracked_deliveries,
        )

    def _audit_event_matches_upstream(self, audit_event: AuditEvent) -> bool:
        if not super()._audit_event_matches_upstream(audit_event):
            return False
        return (
            audit_event.version == "4"
            or audit_event.proposal_digest == self._audit_binding.proposal_digest
        )
