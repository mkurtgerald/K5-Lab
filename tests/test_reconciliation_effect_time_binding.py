from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import (
    AuditAdmissionBinding,
    AuditedDelegatedSimulation,
    DelegationGrant,
    ReconciliationBinding,
    SimulationStep,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
ATTEMPT_TIME = NOW + timedelta(seconds=2)
OBSERVED_BEFORE_EFFECT = NOW + timedelta(seconds=1)
RECONCILE_TIME = NOW + timedelta(seconds=3)
STATE = "a" * 64
RESULT_DIGEST = "b" * 64


def _grant():
    return DelegationGrant(
        grant_id="g1",
        principal_ref="p1",
        partition="part1",
        proposal_digest=STATE,
        policy_revision="pol1",
        state_digest=STATE,
        allowed_actions=("a1",),
        allowed_targets=("t1",),
        granted_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        max_steps=4,
        max_duration_seconds=60,
        max_actions_per_minute=4,
    )


def _audit_event(*, event_id, decision, outcome, reason, recorded_at, **changes):
    values = dict(
        event_id=event_id,
        request_id="s1",
        partition="part1",
        principal_ref="p1",
        profile="delegated_simulation",
        policy_revision="pol1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=(),
        decision=decision,
        reason=reason,
        outcome=outcome,
        recorded_at=recorded_at,
        proposal_id="prop1",
        grant_ref="g1",
    )
    values.update(changes)
    return AuditEvent(**values)


def test_reconciliation_observation_cannot_predate_the_mocked_effect():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        _grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=AuditAdmissionBinding(proposal_id="prop1", proposal_digest=STATE),
    )
    first = sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=ATTEMPT_TIME,
        current_policy_revision="pol1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="outcome_unknown",
        reversible=False,
        audit_event=_audit_event(
            event_id="admit1",
            decision="attempted",
            outcome="attempted",
            reason="mocked_effect_admitted",
            recorded_at=ATTEMPT_TIME,
        ),
    )
    assert first.status == "outcome_unknown"

    trusted = ReconciliationBinding(
        step_id="s1",
        delivery_id="d1",
        source_ref="source1",
        result_ref="result1",
        result_digest=RESULT_DIGEST,
        authoritative_outcome="verified_complete",
        observed_at=OBSERVED_BEFORE_EFFECT,
    )
    terminal = _audit_event(
        event_id="result1",
        decision="returned",
        outcome="verified_complete",
        reason="reconciled",
        recorded_at=RECONCILE_TIME,
        reconciliation_binding_version=trusted.version,
        reconciliation_delivery_id=trusted.delivery_id,
        reconciliation_source_ref=trusted.source_ref,
        reconciliation_result_ref=trusted.result_ref,
        reconciliation_result_digest=trusted.result_digest,
        reconciliation_observed_at=trusted.observed_at,
    )
    blocked = sim.reconcile(
        "s1",
        authoritative_outcome="verified_complete",
        reversible=False,
        reconciliation_binding=trusted,
        audit_event=terminal,
        now=RECONCILE_TIME,
    )
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "reconciliation_binding_mismatch"
    assert blocked.mocked_effects == 0
    assert len(sink.snapshot()) == 1
