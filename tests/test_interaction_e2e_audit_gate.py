from dataclasses import replace
from datetime import datetime, timedelta, timezone

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger
from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditAdmissionBinding, AuditedDelegatedSimulation, DelegationGrant, SimulationStep
from mosaic_lab.interaction import EvidenceRef, TrustedAuthority, effect_digest, evaluate_proposal, parse_untrusted_proposal
from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore
from mosaic_lab.text_interaction import ActionPresentation, InteractionInput, InteractionSession, ProviderReply, run_interaction_turn

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EFFECT_TIME = NOW + timedelta(seconds=1)
STATE = "b" * 64


class Provider:
    def complete(self, request):
        return ProviderReply("ok", "answer", "provider_ok", 4, 2)


def upstream_digest():
    proposal = parse_untrusted_proposal({
        "version": "1",
        "partition": "p1",
        "request_id": "req1",
        "proposal_id": "prop1",
        "action_ref": "act1",
        "target_ref": "target1",
        "parameters": {"level": "medium"},
        "evidence_refs": ["rec1"],
        "issued_at": (NOW - timedelta(seconds=5)).isoformat(),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
    })
    digest = effect_digest(proposal)
    authority = TrustedAuthority(
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        allowed_actions=("act1",),
        allowed_targets=("target1",),
        policy_revision="policy1",
        valid_until=NOW + timedelta(minutes=5),
    )
    decision = evaluate_proposal(
        proposal,
        authority,
        evidence={"rec1": EvidenceRef("p1", "rec1", NOW - timedelta(seconds=5))},
        current_policy_revision="policy1",
        now=NOW,
    )
    assert decision.status == "recommendation"
    assert not decision.authorized and not decision.execute and decision.external_actions == 0

    approval = ApprovalRecord(
        approval_id="approval1",
        approver_ref="principal2",
        partition="p1",
        proposal_digest=digest,
        policy_revision="policy1",
        state_digest=STATE,
        profile="delegated_simulation",
        granted_at=NOW - timedelta(seconds=2),
        expires_at=NOW + timedelta(seconds=30),
    )
    approval_result = ApprovalUseLedger().validate_and_consume(
        (approval,),
        partition="p1",
        proposal_digest=digest,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        now=NOW,
    )
    assert approval_result.status == "accepted_for_simulation"
    assert not approval_result.authorized and approval_result.external_actions == 0

    store = SyntheticEvidenceStore()
    store.add(EvidenceRecord(
        partition="p1",
        record_id="rec1",
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=5),
        text="synthetic evidence",
    ))
    scope = ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        allowed_record_ids=("rec1",),
        valid_until=NOW + timedelta(minutes=5),
    )
    retrieval = RetrievalSession(
        session_id="session1",
        partition="p1",
        principal_ref="principal1",
        policy_revision="policy1",
    ).retrieve(
        "req1", "rec1", store, scope, current_policy_revision="policy1", now=NOW
    )
    assert retrieval.status == "returned"
    assert not retrieval.authorized and retrieval.external_actions == 0

    text = run_interaction_turn(
        InteractionSession(partition="p1", session_id="session1"),
        InteractionInput(
            partition="p1",
            session_id="session1",
            request_id="req1",
            text="question",
            evidence_refs=("rec1",),
            action=ActionPresentation("awaiting_approval"),
        ),
        Provider(),
    )
    assert text.status == "ok"
    assert not text.authorized and not text.execute and text.external_actions == 0
    return proposal.proposal_id, digest, approval_result.consumed_approval_ids, retrieval.content_digest


def grant(digest):
    return DelegationGrant(
        grant_id="grant1",
        principal_ref="principal1",
        partition="p1",
        proposal_digest=digest,
        policy_revision="policy1",
        state_digest=STATE,
        allowed_actions=("act1",),
        allowed_targets=("target1",),
        granted_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
        max_steps=2,
        max_duration_seconds=30.0,
        max_actions_per_minute=2,
    )


def upstream_binding(proposal_id, digest, approval_refs, evidence_digest):
    return AuditAdmissionBinding(
        proposal_id=proposal_id,
        proposal_digest=digest,
        approval_refs=approval_refs,
        evidence_refs=("rec1",),
        evidence_digests=(evidence_digest,),
    )


def admission_event(evidence_digest):
    return AuditEvent(
        event_id="effect-admission-1",
        request_id="step1",
        proposal_id="prop1",
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        grant_ref="grant1",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=("rec1",),
        decision="attempted",
        reason="mocked_effect_admitted",
        approval_ref="approval1",
        outcome="attempted",
        recorded_at=EFFECT_TIME,
        evidence_digests=(evidence_digest,),
    )


def attempt(simulation, evidence_digest, *, audit_event=None):
    return simulation.attempt_step(
        SimulationStep("step1", "delivery1", "act1", "target1"),
        now=EFFECT_TIME,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
        audit_event=audit_event or admission_event(evidence_digest),
    )


def test_end_to_end_effect_requires_successful_audit_admission():
    proposal_id, digest, approval_refs, evidence_digest = upstream_digest()
    audit = AuditBuffer(max_entries=8)
    simulation = AuditedDelegatedSimulation(
        grant(digest),
        session_id="session1",
        started_at=NOW,
        audit_sink=audit,
        audit_binding=upstream_binding(proposal_id, digest, approval_refs, evidence_digest),
    )
    receipt = attempt(simulation, evidence_digest)
    assert receipt.status == "verified_complete"
    assert receipt.mocked_effects == 1
    assert not receipt.authorized and not receipt.execute and receipt.external_actions == 0
    assert audit.snapshot() == (admission_event(evidence_digest),)


def test_end_to_end_audit_unavailable_has_zero_mocked_effects():
    proposal_id, digest, approval_refs, evidence_digest = upstream_digest()
    simulation = AuditedDelegatedSimulation(
        grant(digest),
        session_id="session1",
        started_at=NOW,
        audit_sink=None,
        audit_binding=upstream_binding(proposal_id, digest, approval_refs, evidence_digest),
    )
    receipt = attempt(simulation, evidence_digest)
    assert receipt.status == "denied"
    assert receipt.reason == "audit_unavailable"
    assert receipt.mocked_effects == 0
    assert not receipt.authorized and not receipt.execute and receipt.external_actions == 0


def test_upstream_identity_substitution_is_denied_before_audit_admission():
    proposal_id, digest, approval_refs, evidence_digest = upstream_digest()
    binding = upstream_binding(proposal_id, digest, approval_refs, evidence_digest)
    original = admission_event(evidence_digest)
    substitutions = (
        replace(original, proposal_id="other"),
        replace(original, approval_ref="other"),
        replace(original, evidence_refs=("rec2",)),
        replace(original, evidence_digests=("e" * 64,)),
    )
    for forged in substitutions:
        audit = AuditBuffer(max_entries=8)
        simulation = AuditedDelegatedSimulation(
            grant(digest),
            session_id="session1",
            started_at=NOW,
            audit_sink=audit,
            audit_binding=binding,
        )
        receipt = attempt(simulation, evidence_digest, audit_event=forged)
        assert (receipt.status, receipt.reason) == ("denied", "audit_binding_mismatch")
        assert receipt.mocked_effects == 0
        assert receipt.external_actions == 0
        assert audit.snapshot() == ()


def test_unbound_audit_construction_is_rejected():
    _, digest, _, _ = upstream_digest()
    try:
        AuditedDelegatedSimulation(
            grant(digest),
            session_id="session1",
            started_at=NOW,
            audit_sink=AuditBuffer(max_entries=8),
            audit_binding=None,
        )
    except ValueError as exc:
        assert str(exc) == "trusted audit binding required"
    else:
        raise AssertionError("unbound audited simulation construction must fail closed")


def test_binding_rejects_mismatched_digest():
    proposal_id, digest, _, evidence_digest = upstream_digest()
    binding = upstream_binding(proposal_id, "c" * 64, ("approval1",), evidence_digest)
    try:
        AuditedDelegatedSimulation(
            grant(digest),
            session_id="session1",
            started_at=NOW,
            audit_sink=AuditBuffer(max_entries=8),
            audit_binding=binding,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched upstream audit binding must fail closed")


def test_multi_approval_identity_is_carried_without_approximation():
    proposal_id, digest, _, evidence_digest = upstream_digest()
    binding = upstream_binding(
        proposal_id,
        digest,
        ("approval1", "approval2"),
        evidence_digest,
    )
    exact = replace(
        admission_event(evidence_digest),
        approval_ref=None,
        approval_refs=("approval1", "approval2"),
    )
    audit = AuditBuffer(max_entries=8)
    simulation = AuditedDelegatedSimulation(
        grant(digest),
        session_id="session1",
        started_at=NOW,
        audit_sink=audit,
        audit_binding=binding,
    )
    receipt = attempt(simulation, evidence_digest, audit_event=exact)
    assert receipt.status == "verified_complete"
    assert receipt.mocked_effects == 1
    assert audit.snapshot() == (exact,)
    assert exact.bound_approval_refs == ("approval1", "approval2")
    assert exact.version == "3"

    forged = replace(
        exact,
        event_id="effect-admission-2",
        approval_refs=("approval2", "approval1"),
    )
    audit2 = AuditBuffer(max_entries=8)
    simulation2 = AuditedDelegatedSimulation(
        grant(digest),
        session_id="session2",
        started_at=NOW,
        audit_sink=audit2,
        audit_binding=binding,
    )
    blocked = attempt(simulation2, evidence_digest, audit_event=forged)
    assert (blocked.status, blocked.reason) == ("denied", "audit_binding_mismatch")
    assert blocked.mocked_effects == 0
    assert audit2.snapshot() == ()
