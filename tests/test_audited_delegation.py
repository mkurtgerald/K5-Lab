from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditAdmissionBinding, AuditedDelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def grant():
    return DelegationGrant(
        grant_id="g1", principal_ref="p1", partition="part1",
        proposal_digest=DIGEST, policy_revision="pol1", state_digest=DIGEST,
        allowed_actions=("a1",), allowed_targets=("t1",),
        granted_at=NOW, expires_at=NOW + timedelta(minutes=5),
        max_steps=4, max_duration_seconds=60, max_actions_per_minute=4,
    )


def binding():
    return AuditAdmissionBinding(proposal_id="prop1", proposal_digest=DIGEST)


def event(event_id="e1", step_id="s1"):
    return AuditEvent(
        event_id=event_id, request_id=step_id, partition="part1", principal_ref="p1",
        profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
        tool_revision="t1", evidence_refs=(), decision="attempted",
        reason="mocked_effect_admitted", outcome="attempted", recorded_at=NOW,
        proposal_id="prop1", grant_ref="g1",
    )


def attempt(sim, *, step_id="s1", delivery_id="d1", audit_event=None):
    return sim.attempt_step(
        SimulationStep(step_id, delivery_id, "a1", "t1"), now=NOW,
        current_policy_revision="pol1", current_state_digest=DIGEST,
        current_profile="delegated_simulation", authority_available=True,
        cancelled=False, grant_revoked=False, mocked_outcome="verified_complete",
        reversible=True, audit_event=audit_event,
    )


def test_audit_binding_is_required_at_construction():
    sink = AuditBuffer(max_entries=4)
    try:
        AuditedDelegatedSimulation(
            grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=None
        )
    except ValueError as exc:
        assert str(exc) == "trusted audit binding required"
    else:
        raise AssertionError("audited simulation accepted missing trusted binding")


def test_audit_unavailable_denies_before_mocked_effect():
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=None, audit_binding=binding()
    )
    receipt = attempt(sim, audit_event=event())
    assert receipt.status == "denied"
    assert receipt.reason == "audit_unavailable"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0


def test_audit_capacity_denies_without_effect():
    sink = AuditBuffer(max_entries=1)
    sink.append(event("pre", "pre"))
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    receipt = attempt(sim, audit_event=event())
    assert receipt.status == "denied"
    assert receipt.reason == "audit_admission_failed"
    assert receipt.mocked_effects == 0
    assert len(sink.snapshot()) == 1


def test_audit_binding_mismatch_denies():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    bad = AuditEvent(
        event_id="e1", request_id="wrong", partition="part1", principal_ref="p1",
        profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
        tool_revision="t1", evidence_refs=(), decision="attempted",
        reason="mocked_effect_admitted", outcome="attempted", recorded_at=NOW,
        proposal_id="prop1", grant_ref="g1",
    )
    receipt = attempt(sim, audit_event=bad)
    assert receipt.status == "denied"
    assert receipt.reason == "audit_binding_mismatch"
    assert receipt.mocked_effects == 0
    assert sink.snapshot() == ()


def test_admitted_audit_precedes_effect_and_duplicate_is_idempotent():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(
        grant(), session_id="sess1", started_at=NOW, audit_sink=sink, audit_binding=binding()
    )
    first = attempt(sim, audit_event=event())
    duplicate = attempt(sim, audit_event=event())
    assert first.status == "verified_complete"
    assert first.mocked_effects == 1
    assert duplicate == first
    assert len(sink.snapshot()) == 1
    assert sink.snapshot()[0].request_id == "s1"
