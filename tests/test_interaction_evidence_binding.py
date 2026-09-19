from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.interaction import (
    EvidenceRef,
    TrustedAuthority,
    evaluate_proposal,
    parse_untrusted_proposal,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


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
        profile="approval_required",
        allowed_actions=("act1",),
        allowed_targets=("target1",),
        policy_revision="policy1",
        valid_until=NOW + timedelta(minutes=5),
    )


class InteractionEvidenceBindingTests(unittest.TestCase):
    def test_mapping_key_cannot_substitute_different_evidence_identity(self):
        receipt = evaluate_proposal(
            proposal(),
            authority(),
            evidence={
                "rec1": EvidenceRef(
                    partition="p1",
                    record_id="rec2",
                    observed_at=NOW - timedelta(seconds=10),
                )
            },
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "reference_mismatch"))
        self.assertFalse(receipt.authorized)
        self.assertFalse(receipt.execute)
        self.assertEqual(receipt.external_actions, 0)

    def test_evidence_mapping_requires_typed_reference(self):
        class ForgedEvidence:
            partition = "p1"
            record_id = "rec1"
            observed_at = NOW - timedelta(seconds=10)

        receipt = evaluate_proposal(
            proposal(),
            authority(),
            evidence={"rec1": ForgedEvidence()},  # type: ignore[dict-item]
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "invalid_evidence_type"))
        self.assertFalse(receipt.authorized)
        self.assertFalse(receipt.execute)
        self.assertEqual(receipt.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
