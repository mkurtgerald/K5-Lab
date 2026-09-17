from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger
from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import DelegatedSimulation, DelegationGrant, SimulationStep
from mosaic_lab.interaction import (
    EvidenceRef,
    TrustedAuthority,
    effect_digest,
    evaluate_proposal,
    parse_untrusted_proposal,
)
from mosaic_lab.retrieval import (
    EvidenceRecord,
    ReadScope,
    RetrievalSession,
    SyntheticEvidenceStore,
)
from mosaic_lab.text_interaction import (
    ActionPresentation,
    InteractionInput,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
STATE = "b" * 64


def proposal_payload(**changes):
    values = {
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
        "untrusted_score": 1.0,
        "untrusted_rationale": "untrusted text",
    }
    values.update(changes)
    return values


def authority(**changes):
    values = {
        "partition": "p1",
        "principal_ref": "principal1",
        "profile": "delegated_simulation",
        "allowed_actions": ("act1",),
        "allowed_targets": ("target1",),
        "policy_revision": "policy1",
        "valid_until": NOW + timedelta(minutes=5),
        "authenticated": True,
    }
    values.update(changes)
    return TrustedAuthority(**values)


def proposal_evidence(**changes):
    values = {
        "partition": "p1",
        "record_id": "rec1",
        "observed_at": NOW - timedelta(seconds=5),
    }
    values.update(changes)
    return {"rec1": EvidenceRef(**values)}


def read_scope(**changes):
    values = {
        "partition": "p1",
        "principal_ref": "principal1",
        "profile": "delegated_simulation",
        "policy_revision": "policy1",
        "allowed_record_ids": ("rec1",),
        "valid_until": NOW + timedelta(minutes=5),
    }
    values.update(changes)
    return ReadScope(**values)


def evidence_record(**changes):
    values = {
        "partition": "p1",
        "record_id": "rec1",
        "source_ref": "source1",
        "observed_at": NOW - timedelta(seconds=5),
        "text": "untrusted evidence text",
        "origin": "record",
    }
    values.update(changes)
    return EvidenceRecord(**values)


def approval(proposal_digest, **changes):
    values = {
        "approval_id": "approval1",
        "approver_ref": "principal2",
        "partition": "p1",
        "proposal_digest": proposal_digest,
        "policy_revision": "policy1",
        "state_digest": STATE,
        "profile": "delegated_simulation",
        "granted_at": NOW - timedelta(seconds=2),
        "expires_at": NOW + timedelta(seconds=30),
    }
    values.update(changes)
    return ApprovalRecord(**values)


def grant(proposal_digest, **changes):
    values = {
        "grant_id": "grant1",
        "principal_ref": "principal1",
        "partition": "p1",
        "proposal_digest": proposal_digest,
        "policy_revision": "policy1",
        "state_digest": STATE,
        "allowed_actions": ("act1",),
        "allowed_targets": ("target1",),
        "granted_at": NOW - timedelta(seconds=1),
        "expires_at": NOW + timedelta(minutes=1),
        "max_steps": 2,
        "max_duration_seconds": 30.0,
        "max_actions_per_minute": 2,
    }
    values.update(changes)
    return DelegationGrant(**values)


def audit_event(event_id, *, decision, reason, outcome, proposal_id="prop1", approval_ref="approval1"):
    return AuditEvent(
        event_id=event_id,
        request_id="req1",
        proposal_id=proposal_id,
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        grant_ref="grant1",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=("rec1",),
        decision=decision,
        reason=reason,
        approval_ref=approval_ref,
        outcome=outcome,
        recorded_at=NOW,
    )


class Provider:
    def __init__(self, *, raises=False):
        self.raises = raises
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.raises:
            raise RuntimeError("synthetic")
        return ProviderReply("ok", "answer", "provider_ok", 4, 2)


class MaliciousSource:
    def get(self, partition, record_id):
        return evidence_record(partition="p2")


class EndToEndInteractionSafetyTests(unittest.TestCase):
    def assert_non_authorizing(self, receipt):
        self.assertFalse(receipt.authorized)
        self.assertFalse(receipt.execute)
        self.assertEqual(receipt.external_actions, 0)

    def test_positive_synthetic_path_stays_non_authorizing_and_audited(self):
        proposal = parse_untrusted_proposal(proposal_payload())
        digest = effect_digest(proposal)
        proposal_receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=proposal_evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((proposal_receipt.status, proposal_receipt.reason), ("recommendation", "simulation_only"))
        self.assert_non_authorizing(proposal_receipt)

        approval_receipt = ApprovalUseLedger().validate_and_consume(
            (approval(digest),),
            partition="p1",
            proposal_digest=digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual(approval_receipt.status, "accepted_for_simulation")
        self.assert_non_authorizing(approval_receipt)

        store = SyntheticEvidenceStore()
        store.add(evidence_record())
        retrieval = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        ).retrieve(
            "req1",
            "rec1",
            store,
            read_scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual(retrieval.status, "returned")
        self.assert_non_authorizing(retrieval)

        provider = Provider()
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
            provider,
        )
        self.assertEqual(text.status, "ok")
        self.assert_non_authorizing(text)

        simulation = DelegatedSimulation(grant(digest), session_id="session1", started_at=NOW)
        step = simulation.attempt_step(
            SimulationStep(step_id="step1", delivery_id="delivery1", action_ref="act1", target_ref="target1"),
            now=NOW + timedelta(seconds=1),
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            authority_available=True,
            cancelled=False,
            grant_revoked=False,
            mocked_outcome="verified_complete",
            reversible=True,
        )
        self.assertEqual(step.mocked_effects, 1)
        self.assert_non_authorizing(step)

        audit = AuditBuffer()
        for item in (
            audit_event("event1", decision="proposed", reason="simulation_only", outcome="proposed", approval_ref="approval1"),
            audit_event("event2", decision="returned", reason="trusted_approval_bound", outcome="awaiting_approval"),
            audit_event("event3", decision="returned", reason="evidence_returned", outcome="not_applicable"),
            audit_event("event4", decision="returned", reason="provider_ok", outcome="not_applicable"),
            audit_event("event5", decision="attempted", reason="mock_verified", outcome="verified_complete"),
        ):
            self.assertTrue(audit.append(item))
        self.assertEqual(len(audit.snapshot()), 5)

    def test_forged_authority_cross_partition_and_revoked_approval_have_zero_mocked_effects(self):
        forged = proposal_payload(approved=True)
        with self.assertRaises(ValueError):
            parse_untrusted_proposal(forged)

        proposal = parse_untrusted_proposal(proposal_payload())
        digest = effect_digest(proposal)
        retrieval = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        ).retrieve(
            "req1",
            "rec1",
            MaliciousSource(),
            read_scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((retrieval.status, retrieval.reason), ("denied", "cross_partition_evidence"))
        self.assert_non_authorizing(retrieval)

        approval_receipt = ApprovalUseLedger().validate_and_consume(
            (approval(digest, revoked=True),),
            partition="p1",
            proposal_digest=digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual((approval_receipt.status, approval_receipt.reason), ("denied", "approval_revoked"))
        self.assert_non_authorizing(approval_receipt)

        audit = AuditBuffer()
        self.assertTrue(audit.append(audit_event("event1", decision="denied", reason="invalid_proposal", outcome="denied")))
        self.assertTrue(audit.append(audit_event("event2", decision="denied", reason="cross_partition_evidence", outcome="denied")))
        self.assertTrue(audit.append(audit_event("event3", decision="denied", reason="approval_revoked", outcome="denied")))
        self.assertEqual(len(audit.snapshot()), 3)

    def test_state_change_provider_failure_and_ambiguous_retry_fail_closed(self):
        proposal = parse_untrusted_proposal(proposal_payload())
        digest = effect_digest(proposal)
        simulation = DelegatedSimulation(grant(digest), session_id="session1", started_at=NOW)
        denied = simulation.attempt_step(
            SimulationStep(step_id="step1", delivery_id="delivery1", action_ref="act1", target_ref="target1"),
            now=NOW + timedelta(seconds=1),
            current_policy_revision="policy1",
            current_state_digest="c" * 64,
            current_profile="delegated_simulation",
            authority_available=True,
            cancelled=False,
            grant_revoked=False,
            mocked_outcome="verified_complete",
            reversible=True,
        )
        self.assertEqual((denied.status, denied.reason), ("denied", "state_changed"))
        self.assertEqual(denied.mocked_effects, 0)
        self.assert_non_authorizing(denied)

        provider = Provider(raises=True)
        interaction = run_interaction_turn(
            InteractionSession(partition="p1", session_id="session1"),
            InteractionInput(
                partition="p1",
                session_id="session1",
                request_id="req1",
                text="question",
                evidence_refs=("rec1",),
                action=ActionPresentation("awaiting_approval"),
            ),
            provider,
        )
        self.assertEqual((interaction.status, interaction.reason), ("error", "provider_exception"))
        self.assert_non_authorizing(interaction)

        ambiguous_session = DelegatedSimulation(grant(digest), session_id="session2", started_at=NOW)
        first = ambiguous_session.attempt_step(
            SimulationStep(step_id="step1", delivery_id="delivery1", action_ref="act1", target_ref="target1"),
            now=NOW + timedelta(seconds=1),
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            authority_available=True,
            cancelled=False,
            grant_revoked=False,
            mocked_outcome="outcome_unknown",
            reversible=False,
        )
        self.assertEqual(first.status, "outcome_unknown")
        retry = ambiguous_session.attempt_step(
            SimulationStep(step_id="step1", delivery_id="delivery2", action_ref="act1", target_ref="target1"),
            now=NOW + timedelta(seconds=2),
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            authority_available=True,
            cancelled=False,
            grant_revoked=False,
            mocked_outcome="verified_complete",
            reversible=False,
        )
        self.assertEqual((retry.status, retry.reason), ("reconciliation_required", "ambiguous_prior_outcome"))
        self.assertEqual(retry.mocked_effects, 0)
        self.assert_non_authorizing(retry)

        audit = AuditBuffer()
        self.assertTrue(audit.append(audit_event("event1", decision="denied", reason="state_changed", outcome="denied")))
        self.assertTrue(audit.append(audit_event("event2", decision="failed", reason="provider_exception", outcome="failed")))
        self.assertTrue(audit.append(audit_event("event3", decision="attempted", reason="ambiguous_outcome", outcome="outcome_unknown")))
        self.assertEqual(len(audit.snapshot()), 3)


if __name__ == "__main__":
    unittest.main()
