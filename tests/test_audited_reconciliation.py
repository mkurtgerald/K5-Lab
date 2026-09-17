from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditedDelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
ATTEMPT_TIME = NOW + timedelta(seconds=1)
RECONCILE_TIME = NOW + timedelta(seconds=2)
STATE = "a" * 64


def grant():
    return DelegationGrant(
        grant_id="g1", principal_ref="p1", partition="part1", proposal_digest=STATE,
        policy_revision="pol1", state_digest=STATE, allowed_actions=("a1",), allowed_targets=("t1",),
        granted_at=NOW, expires_at=NOW + timedelta(minutes=5), max_steps=4,
        max_duration_seconds=60, max_actions_per_minute=4,
    )


def audit_event(*, event_id, decision, outcome, reason, recorded_at):
    return AuditEvent(
        event_id=event_id, request_id="s1", partition="part1", principal_ref="p1",
        profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
        tool_revision="t1", evidence_refs=(), decision=decision, reason=reason,
        outcome=outcome, recorded_at=recorded_at, proposal_id="prop1", grant_ref="g1",
    )


def ambiguous(sim):
    return sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"), now=ATTEMPT_TIME,
        current_policy_revision="pol1", current_state_digest=STATE,
        current_profile="delegated_simulation", authority_available=True,
        cancelled=False, grant_revoked=False, mocked_outcome="outcome_unknown",
        reversible=False,
        audit_event=audit_event(event_id="admit1", decision="attempted", outcome="attempted", reason="mocked_effect_admitted", recorded_at=ATTEMPT_TIME),
    )


def terminal(event_id="term1", *, outcome="verified_complete", decision="returned", reason="reconciled"):
    return audit_event(event_id=event_id, decision=decision, outcome=outcome, reason=reason, recorded_at=RECONCILE_TIME)


def test_audited_reconciliation_records_terminal_outcome_before_resolution():
    sink=AuditBuffer(max_entries=4)
    sim=AuditedDelegatedSimulation(grant(),session_id="sess1",started_at=NOW,audit_sink=sink)
    first=ambiguous(sim)
    assert first.status=="outcome_unknown"
    resolved=sim.reconcile("s1",authoritative_outcome="verified_complete",reversible=False,audit_event=terminal(),now=RECONCILE_TIME)
    assert resolved.status=="verified_complete"
    assert resolved.reason=="reconciled"
    assert resolved.mocked_effects==0
    assert resolved.external_actions==0
    events=sink.snapshot()
    assert len(events)==2
    assert events[-1].outcome=="verified_complete"
    replay=sim.attempt_step(
        SimulationStep("s1","d1","a1","t1"),now=RECONCILE_TIME,
        current_policy_revision="pol1",current_state_digest=STATE,current_profile="delegated_simulation",
        authority_available=True,cancelled=False,grant_revoked=False,mocked_outcome="outcome_unknown",reversible=False,
        audit_event=audit_event(event_id="unused",decision="attempted",outcome="attempted",reason="mocked_effect_admitted",recorded_at=RECONCILE_TIME),
    )
    assert replay==resolved
    assert len(sink.snapshot())==2


def test_reconciliation_audit_failure_preserves_ambiguous_state():
    sink=AuditBuffer(max_entries=1)
    sim=AuditedDelegatedSimulation(grant(),session_id="sess1",started_at=NOW,audit_sink=sink)
    assert ambiguous(sim).status=="outcome_unknown"
    blocked=sim.reconcile("s1",authoritative_outcome="verified_complete",reversible=False,audit_event=terminal(),now=RECONCILE_TIME)
    assert blocked.status=="reconciliation_required"
    assert blocked.reason=="audit_admission_failed"
    assert blocked.mocked_effects==0
    assert len(sink.snapshot())==1
    retry=sim.attempt_step(
        SimulationStep("s1","d2","a1","t1"),now=RECONCILE_TIME,
        current_policy_revision="pol1",current_state_digest=STATE,current_profile="delegated_simulation",
        authority_available=True,cancelled=False,grant_revoked=False,mocked_outcome="verified_complete",reversible=False,
        audit_event=audit_event(event_id="unused",decision="attempted",outcome="attempted",reason="mocked_effect_admitted",recorded_at=RECONCILE_TIME),
    )
    assert retry.status=="reconciliation_required"
    assert retry.reason=="ambiguous_prior_outcome"


def test_forged_terminal_audit_cannot_resolve_unknown_outcome():
    sink=AuditBuffer(max_entries=4)
    sim=AuditedDelegatedSimulation(grant(),session_id="sess1",started_at=NOW,audit_sink=sink)
    assert ambiguous(sim).status=="outcome_unknown"
    blocked=sim.reconcile("s1",authoritative_outcome="verified_complete",reversible=False,audit_event=terminal(outcome="failed",decision="failed"),now=RECONCILE_TIME)
    assert blocked.status=="reconciliation_required"
    assert blocked.reason=="audit_binding_mismatch"
    assert len(sink.snapshot())==1


def test_concurrent_reconciliation_records_one_terminal_audit_event():
    sink=AuditBuffer(max_entries=8)
    sim=AuditedDelegatedSimulation(grant(),session_id="sess1",started_at=NOW,audit_sink=sink)
    assert ambiguous(sim).status=="outcome_unknown"
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(lambda i: sim.reconcile("s1",authoritative_outcome="verified_complete",reversible=False,audit_event=terminal(f"term{i}"),now=RECONCILE_TIME),range(4)))
    assert all(item.status=="verified_complete" for item in results)
    assert len(sink.snapshot())==2
