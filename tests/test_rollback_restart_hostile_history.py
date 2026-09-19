from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest

NOW = datetime(2026, 9, 18, 8, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64
EFFECT = "c" * 64


def capability():
    return RollbackCapabilityBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        partition="part1",
        principal_ref="principal1",
        proposal_digest=PROPOSAL,
        policy_revision="policy1",
        state_digest=STATE,
        effect_digest=EFFECT,
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=3),
    )


def assessment(item):
    return assess_rollback(
        item,
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        partition="part1",
        principal_ref="principal1",
        proposal_digest=PROPOSAL,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        terminal_status="verified_complete",
        terminal_effect_digest=EFFECT,
        now=NOW + timedelta(seconds=1),
    )


def attempt_event(item, *, event_id, request_id="req1", at=None):
    at = at or NOW + timedelta(seconds=2)
    return AuditEvent(
        event_id=event_id,
        request_id=request_id,
        partition="part1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=("rb1",),
        evidence_digests=(rollback_capability_digest(item),),
        decision="attempted",
        reason="rollback_attempted",
        outcome="attempted",
        recorded_at=at,
    )


def result_event(item, *, event_id, result_ref="res1", at=None):
    at = at or NOW + timedelta(seconds=4)
    return AuditEvent(
        event_id=event_id,
        request_id="req1",
        partition="part1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=("rb1", result_ref),
        evidence_digests=(rollback_capability_digest(item), "d" * 64),
        decision="returned",
        reason="rollback_reconciled",
        outcome="verified_complete",
        recorded_at=at,
    )


def try_attempt(sim, item, *, request_id="req1", event_id="new_attempt", at=None):
    at = at or NOW + timedelta(seconds=5)
    return sim.attempt(
        request_id=request_id,
        now=at,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        capability_revoked=False,
        audit_event=attempt_event(item, event_id=event_id, request_id=request_id, at=at),
    )


def test_restart_duplicate_semantic_attempts_fail_closed_without_effect():
    item = capability()
    sink = AuditBuffer(max_entries=8)
    sink.append(attempt_event(item, event_id="audit1"))
    sink.append(attempt_event(item, event_id="audit2"))

    restarted = AuditedRollbackSimulation(item, assessment=assessment(item), audit_sink=sink)
    blocked = try_attempt(restarted, item)

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.authorized is False
    assert blocked.execute is False
    assert blocked.external_actions == 0
    assert len(sink.snapshot()) == 2


def test_restart_orphaned_result_history_fails_closed_without_effect():
    item = capability()
    sink = AuditBuffer(max_entries=8)
    sink.append(result_event(item, event_id="orphan_result"))

    restarted = AuditedRollbackSimulation(item, assessment=assessment(item), audit_sink=sink)
    blocked = try_attempt(restarted, item)

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.external_actions == 0
    assert len(sink.snapshot()) == 1


def test_restart_result_before_attempt_time_fails_closed():
    item = capability()
    sink = AuditBuffer(max_entries=8)
    sink.append(attempt_event(item, event_id="audit1", at=NOW + timedelta(seconds=4)))
    sink.append(result_event(item, event_id="early_result", at=NOW + timedelta(seconds=3)))

    restarted = AuditedRollbackSimulation(item, assessment=assessment(item), audit_sink=sink)
    result = RollbackResultBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        result_ref="res2",
        result_digest="e" * 64,
        outcome="verified_rolled_back",
        observed_at=NOW + timedelta(seconds=5),
    )
    blocked = restarted.reconcile(
        result,
        request_id="req1",
        now=NOW + timedelta(seconds=6),
        audit_event=result_event(item, event_id="new_result", result_ref="res2", at=NOW + timedelta(seconds=6)),
    )

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.external_actions == 0
    assert len(sink.snapshot()) == 2
