from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditAdmissionBinding, AuditedDelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
STATE = "a" * 64
OTHER_STATE = "b" * 64


def grant():
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


def binding():
    return AuditAdmissionBinding(proposal_id="prop1", proposal_digest=STATE)


def event():
    return AuditEvent(
        event_id="e1",
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
        recorded_at=NOW,
        proposal_id="prop1",
        grant_ref="g1",
    )


def attempt(sim, **overrides):
    kwargs = dict(
        now=NOW,
        current_policy_revision="pol1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
        audit_event=event(),
    )
    kwargs.update(overrides)
    return sim.attempt_step(SimulationStep("s1", "d1", "a1", "t1"), **kwargs)


def test_state_change_is_denied_before_attempt_audit_is_recorded():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    receipt = attempt(sim, current_state_digest=OTHER_STATE)
    assert receipt.status == "denied"
    assert receipt.reason == "state_changed"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()


def test_policy_change_is_denied_before_attempt_audit_is_recorded():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    receipt = attempt(sim, current_policy_revision="pol2")
    assert receipt.status == "denied"
    assert receipt.reason == "policy_changed"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()


def test_cancelled_or_revoked_step_never_records_attempt_audit():
    for overrides, expected_status, expected_reason in (
        ({"cancelled": True}, "cancelled", "session_cancelled"),
        ({"grant_revoked": True}, "denied", "grant_revoked"),
    ):
        sink = AuditBuffer(max_entries=4)
        sim = AuditedDelegatedSimulation(
            grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
        )
        receipt = attempt(sim, **overrides)
        assert receipt.status == expected_status
        assert receipt.reason == expected_reason
        assert receipt.mocked_effects == 0
        assert receipt.external_actions == 0
        assert sink.snapshot() == ()


def test_out_of_scope_step_never_records_attempt_audit():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    receipt = sim.attempt_step(
        SimulationStep("s1", "d1", "other", "t1"),
        now=NOW,
        current_policy_revision="pol1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
        audit_event=event(),
    )
    assert receipt.status == "denied"
    assert receipt.reason == "action_out_of_scope"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()
