from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import (
    AuditAdmissionBinding,
    AuditedDelegatedSimulation,
    DelegationGrant,
    ReconciliationBinding,
    SimulationStep,
)


NOW = datetime(2026, 9, 18, 22, 0, tzinfo=timezone.utc)
ATTEMPT_TIME = NOW + timedelta(seconds=1)
RECONCILE_TIME = NOW + timedelta(seconds=2)
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64
RESULT_DIGEST = "c" * 64


def grant():
    return DelegationGrant(
        grant_id="g1",
        principal_ref="p1",
        partition="part1",
        proposal_digest=DIGEST,
        policy_revision="pol1",
        state_digest=DIGEST,
        allowed_actions=("a1",),
        allowed_targets=("t1",),
        granted_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        max_steps=4,
        max_duration_seconds=60,
        max_actions_per_minute=4,
    )


def binding():
    return AuditAdmissionBinding(proposal_id="prop1", proposal_digest=DIGEST)


def attempt_event(*, version="4", proposal_digest=None):
    return AuditEvent(
        event_id="attempt1",
        request_id="s1",
        partition="part1",
        principal_ref="p1",
        profile="delegated_simulation",
        policy_revision="pol1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=(),
        decision="attempted",
        reason="mocked_effect_admitted",
        outcome="attempted",
        recorded_at=ATTEMPT_TIME,
        proposal_id="prop1",
        proposal_digest=proposal_digest,
        grant_ref="g1",
        version=version,
    )


def test_effect_admission_persists_trusted_v5_proposal_digest():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=binding(),
    )
    receipt = sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=ATTEMPT_TIME,
        current_policy_revision="pol1",
        current_state_digest=DIGEST,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=False,
        audit_event=attempt_event(),
    )
    assert receipt.status == "verified_complete"
    assert receipt.authorized is False
    assert receipt.execute is False
    assert receipt.external_actions == 0
    persisted = sink.snapshot()
    assert len(persisted) == 1
    assert persisted[0].version == "5"
    assert persisted[0].proposal_id == "prop1"
    assert persisted[0].proposal_digest == DIGEST


def test_forged_v5_proposal_digest_is_denied_before_effect_or_persistence():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=binding(),
    )
    receipt = sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=ATTEMPT_TIME,
        current_policy_revision="pol1",
        current_state_digest=DIGEST,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=False,
        audit_event=attempt_event(version="5", proposal_digest=OTHER_DIGEST),
    )
    assert receipt.status == "denied"
    assert receipt.reason == "audit_binding_mismatch"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()


def test_reconciliation_persists_same_trusted_v5_proposal_digest():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=binding(),
    )
    first = sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=ATTEMPT_TIME,
        current_policy_revision="pol1",
        current_state_digest=DIGEST,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="outcome_unknown",
        reversible=False,
        audit_event=attempt_event(),
    )
    assert first.status == "outcome_unknown"
    reconciliation = ReconciliationBinding(
        step_id="s1",
        delivery_id="d1",
        source_ref="source1",
        result_ref="result1",
        result_digest=RESULT_DIGEST,
        authoritative_outcome="verified_complete",
        observed_at=RECONCILE_TIME,
    )
    result_event = AuditEvent(
        event_id="result1",
        request_id="s1",
        partition="part1",
        principal_ref="p1",
        profile="delegated_simulation",
        policy_revision="pol1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=(),
        decision="returned",
        reason="reconciled",
        outcome="verified_complete",
        recorded_at=RECONCILE_TIME,
        proposal_id="prop1",
        grant_ref="g1",
        reconciliation_binding_version=reconciliation.version,
        reconciliation_delivery_id=reconciliation.delivery_id,
        reconciliation_source_ref=reconciliation.source_ref,
        reconciliation_result_ref=reconciliation.result_ref,
        reconciliation_result_digest=reconciliation.result_digest,
        reconciliation_observed_at=reconciliation.observed_at,
    )
    resolved = sim.reconcile(
        "s1",
        authoritative_outcome="verified_complete",
        reversible=False,
        reconciliation_binding=reconciliation,
        audit_event=result_event,
        now=RECONCILE_TIME,
    )
    assert resolved.status == "verified_complete"
    assert resolved.authorized is False
    assert resolved.execute is False
    assert resolved.external_actions == 0
    persisted = sink.snapshot()
    assert len(persisted) == 2
    assert all(item.version == "5" for item in persisted)
    assert all(item.proposal_digest == DIGEST for item in persisted)
    assert persisted[-1].reconciliation_result_digest == RESULT_DIGEST
