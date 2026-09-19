from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mosaic_lab import _delegation_core as core
from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import (
    AuditAdmissionBinding,
    AuditedDelegatedSimulation,
    DelegationGrant,
    ReconciliationBinding,
    SimulationStep,
)

NOW = datetime(2026, 9, 18, 20, 0, tzinfo=timezone.utc)
ATTEMPT_TIME = NOW + timedelta(seconds=1)
RECONCILE_TIME = NOW + timedelta(seconds=2)
PROPOSAL_DIGEST = "a" * 64
RESULT_DIGEST = "b" * 64


def grant():
    return DelegationGrant(
        grant_id="g1",
        principal_ref="p1",
        partition="part1",
        proposal_digest=PROPOSAL_DIGEST,
        policy_revision="pol1",
        state_digest=PROPOSAL_DIGEST,
        allowed_actions=("a1",),
        allowed_targets=("t1",),
        granted_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        max_steps=4,
        max_duration_seconds=60,
        max_actions_per_minute=4,
    )


def binding():
    return AuditAdmissionBinding(proposal_id="prop1", proposal_digest=PROPOSAL_DIGEST)


def attempt_event():
    return AuditEvent(
        event_id="admit1",
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
        recorded_at=ATTEMPT_TIME,
        proposal_id="prop1",
        grant_ref="g1",
        proposal_digest=PROPOSAL_DIGEST,
        version="5",
    )


def reconciliation():
    return ReconciliationBinding(
        step_id="s1",
        delivery_id="d1",
        source_ref="source1",
        result_ref="result1",
        result_digest=RESULT_DIGEST,
        authoritative_outcome="verified_complete",
        observed_at=RECONCILE_TIME,
    )


def terminal_event(trusted):
    return AuditEvent(
        event_id=trusted.result_ref,
        request_id="s1",
        partition="part1",
        principal_ref="p1",
        profile="delegated_simulation",
        policy_revision="pol1",
        model_revision="m1",
        tool_revision="t1",
        evidence_refs=(),
        decision="returned",
        reason="reconciled",
        outcome="verified_complete",
        recorded_at=RECONCILE_TIME,
        proposal_id="prop1",
        grant_ref="g1",
        proposal_digest=PROPOSAL_DIGEST,
        reconciliation_binding_version=trusted.version,
        reconciliation_delivery_id=trusted.delivery_id,
        reconciliation_source_ref=trusted.source_ref,
        reconciliation_result_ref=trusted.result_ref,
        reconciliation_result_digest=trusted.result_digest,
        reconciliation_observed_at=trusted.observed_at,
        version="5",
    )


def attempt(sim, *, outcome="verified_complete"):
    return sim.attempt_step(
        SimulationStep("s1", "d1", "a1", "t1"),
        now=ATTEMPT_TIME,
        current_policy_revision="pol1",
        current_state_digest=PROPOSAL_DIGEST,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome=outcome,
        reversible=False,
        audit_event=attempt_event(),
    )


def test_post_audit_effect_transition_failure_becomes_reconcilable_unknown():
    sink = AuditBuffer(max_entries=8)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=binding(),
    )

    with patch.object(
        core.DelegatedSimulation,
        "attempt_step",
        side_effect=RuntimeError("synthetic effect transition failure"),
    ):
        uncertain = attempt(sim)

    assert uncertain.status == "outcome_unknown"
    assert uncertain.reason == "effect_boundary_failure"
    assert uncertain.mocked_effects == 0
    assert uncertain.unknown_steps == 1
    assert uncertain.rollback_available is False
    assert uncertain.authorized is False
    assert uncertain.execute is False
    assert uncertain.external_actions == 0
    assert sink.snapshot() == (attempt_event(),)

    replay = attempt(sim)
    assert replay == uncertain
    assert sink.snapshot() == (attempt_event(),)

    trusted = reconciliation()
    resolved = sim.reconcile(
        "s1",
        authoritative_outcome="verified_complete",
        reversible=False,
        reconciliation_binding=trusted,
        audit_event=terminal_event(trusted),
        now=RECONCILE_TIME,
    )
    assert resolved.status == "verified_complete"
    assert resolved.reason == "reconciled"
    assert resolved.mocked_effects == 0
    assert resolved.unknown_steps == 0
    assert resolved.rollback_available is False
    assert resolved.external_actions == 0
    assert sink.snapshot() == (attempt_event(), terminal_event(trusted))


def test_terminal_audit_survives_local_reconciliation_state_failure_and_retry():
    sink = AuditBuffer(max_entries=8)
    sim = AuditedDelegatedSimulation(
        grant(),
        session_id="sess1",
        started_at=NOW,
        audit_sink=sink,
        audit_binding=binding(),
    )
    first = attempt(sim, outcome="outcome_unknown")
    assert first.status == "outcome_unknown"
    assert first.mocked_effects == 1

    trusted = reconciliation()
    terminal = terminal_event(trusted)
    with patch.object(
        core.DelegatedSimulation,
        "reconcile",
        side_effect=RuntimeError("synthetic reconciliation state failure"),
    ):
        blocked = sim.reconcile(
            "s1",
            authoritative_outcome="verified_complete",
            reversible=False,
            reconciliation_binding=trusted,
            audit_event=terminal,
            now=RECONCILE_TIME,
        )

    assert blocked.status == "reconciliation_required"
    assert blocked.reason == "reconciliation_state_failure"
    assert blocked.mocked_effects == 0
    assert blocked.rollback_available is False
    assert blocked.external_actions == 0
    assert sink.snapshot() == (attempt_event(), terminal)

    recovered = sim.reconcile(
        "s1",
        authoritative_outcome="verified_complete",
        reversible=False,
        reconciliation_binding=trusted,
        audit_event=terminal,
        now=RECONCILE_TIME,
    )
    assert recovered.status == "verified_complete"
    assert recovered.reason == "reconciled"
    assert recovered.rollback_available is False
    assert recovered.external_actions == 0
    assert sink.snapshot() == (attempt_event(), terminal)
