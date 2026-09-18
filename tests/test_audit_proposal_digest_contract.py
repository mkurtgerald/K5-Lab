from datetime import datetime, timezone
import unittest

from mosaic_lab.audit import AuditBuffer, AuditEvent


NOW = datetime(2026, 9, 18, 21, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def event(**changes):
    values = dict(
        event_id="event1",
        request_id="req1",
        partition="part1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=(),
        evidence_digests=(),
        decision="attempted",
        reason="mocked_effect_admitted",
        outcome="attempted",
        recorded_at=NOW,
        proposal_id="proposal1",
        proposal_digest=DIGEST,
        grant_ref="grant1",
        version="5",
    )
    values.update(changes)
    return AuditEvent(**values)


class AuditProposalDigestContractTests(unittest.TestCase):
    def test_v5_carries_exact_proposal_digest_without_changing_authority(self):
        item = event()
        self.assertEqual(item.version, "5")
        self.assertEqual(item.proposal_id, "proposal1")
        self.assertEqual(item.proposal_digest, DIGEST)

    def test_v5_requires_complete_proposal_identity_and_lowercase_sha256(self):
        with self.assertRaises(ValueError):
            event(proposal_id=None)
        with self.assertRaises(ValueError):
            event(proposal_digest=None)
        with self.assertRaises(ValueError):
            event(proposal_digest="not-a-digest")
        with self.assertRaises(ValueError):
            event(proposal_digest="A" * 64)

    def test_v4_rejects_digest_to_prevent_silent_same_version_schema_drift(self):
        with self.assertRaises(ValueError):
            event(version="4")
        legacy = event(version="4", proposal_digest=None)
        self.assertEqual(legacy.version, "4")
        self.assertIsNone(legacy.proposal_digest)

    def test_event_identity_collision_detects_proposal_digest_rebinding(self):
        buffer = AuditBuffer(max_entries=2)
        self.assertTrue(buffer.append(event()))
        with self.assertRaises(ValueError):
            buffer.append(event(proposal_digest=OTHER_DIGEST))
        self.assertEqual(buffer.snapshot()[0].proposal_digest, DIGEST)


if __name__ == "__main__":
    unittest.main()
