from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditedDelegatedSimulation, DelegationGrant, SimulationStep

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


def event(*, event_id="e1", outcome="attempted", recorded_at=NOW):
    return AuditEvent(
        event_id=event_id, request_id="s1", partition="part1", principal_ref="p1",
        profile="delegated_simulation", policy_revision="pol1", model_revision="m1",
        tool_revision="t1", evidence_refs=(), decision="attempted",
        reason="mocked_effect_admitted", outcome=outcome, recorded_at=recorded_at,
        proposal_id="prop1", grant_ref="g1",
    )


def attempt(sim, audit_event):
    return sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"), now=NOW,
        current_policy_revision="pol1", current_state_digest=DIGEST,
        current_profile="delegated_simulation", authority_available=True,
        cancelled=False, grant_revoked=False, mocked_outcome="verified_complete",
        reversible=True, audit_event=audit_event,
    )


def test_audit_cannot_preclaim_terminal_outcome_before_effect():
    sink = AuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(grant(), session_id="sess1", started_at=NOW, audit_sink=sink)
    receipt = attempt(sim, event(outcome="verified_complete"))
    assert receipt.status == "denied"
    assert receipt.reason == "audit_binding_mismatch"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
    assert sink.snapshot() == ()


def test_audit_timestamp_must_bind_to_effect_boundary_time():
    for recorded_at in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=1)):
        sink = AuditBuffer(max_entries=4)
        sim = AuditedDelegatedSimulation(grant(), session_id="sess1", started_at=NOW, audit_sink=sink)
        receipt = attempt(sim, event(recorded_at=recorded_at))
        assert receipt.status == "denied"
        assert receipt.reason == "audit_binding_mismatch"
        assert receipt.mocked_effects == 0
        assert receipt.external_actions == 0
        assert sink.snapshot() == ()


def test_concurrent_duplicate_delivery_records_one_audit_admission():
    sink = AuditBuffer(max_entries=16)
    sim = AuditedDelegatedSimulation(grant(), session_id="sess1", started_at=NOW, audit_sink=sink)

    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda i: attempt(sim, event(event_id=f"e{i}")), range(8)))

    assert all(receipt == receipts[0] for receipt in receipts)
    assert receipts[0].status == "verified_complete"
    assert receipts[0].mocked_effects == 1
    assert receipts[0].external_actions == 0
    assert len(sink.snapshot()) == 1


class TimeoutAuditBuffer(AuditBuffer):
    def append(self, event):
        raise TimeoutError("synthetic audit timeout")


def test_unexpected_audit_sink_failure_fails_closed():
    sink = TimeoutAuditBuffer(max_entries=4)
    sim = AuditedDelegatedSimulation(grant(), session_id="sess1", started_at=NOW, audit_sink=sink)
    receipt = attempt(sim, event())
    assert receipt.status == "denied"
    assert receipt.reason == "audit_admission_failed"
    assert receipt.mocked_effects == 0
    assert receipt.external_actions == 0
