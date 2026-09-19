"""Delegated-simulation public surface with trusted v5 audit persistence binding.

The implementation remains in the frozen core module so this boundary can add
narrow persistence and fail-closed recovery guarantees without duplicating or
weakening the established simulation contracts.
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
    """Audited simulation with digest-bound persistence and ambiguous-failure recovery."""

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

    def _record_effect_boundary_failure(self, step: SimulationStep, kwargs: dict) -> SimulationReceipt:
        """Quarantine an admitted step when its local effect transition crashes.

        Audit admission has already succeeded before control reaches the core effect
        transition. Any unexpected failure after that point is therefore ambiguous:
        never blind-retry it and never claim rollback. Preserve enough trusted local
        identity to require authoritative reconciliation instead.
        """
        if not isinstance(step, SimulationStep):
            raise ValueError("trusted simulation step required")
        effect_time = _core.utc(kwargs["now"])
        reversible = kwargs["reversible"]
        if not isinstance(reversible, bool):
            raise ValueError("boolean flags required")
        with self._lock:
            existing_step = self._delivery_steps.get(step.delivery_id)
            if existing_step is not None and existing_step != step:
                prior = self._receipts[step.delivery_id]
                return self._receipt(
                    status="denied",
                    reason="delivery_identity_collision",
                    step=step,
                    step_index=prior.step_index,
                )

            prior = self._step_receipts.get(step.step_id)
            step_index = prior.step_index if prior is not None else len(self._step_receipts) + 1
            if prior is None:
                receipt = self._receipt(
                    status="outcome_unknown",
                    reason="effect_boundary_failure",
                    step=step,
                    step_index=step_index,
                    mocked_effects=0,
                    rollback_available=False,
                )
            else:
                receipt = _replace(
                    prior,
                    status="outcome_unknown",
                    reason="effect_boundary_failure",
                    mocked_effects=0,
                    rollback_available=False,
                )

            self._step_effect_times[step.step_id] = effect_time
            self._step_reversible[step.step_id] = reversible
            self._step_receipts[step.step_id] = receipt
            completed, failed, unknown = self._counts()
            receipt = _replace(
                receipt,
                completed_steps=completed,
                failed_steps=failed,
                unknown_steps=unknown,
            )
            self._step_receipts[step.step_id] = receipt
            self._delivery_steps[step.delivery_id] = step
            self._receipts[step.delivery_id] = receipt
            return receipt

    def attempt_step(self, step: SimulationStep, *, audit_event: AuditEvent | None, **kwargs) -> SimulationReceipt:
        try:
            return super().attempt_step(step, audit_event=audit_event, **kwargs)
        except (TypeError, ValueError):
            raise
        except Exception:
            return self._record_effect_boundary_failure(step, kwargs)

    def reconcile(
        self,
        step_id: str,
        *,
        authoritative_outcome: str,
        reversible: bool,
        reconciliation_binding: ReconciliationBinding | None = None,
        audit_event: AuditEvent | None = None,
        now=None,
    ) -> SimulationReceipt:
        try:
            return super().reconcile(
                step_id,
                authoritative_outcome=authoritative_outcome,
                reversible=reversible,
                reconciliation_binding=reconciliation_binding,
                audit_event=audit_event,
                now=now,
            )
        except (TypeError, ValueError):
            raise
        except Exception:
            with self._lock:
                prior = self._step_receipts.get(step_id)
                if prior is None:
                    raise
                return _replace(
                    prior,
                    status="reconciliation_required",
                    reason="reconciliation_state_failure",
                    mocked_effects=0,
                    rollback_available=False,
                )
