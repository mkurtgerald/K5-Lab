from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger
from mosaic_lab.delegation import DelegatedSimulation, DelegationGrant, SimulationStep
from mosaic_lab.evidence_binding import EvidenceContentBinding, bind_proposal_evidence
from mosaic_lab.interaction import EvidenceRef, TrustedAuthority, evaluate_proposal, parse_untrusted_proposal
from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
STATE = "d" * 64


def proposal():
    return parse_untrusted_proposal(
        {
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
        }
    )


def authority():
    return TrustedAuthority(
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        allowed_actions=("act1",),
        allowed_targets=("target1",),
        policy_revision="policy1",
        valid_until=NOW + timedelta(minutes=5),
        authenticated=True,
    )


def scope():
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        allowed_record_ids=("rec1",),
        valid_until=NOW + timedelta(minutes=5),
    )


def record(text):
    return EvidenceRecord(
        partition="p1",
        record_id="rec1",
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=5),
        text=text,
        origin="record",
    )


def retrieve(text, *, session_id, request_id):
    store = SyntheticEvidenceStore()
    store.add(record(text))
    receipt = RetrievalSession(
        session_id=session_id,
        partition="p1",
        principal_ref="principal1",
        policy_revision="policy1",
    ).retrieve(
        request_id,
        "rec1",
        store,
        scope(),
        current_policy_revision="policy1",
        now=NOW,
    )
    if receipt.status != "returned":
        raise AssertionError(receipt)
    return receipt


def bind(candidate, receipt):
    return bind_proposal_evidence(
        candidate,
        {
            "rec1": EvidenceContentBinding(
                partition=receipt.partition,
                record_id=receipt.record_id,
                content_digest=receipt.content_digest,
                observed_at=receipt.observed_at,
            )
        },
    )


def approval(digest):
    return ApprovalRecord(
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


class ContentBoundReplayChainTests(unittest.TestCase):
    def assert_non_authorizing(self, receipt):
        self.assertFalse(receipt.authorized)
        self.assertFalse(receipt.execute)
        self.assertEqual(receipt.external_actions, 0)

    def test_retrieved_content_digest_binds_approval_and_delegation_chain(self):
        candidate = proposal()
        evaluation = evaluate_proposal(
            candidate,
            authority(),
            evidence={"rec1": EvidenceRef(partition="p1", record_id="rec1", observed_at=NOW - timedelta(seconds=5))},
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((evaluation.status, evaluation.reason), ("recommendation", "simulation_only"))
        self.assert_non_authorizing(evaluation)

        first_receipt = retrieve("synthetic evidence", session_id="session1", request_id="read1")
        first_bound = bind(candidate, first_receipt)
        trusted_approval = approval(first_bound.bound_digest)
        accepted = ApprovalUseLedger().validate_and_consume(
            (trusted_approval,),
            partition="p1",
            proposal_digest=first_bound.bound_digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual((accepted.status, accepted.reason), ("accepted_for_simulation", "trusted_approval_bound"))
        self.assert_non_authorizing(accepted)

        simulation = DelegatedSimulation(grant(first_bound.bound_digest), session_id="session1", started_at=NOW)
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

        substituted_receipt = retrieve("substituted evidence", session_id="session2", request_id="read2")
        substituted_bound = bind(candidate, substituted_receipt)
        self.assertEqual(first_bound.base_proposal_digest, substituted_bound.base_proposal_digest)
        self.assertNotEqual(first_bound.bound_digest, substituted_bound.bound_digest)

        denied = ApprovalUseLedger().validate_and_consume(
            (trusted_approval,),
            partition="p1",
            proposal_digest=substituted_bound.bound_digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual((denied.status, denied.reason), ("denied", "proposal_changed"))
        self.assert_non_authorizing(denied)


if __name__ == "__main__":
    unittest.main()
