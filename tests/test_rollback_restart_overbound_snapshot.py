from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest

NOW = datetime(2026, 9, 18, 10, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64
EFFECT = "c" * 64


def _capability():
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


def _assessment(item):
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


def _attempt_event(item):
    return AuditEvent(
        event_id="attempt1",
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
        recorded_at=NOW + timedelta(seconds=2),
    )


def _unknown_result(ref, digest_char, observed_at):
    return RollbackResultBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        result_ref=ref,
        result_digest=digest_char * 64,
        outcome="rollback_unknown",
        observed_at=observed_at,
    )


def _result_event(item, value, *, event_id, at):
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
        outcome="outcome_unknown",
        recorded_at=at,
    )


def test_restart_over_unknown_bound_is_ambiguous_before_any_new_result():
    item = _capability()
    sink = AuditBuffer(max_entries=16)
    sink.append(_attempt_event(item))
    for index, digest_char in enumerate(("d", "e", "f"), start=1):
        value = _unknown_result(
            f"unknown{index}",
            digest_char,
            NOW + timedelta(seconds=2 + index),
        )
        sink.append(
            _result_event(
                item,
                value,
                event_id=f"unknown_audit{index}",
                at=NOW + timedelta(seconds=3 + index),
            )
        )

    restarted = AuditedRollbackSimulation(
        item,
        assessment=_assessment(item),
        audit_sink=sink,
        max_unknown_results=2,
    )
    before = sink.snapshot()
    blocked = restarted.attempt(
        request_id="req1",
        now=NOW + timedelta(seconds=7),
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        capability_revoked=False,
        audit_event=AuditEvent(
            event_id="new_attempt",
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
            recorded_at=NOW + timedelta(seconds=7),
        ),
    )

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "rollback_restart_audit_ambiguous"
    assert blocked.mocked_rollbacks == 0
    assert blocked.authorized is False
    assert blocked.execute is False
    assert blocked.external_actions == 0
    assert sink.snapshot() == before
