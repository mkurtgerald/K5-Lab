from dataclasses import replace
from datetime import datetime, timedelta, timezone

from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback

NOW = datetime(2026, 9, 18, 1, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64
EFFECT = "c" * 64
RESULT = "d" * 64


def capability(**changes):
    values = dict(
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
        expires_at=NOW + timedelta(minutes=1),
    )
    values.update(changes)
    return RollbackCapabilityBinding(**values)


def assess(item=None, **changes):
    values = dict(
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
    values.update(changes)
    return assess_rollback(capability() if item is None else item, **values)


def test_exact_trusted_capability_is_non_authorizing():
    receipt = assess()
    assert receipt.status == "available_for_simulation"
    assert receipt.rollback_available is True
    assert receipt.capability_id == "rb1"
    assert receipt.effect_digest == EFFECT
    assert receipt.authorized is False
    assert receipt.execute is False
    assert receipt.external_actions == 0


def test_missing_or_forged_capability_fails_closed():
    for item in (False, {}, object()):
        receipt = assess(item)
        assert receipt.status == "denied"
        assert receipt.reason == "rollback_capability_required"
        assert receipt.rollback_available is False


def test_cross_boundary_substitution_fails_closed():
    cases = (
        (capability(session_id="sess2"), "rollback_session_mismatch"),
        (capability(step_id="step2"), "rollback_step_mismatch"),
        (capability(delivery_id="delivery2"), "rollback_delivery_mismatch"),
        (capability(partition="part2"), "rollback_partition_mismatch"),
        (capability(principal_ref="principal2"), "rollback_principal_mismatch"),
        (capability(proposal_digest="e" * 64), "rollback_proposal_mismatch"),
        (capability(policy_revision="policy2"), "rollback_policy_mismatch"),
        (capability(state_digest="e" * 64), "rollback_state_mismatch"),
        (capability(effect_digest="e" * 64), "rollback_effect_mismatch"),
    )
    for item, reason in cases:
        receipt = assess(item)
        assert receipt.status == "denied"
        assert receipt.reason == reason
        assert receipt.rollback_available is False


def test_terminal_profile_and_time_are_rechecked():
    assert assess(current_profile="recommend").reason == "rollback_profile_mismatch"
    assert assess(terminal_status="failed").reason == "rollback_terminal_state_mismatch"
    assert assess(capability(issued_at=NOW + timedelta(seconds=2), expires_at=NOW + timedelta(minutes=1))).reason == "rollback_capability_not_yet_valid"
    assert assess(capability(expires_at=NOW + timedelta(seconds=1)), now=NOW + timedelta(seconds=1)).reason == "rollback_capability_expired"


def test_result_binding_is_versioned_and_outcome_bounded():
    item = RollbackResultBinding(
        capability_id="rb1",
        session_id="sess1",
        step_id="step1",
        delivery_id="delivery1",
        result_ref="result1",
        result_digest=RESULT,
        outcome="verified_rolled_back",
        observed_at=NOW + timedelta(seconds=2),
    )
    assert item.version == "1"
    assert item.outcome == "verified_rolled_back"

    try:
        replace(item, outcome="success")
    except ValueError as exc:
        assert "rollback outcome" in str(exc)
    else:
        raise AssertionError("unsupported rollback outcome accepted")
