from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import (
    AuditAdmissionBinding,
    AuditedDelegatedSimulation,
    DelegatedSimulation,
    DelegationGrant,
    ReconciliationBinding,
    SimulationReceipt,
    SimulationStep,
)

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
ATTEMPT_TIME = NOW + timedelta(seconds=1)
RECONCILE_TIME = NOW + timedelta(seconds=2)
STATE = "a" * 64
RESULT_DIGEST = "b" * 64


def grant():
    return DelegationGrant(
        grant_id="g1", principal_ref="p1", partition="part1", proposal_digest=STATE,
        policy_revision="pol1", state_digest=STATE, allowed_actions=("a1",), allowed_targets=("t1",),
        granted_at=NOW, expires_at=NOW + timedelta(minutes=5), max_steps=4,
        max_duration_seconds=60, max_actions_per_minute=4,
    )


def binding():
    return AuditAdmissionBinding(proposal_id="prop1", proposal_digest=STATE)


def reconciliation():
    return ReconciliationBinding(
        step_id="s1", delivery_id="d1", source_ref="source1", result_ref="result1",
        result_digest=RESULT_DIGEST, authoritative_outcome="verified_complete", observed_at=RECONCILE_TIME,
    )


def attempt(sim, *, reversible):
    kwargs = dict(
        now=ATTEMPT_TIME, current_policy_revision="pol1", current_state_digest=STATE,
        current_profile="delegated_simulation", authority_available=True,
        cancelled=False, grant_revoked=False, mocked_outcome="outcome_unknown",
        reversible=reversible,
    )
    if isinstance(sim, AuditedDelegatedSimulation):
        kwargs["audit_event"] = AuditEvent(
            event_id="admit1", request_id="s1", partition="part1", principal_ref="p1",
            profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
            tool_revision="t1", evidence_refs=(), decision="attempted",
            reason="mocked_effect_admitted", outcome="attempted", recorded_at=ATTEMPT_TIME,
            proposal_id="prop1", grant_ref="g1",
        )
    return sim.attempt_step(SimulationStep("s1", "d1", "a1", "t1"), **kwargs)


def terminal():
    trusted = reconciliation()
    return AuditEvent(
        event_id="result1", request_id="s1", partition="part1", principal_ref="p1",
        profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
        tool_revision="t1", evidence_refs=(), decision="returned", reason="reconciled",
        outcome="verified_complete", recorded_at=RECONCILE_TIME, proposal_id="prop1", grant_ref="g1",
        reconciliation_binding_version=trusted.version,
        reconciliation_delivery_id=trusted.delivery_id,
        reconciliation_source_ref=trusted.source_ref,
        reconciliation_result_ref=trusted.result_ref,
        reconciliation_result_digest=trusted.result_digest,
        reconciliation_observed_at=trusted.observed_at,
    )


def test_reconciliation_cannot_promote_rollback_availability():
    sim = DelegatedSimulation(grant(), session_id="sess1", started_at=NOW)
    assert attempt(sim, reversible=False).status == "outcome_unknown"

    blocked = sim.reconcile("s1", authoritative_outcome="verified_complete", reversible=True)
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "reversibility_mismatch"
    assert blocked.rollback_available is False
    assert blocked.external_actions == 0

    resolved = sim.reconcile("s1", authoritative_outcome="verified_complete", reversible=False)
    assert resolved.status == "verified_complete"
    assert resolved.rollback_available is False
    assert resolved.external_actions == 0


def test_reconciliation_does_not_publish_unbound_positive_reversibility():
    sim = DelegatedSimulation(grant(), session_id="sess1", started_at=NOW)
    assert attempt(sim, reversible=True).status == "outcome_unknown"

    blocked = sim.reconcile("s1", authoritative_outcome="verified_complete", reversible=False)
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "reversibility_mismatch"
    assert blocked.rollback_available is False

    resolved = sim.reconcile("s1", authoritative_outcome="verified_complete", reversible=True)
    assert resolved.status == "verified_complete"
    assert resolved.rollback_available is False


def test_public_receipt_rejects_unbound_rollback_claim():
    try:
        SimulationReceipt(
            status="verified_complete", reason="mocked_effect_recorded", session_id="sess1",
            step_id="s1", delivery_id="d1", step_index=1, mocked_effects=1,
            completed_steps=1, failed_steps=0, unknown_steps=0, rollback_available=True,
        )
    except ValueError as exc:
        assert "rollback availability" in str(exc)
    else:
        raise AssertionError("public receipt accepted unbound rollback availability")


def test_audited_reversibility_mismatch_does_not_admit_terminal_audit():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    assert attempt(sim, reversible=False).status == "outcome_unknown"
    assert len(sink.snapshot()) == 1

    trusted_result = reconciliation()
    blocked = sim.reconcile(
        "s1", authoritative_outcome="verified_complete", reversible=True,
        reconciliation_binding=trusted_result, audit_event=terminal(), now=RECONCILE_TIME,
    )
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "reversibility_mismatch"
    assert blocked.rollback_available is False
    assert len(sink.snapshot()) == 1

    resolved = sim.reconcile(
        "s1", authoritative_outcome="verified_complete", reversible=False,
        reconciliation_binding=trusted_result, audit_event=terminal(), now=RECONCILE_TIME,
    )
    assert resolved.status == "verified_complete"
    assert resolved.rollback_available is False
    assert len(sink.snapshot()) == 2
