from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest

NOW = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
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
        expires_at=NOW + timedelta(minutes=5),
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


def attempt_event(item, *, event_id="attempt1", at=None):
    at = at or NOW + timedelta(seconds=2)
    return AuditEvent(
        event_id=event_id,
        request_id="req1",
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


def result(item, *, ref, digest_char, outcome, observed_at):
    return RollbackResultBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        result_ref=ref,
        result_digest=digest_char * 64,
        outcome=outcome,
        observed_at=observed_at,
    )


def result_event(item, value, *, event_id, at):
    audit_outcome = {
        "verified_rolled_back": "verified_complete",
        "rollback_failed": "failed",
        "rollback_unknown": "outcome_unknown",
    }[value.outcome]
    return AuditEvent(
        event_id=event_id,
        request_id="req1",
        partition="part1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=("rb1", value.result_ref),
        evidence_digests=(rollback_capability_digest(item), value.result_digest),
        decision="returned",
        reason="rollback_reconciled",
        outcome=audit_outcome,
        recorded_at=at,
    )


def try_attempt(sim, item, *, at):
    return sim.attempt(
        request_id="req1",
        now=at,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        capability_revoked=False,
        audit_event=attempt_event(item, event_id="new_attempt", at=at),
    )


def test_restart_snapshot_over_unknown_result_bound_blocks_growth_without_audit_mutation():
    item = capability()
    sink = AuditBuffer(max_entries=16)
    sink.append(attempt_event(item))
    for index, digest_char in enumerate(("d", "e", "f"), start=1):
        value = result(
            item,
            ref=f"unknown{index}",
            digest_char=digest_char,
            outcome="rollback_unknown",
            observed_at=NOW + timedelta(seconds=2 + index),
        )
        sink.append(
            result_event(
                item,
                value,
                event_id=f"unknown_audit{index}",
                at=NOW + timedelta(seconds=3 + index),
            )
        )

    restarted = AuditedRollbackSimulation(
        item,
        assessment=assessment(item),
        audit_sink=sink,
        max_unknown_results=2,
    )
    before = sink.snapshot()
    extra = result(
        item,
        ref="unknown4",
        digest_char="9",
        outcome="rollback_unknown",
        observed_at=NOW + timedelta(seconds=7),
    )
    blocked = restarted.reconcile(
        extra,
        request_id="req1",
        now=NOW + timedelta(seconds=8),
        audit_event=result_event(
            item,
            extra,
            event_id="unknown_audit4",
            at=NOW + timedelta(seconds=8),
        ),
    )

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.authorized is False
    assert blocked.execute is False
    assert blocked.external_actions == 0
    assert sink.snapshot() == before


def test_restart_conflicting_terminal_history_fails_closed_without_repeat_effect():
    item = capability()
    sink = AuditBuffer(max_entries=16)
    sink.append(attempt_event(item))

    verified = result(
        item,
        ref="verified1",
        digest_char="d",
        outcome="verified_rolled_back",
        observed_at=NOW + timedelta(seconds=3),
    )
    failed = result(
        item,
        ref="failed1",
        digest_char="e",
        outcome="rollback_failed",
        observed_at=NOW + timedelta(seconds=4),
    )
    sink.append(
        result_event(
            item,
            verified,
            event_id="verified_audit",
            at=NOW + timedelta(seconds=4),
        )
    )
    sink.append(
        result_event(
            item,
            failed,
            event_id="failed_audit",
            at=NOW + timedelta(seconds=5),
        )
    )

    restarted = AuditedRollbackSimulation(
        item,
        assessment=assessment(item),
        audit_sink=sink,
        max_unknown_results=2,
    )
    before = sink.snapshot()
    blocked = try_attempt(restarted, item, at=NOW + timedelta(seconds=6))

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.authorized is False
    assert blocked.execute is False
    assert blocked.external_actions == 0
    assert sink.snapshot() == before
