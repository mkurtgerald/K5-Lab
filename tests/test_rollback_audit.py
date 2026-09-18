from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest

NOW = datetime(2026, 9, 18, 6, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64
EFFECT = "c" * 64
RESULT = "d" * 64


def cap():
    return RollbackCapabilityBinding(
        capability_id="rb1", session_id="sess1", step_id="step1", delivery_id="delivery1",
        partition="part1", principal_ref="principal1", proposal_digest=PROPOSAL,
        policy_revision="policy1", state_digest=STATE, effect_digest=EFFECT,
        issued_at=NOW, expires_at=NOW + timedelta(minutes=2),
    )


def assessment(item):
    return assess_rollback(
        item, session_id="sess1", step_id="step1", delivery_id="delivery1", partition="part1",
        principal_ref="principal1", proposal_digest=PROPOSAL, current_policy_revision="policy1",
        current_state_digest=STATE, current_profile="delegated_simulation",
        terminal_status="verified_complete", terminal_effect_digest=EFFECT,
        now=NOW + timedelta(seconds=1),
    )


def attempt_event(item, request_id="req1", event_id="audit1", digest=None):
    return AuditEvent(
        event_id=event_id, request_id=request_id, partition="part1", principal_ref="principal1",
        profile="delegated_simulation", policy_revision="policy1", model_revision="m1", tool_revision="t1",
        evidence_refs=("rb1",), evidence_digests=(digest or rollback_capability_digest(item),),
        decision="attempted", reason="rollback_attempted", outcome="attempted",
        recorded_at=NOW + timedelta(seconds=2),
    )


def result(outcome="verified_rolled_back", result_ref="res1", observed=None):
    return RollbackResultBinding(
        capability_id="rb1", session_id="sess1", step_id="step1", delivery_id="delivery1",
        result_ref=result_ref, result_digest=RESULT, outcome=outcome,
        observed_at=observed or NOW + timedelta(seconds=3),
    )


def result_event(item, rb, event_id="audit_result", at=None, digest=None):
    mapping = {"verified_rolled_back":"verified_complete", "rollback_failed":"failed", "rollback_unknown":"outcome_unknown"}
    return AuditEvent(
        event_id=event_id, request_id="req1", partition="part1", principal_ref="principal1",
        profile="delegated_simulation", policy_revision="policy1", model_revision="m1", tool_revision="t1",
        evidence_refs=("rb1", rb.result_ref),
        evidence_digests=(rollback_capability_digest(item), digest or rb.result_digest),
        decision="returned", reason="rollback_reconciled", outcome=mapping[rb.outcome],
        recorded_at=at or NOW + timedelta(seconds=4),
    )


def attempt(sim, item, event=None):
    return sim.attempt(
        request_id="req1", now=NOW + timedelta(seconds=2), current_policy_revision="policy1",
        current_state_digest=STATE, current_profile="delegated_simulation", authority_available=True,
        cancelled=False, capability_revoked=False, audit_event=event or attempt_event(item),
    )


def test_audit_precedes_exactly_one_mocked_rollback():
    item=cap(); sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    first=attempt(sim,item); same=attempt(sim,item)
    assert first==same
    assert first.status=="attempted" and first.mocked_rollbacks==1 and first.external_actions==0
    assert len(sink.snapshot())==1


def test_missing_forged_or_preseeded_audit_fails_closed_before_effect():
    item=cap(); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=None)
    missing=attempt(sim,item); assert (missing.status,missing.reason,missing.mocked_rollbacks)==("denied","rollback_audit_unavailable",0)
    sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    forged=attempt(sim,item,attempt_event(item,digest="e"*64)); assert forged.reason=="rollback_audit_binding_mismatch" and forged.mocked_rollbacks==0
    seeded=AuditBuffer(max_entries=8); event=attempt_event(item); assert seeded.append(event) is True
    sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=seeded)
    replay=attempt(sim,item,event); assert replay.reason=="rollback_audit_replay_ambiguous" and replay.mocked_rollbacks==0


def test_new_request_cannot_repeat_effect_after_attempt():
    item=cap(); sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    assert attempt(sim,item).status=="attempted"
    other=sim.attempt(
        request_id="req2", now=NOW + timedelta(seconds=2), current_policy_revision="policy1",
        current_state_digest=STATE, current_profile="delegated_simulation", authority_available=True,
        cancelled=False, capability_revoked=False, audit_event=attempt_event(item,"req2","audit2"),
    )
    assert other.status=="reconciliation_required" and other.mocked_rollbacks==0
    assert len(sink.snapshot())==1


def test_terminal_status_requires_exact_trusted_result_and_second_audit():
    item=cap(); sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    assert attempt(sim,item).status=="attempted"
    rb=result(); terminal=sim.reconcile(rb,request_id="req1",now=NOW+timedelta(seconds=4),audit_event=result_event(item,rb))
    assert terminal.status=="verified_rolled_back" and terminal.mocked_rollbacks==0
    assert terminal.result_ref=="res1" and terminal.result_digest==RESULT and terminal.external_actions==0
    assert len(sink.snapshot())==2


def test_forged_result_audit_stays_nonterminal():
    item=cap(); sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    assert attempt(sim,item).status=="attempted"
    rb=result(); blocked=sim.reconcile(rb,request_id="req1",now=NOW+timedelta(seconds=4),audit_event=result_event(item,rb,digest="e"*64))
    assert blocked.status=="reconciliation_required" and blocked.reason=="rollback_audit_binding_mismatch"
    assert len(sink.snapshot())==1


def test_unknown_result_blocks_reexecution_but_allows_later_reconciliation():
    item=cap(); sink=AuditBuffer(max_entries=8); sim=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    assert attempt(sim,item).status=="attempted"
    unknown=result("rollback_unknown","res_unknown")
    ambiguous=sim.reconcile(unknown,request_id="req1",now=NOW+timedelta(seconds=4),audit_event=result_event(item,unknown))
    assert ambiguous.status=="rollback_unknown"
    other=sim.attempt(
        request_id="req2", now=NOW + timedelta(seconds=5), current_policy_revision="policy1",
        current_state_digest=STATE, current_profile="delegated_simulation", authority_available=True,
        cancelled=False, capability_revoked=False,
        audit_event=AuditEvent(
            event_id="audit2",request_id="req2",partition="part1",principal_ref="principal1",
            profile="delegated_simulation",policy_revision="policy1",model_revision="m1",tool_revision="t1",
            evidence_refs=("rb1",),evidence_digests=(rollback_capability_digest(item),),
            decision="attempted",reason="rollback_attempted",outcome="attempted",recorded_at=NOW+timedelta(seconds=5),
        ),
    )
    assert other.status=="reconciliation_required" and other.mocked_rollbacks==0
    final=result("verified_rolled_back","res_final",NOW+timedelta(seconds=5))
    done=sim.reconcile(final,request_id="req1",now=NOW+timedelta(seconds=6),audit_event=result_event(item,final,"audit_final",NOW+timedelta(seconds=6)))
    assert done.status=="verified_rolled_back" and done.mocked_rollbacks==0
    assert len(sink.snapshot())==3
