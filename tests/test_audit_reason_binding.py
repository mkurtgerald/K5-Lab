from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditedDelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
STATE = "a" * 64


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
        max_steps=2,
        max_duration_seconds=60,
        max_actions_per_minute=2,
    )


def test_attempt_audit_reason_is_semantically_bound_before_effect():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
    )
    forged = AuditEvent(
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
        reason="forged_reason",
        outcome="attempted",
        recorded_at=NOW,
        proposal_id="prop1",
        grant_ref="g1",
    )
    receipt = sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=NOW,
        current_policy_revision="pol1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
        audit_event=forged,
    )
    assert (receipt.status, receipt.reason) == ("denied", "audit_binding_mismatch")
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()
