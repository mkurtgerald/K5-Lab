from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.evidence_binding import (
    EvidenceContentBinding,
    bind_proposal_evidence,
)
from mosaic_lab.interaction import ProposalEnvelope

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


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


if __name__ == "__main__":
    unittest.main()
