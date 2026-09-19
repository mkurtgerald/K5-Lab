from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest

NOW = datetime(2026, 9, 18, 7, 0, tzinfo=timezone.utc)
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


def attempt_event(item, *, event_id, request_id, at):
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


def result_binding(*, result_ref, outcome, observed_at, digest_char):
    return RollbackResultBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        result_ref=result_ref,
        result_digest=digest_char * 64,
        outcome=outcome,
        observed_at=observed_at,
    )


def result_event(item, result, *, event_id, at):
    outcome = {
        "verified_rolled_back": "verified_complete",
        "rollback_failed": "failed",
        "rollback_unknown": "outcome_unknown",
    }[result.outcome]
    return AuditEvent(
        event_id=event_id,
        request_id="req1",
        partition="part1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=("rb1", result.result_ref),
        evidence_digests=(rollback_capability_digest(item), result.result_digest),
        decision="returned",
        reason="rollback_reconciled",
        outcome=outcome,
        recorded_at=at,
    )


def attempt(sim, item, *, request_id, event_id, at):
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


def test_restart_with_prior_attempt_audit_cannot_repeat_mocked_rollback():
    item = capability()
    sink = AuditBuffer(max_entries=16)
    first = AuditedRollbackSimulation(item, assessment=assessment(item), audit_sink=sink)
    initial = attempt(first, item, request_id="req1", event_id="audit1", at=NOW + timedelta(seconds=2))
    assert initial.status == "attempted" and initial.mocked_rollbacks == 1

    restarted = AuditedRollbackSimulation(item, assessment=assessment(item), audit_sink=sink)
    blocked = attempt(restarted, item, request_id="req2", event_id="audit2", at=NOW + timedelta(seconds=3))
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_prior_attempt_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.external_actions == 0
    assert len(sink.snapshot()) == 1

    final = result_binding(
        result_ref="res_final",
        outcome="verified_rolled_back",
        observed_at=NOW + timedelta(seconds=4),
        digest_char="d",
    )
    resolved = restarted.reconcile(
        final,
        request_id="req1",
        now=NOW + timedelta(seconds=5),
        audit_event=result_event(item, final, event_id="audit_final", at=NOW + timedelta(seconds=5)),
    )
    assert resolved.status == "verified_rolled_back"
    assert resolved.mocked_rollbacks == 0
    assert resolved.external_actions == 0
    assert len(sink.snapshot()) == 2


def test_unknown_result_ledger_is_bounded_without_blocking_terminal_resolution():
    item = capability()
    sink = AuditBuffer(max_entries=16)
    sim = AuditedRollbackSimulation(
        item,
        assessment=assessment(item),
        audit_sink=sink,
        max_unknown_results=2,
    )
    assert attempt(sim, item, request_id="req1", event_id="audit1", at=NOW + timedelta(seconds=2)).status == "attempted"

    unknown1 = result_binding(
        result_ref="res_unknown1",
        outcome="rollback_unknown",
        observed_at=NOW + timedelta(seconds=3),
        digest_char="d",
    )
    receipt1 = sim.reconcile(
        unknown1,
        request_id="req1",
        now=NOW + timedelta(seconds=4),
        audit_event=result_event(item, unknown1, event_id="audit_unknown1", at=NOW + timedelta(seconds=4)),
    )
    assert receipt1.status == "rollback_unknown"

    unknown2 = result_binding(
        result_ref="res_unknown2",
        outcome="rollback_unknown",
        observed_at=NOW + timedelta(seconds=5),
        digest_char="e",
    )
    receipt2 = sim.reconcile(
        unknown2,
        request_id="req1",
        now=NOW + timedelta(seconds=6),
        audit_event=result_event(item, unknown2, event_id="audit_unknown2", at=NOW + timedelta(seconds=6)),
    )
    assert receipt2.status == "rollback_unknown"

    unknown3 = result_binding(
        result_ref="res_unknown3",
        outcome="rollback_unknown",
        observed_at=NOW + timedelta(seconds=7),
        digest_char="f",
    )
    blocked = sim.reconcile(
        unknown3,
        request_id="req1",
        now=NOW + timedelta(seconds=8),
        audit_event=result_event(item, unknown3, event_id="audit_unknown3", at=NOW + timedelta(seconds=8)),
    )
    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_result_ledger_capacity"
    assert blocked.mocked_rollbacks == 0
    assert len(sink.snapshot()) == 3

    final = result_binding(
        result_ref="res_final",
        outcome="verified_rolled_back",
        observed_at=NOW + timedelta(seconds=9),
        digest_char="9",
    )
    done = sim.reconcile(
        final,
        request_id="req1",
        now=NOW + timedelta(seconds=10),
        audit_event=result_event(item, final, event_id="audit_final", at=NOW + timedelta(seconds=10)),
    )
    assert done.status == "verified_rolled_back"
    assert len(sink.snapshot()) == 4

    replay = sim.reconcile(
        unknown1,
        request_id="req1",
        now=NOW + timedelta(seconds=11),
        audit_event=result_event(item, unknown1, event_id="audit_unknown1", at=NOW + timedelta(seconds=4)),
    )
    assert replay == receipt1
    assert len(sink.snapshot()) == 4


def test_unknown_result_limit_is_strictly_bounded():
    item = capability()
    sink = AuditBuffer(max_entries=8)
    for value in (0, 65, True):
        try:
            AuditedRollbackSimulation(
                item,
                assessment=assessment(item),
                audit_sink=sink,
                max_unknown_results=value,
            )
        except ValueError as exc:
            assert str(exc) == "max_unknown_results outside bounded limit"
        else:
            raise AssertionError("invalid result ledger limit was accepted")
