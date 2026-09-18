from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger
from mosaic_lab.evidence_binding import (
    EvidenceContentBinding,
    bind_proposal_evidence,
)
from mosaic_lab.interaction import ProposalEnvelope
from mosaic_lab.retrieval import RetrievalReceipt

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
STATE = "c" * 64


def proposal(*, evidence_refs=("rec1",)):
    return ProposalEnvelope(
        partition="p1",
        request_id="req1",
        proposal_id="prop1",
        action_ref="act1",
        target_ref="target1",
        parameters=(("level", "medium"),),
        evidence_refs=evidence_refs,
        issued_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=30),
    )


def binding(record_id="rec1", *, digest="a" * 64, partition="p1", observed_at=None):
    return EvidenceContentBinding(
        partition=partition,
        record_id=record_id,
        content_digest=digest,
        observed_at=observed_at or NOW - timedelta(seconds=5),
    )


def retrieval_receipt(*, digest="a" * 64, text="synthetic evidence", observed_at=None):
    return RetrievalReceipt(
        status="returned",
        reason="evidence_returned",
        request_id="read1",
        partition="p1",
        record_id="rec1",
        text=text,
        content_digest=digest,
        observed_at=observed_at or NOW - timedelta(seconds=5),
    )


def binding_from_receipt(receipt):
    return EvidenceContentBinding(
        partition=receipt.partition,
        record_id=receipt.record_id,
        content_digest=receipt.content_digest,
        observed_at=receipt.observed_at,
    )


def approval_record(proposal_digest):
    return ApprovalRecord(
        approval_id="approval1",
        approver_ref="principal2",
        partition="p1",
        proposal_digest=proposal_digest,
        policy_revision="policy1",
        state_digest=STATE,
        profile="delegated_simulation",
        granted_at=NOW - timedelta(seconds=2),
        expires_at=NOW + timedelta(seconds=30),
    )


class EvidenceContentBindingTests(unittest.TestCase):
    def test_same_identity_and_time_but_changed_content_changes_bound_digest(self):
        first = bind_proposal_evidence(proposal(), {"rec1": binding(digest="a" * 64)})
        second = bind_proposal_evidence(proposal(), {"rec1": binding(digest="b" * 64)})
        self.assertNotEqual(first.bound_digest, second.bound_digest)
        self.assertEqual(first.base_proposal_digest, second.base_proposal_digest)
        self.assertFalse(first.authorized)
        self.assertFalse(first.execute)
        self.assertEqual(first.external_actions, 0)

    def test_binding_is_deterministic_in_proposal_reference_order(self):
        candidate = proposal(evidence_refs=("rec2", "rec1"))
        first = bind_proposal_evidence(
            candidate,
            {"rec1": binding("rec1", digest="a" * 64), "rec2": binding("rec2", digest="b" * 64)},
        )
        second = bind_proposal_evidence(
            candidate,
            {"rec2": binding("rec2", digest="b" * 64), "rec1": binding("rec1", digest="a" * 64)},
        )
        self.assertEqual(first, second)
        self.assertEqual(first.evidence_refs, ("rec2", "rec1"))

    def test_missing_or_extra_binding_fails_closed(self):
        candidate = proposal()
        with self.assertRaises(ValueError):
            bind_proposal_evidence(candidate, {})
        with self.assertRaises(ValueError):
            bind_proposal_evidence(
                candidate,
                {"rec1": binding(), "rec2": binding("rec2", digest="b" * 64)},
            )

    def test_identity_and_partition_substitution_fail_closed(self):
        candidate = proposal()
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            bind_proposal_evidence(candidate, {"rec1": binding("rec2")})
        with self.assertRaisesRegex(ValueError, "cross-partition"):
            bind_proposal_evidence(candidate, {"rec1": binding(partition="p2")})

    def test_duck_typed_binding_is_rejected(self):
        class Forged:
            partition = "p1"
            record_id = "rec1"
            content_digest = "a" * 64
            observed_at = NOW

        with self.assertRaisesRegex(ValueError, "trusted evidence-content binding required"):
            bind_proposal_evidence(proposal(), {"rec1": Forged()})

    def test_observation_time_is_part_of_exact_binding(self):
        first = bind_proposal_evidence(
            proposal(),
            {"rec1": binding(observed_at=NOW - timedelta(seconds=5))},
        )
        second = bind_proposal_evidence(
            proposal(),
            {"rec1": binding(observed_at=NOW - timedelta(seconds=4))},
        )
        self.assertNotEqual(first.bound_digest, second.bound_digest)

    def test_retrieval_digest_is_consumed_by_approval_and_substitution_is_denied(self):
        candidate = proposal()
        returned = retrieval_receipt(digest="a" * 64)
        original = bind_proposal_evidence(
            candidate,
            {"rec1": binding_from_receipt(returned)},
        )
        approval = approval_record(original.bound_digest)
        accepted = ApprovalUseLedger().validate_and_consume(
            (approval,),
            partition="p1",
            proposal_digest=original.bound_digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual((accepted.status, accepted.reason), ("accepted_for_simulation", "trusted_approval_bound"))
        self.assertFalse(accepted.authorized)
        self.assertFalse(accepted.execute)
        self.assertEqual(accepted.external_actions, 0)

        substituted = retrieval_receipt(digest="b" * 64)
        rebound = bind_proposal_evidence(
            candidate,
            {"rec1": binding_from_receipt(substituted)},
        )
        self.assertEqual(original.base_proposal_digest, rebound.base_proposal_digest)
        self.assertNotEqual(original.bound_digest, rebound.bound_digest)

        denied = ApprovalUseLedger().validate_and_consume(
            (approval,),
            partition="p1",
            proposal_digest=rebound.bound_digest,
            current_policy_revision="policy1",
            current_state_digest=STATE,
            current_profile="delegated_simulation",
            now=NOW,
        )
        self.assertEqual((denied.status, denied.reason), ("denied", "proposal_changed"))
        self.assertFalse(denied.authorized)
        self.assertFalse(denied.execute)
        self.assertEqual(denied.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
