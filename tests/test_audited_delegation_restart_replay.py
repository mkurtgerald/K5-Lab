from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditAdmissionBinding, AuditedDelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)
DIGEST = "a" * 64


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


def attempt(sim):
    return sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=NOW,
        current_policy_revision="pol1",
        current_state_digest=DIGEST,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
        audit_event=event(),
    )


def test_restart_cannot_reuse_prior_audit_admission_for_second_mocked_effect():
    sink = AuditBuffer(max_entries=4)
    first = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    initial = attempt(first)
    assert initial.status == "verified_complete"
    assert initial.mocked_effects == 1
    assert len(sink.snapshot()) == 1

    restarted = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    replay = attempt(restarted)
    assert replay.status == "reconciliation_required"
    assert replay.reason == "audit_replay_ambiguous"
    assert replay.mocked_effects == 0
    assert replay.authorized is False
    assert replay.execute is False
    assert replay.external_actions == 0
    assert len(sink.snapshot()) == 1
