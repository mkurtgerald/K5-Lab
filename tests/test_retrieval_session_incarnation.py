from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def scope() -> ReadScope:
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1",),
        valid_until=NOW + timedelta(minutes=5),
    )


def store() -> SyntheticEvidenceStore:
    source = SyntheticEvidenceStore()
    source.add(
        EvidenceRecord(
            partition="p1",
            record_id="rec1",
            source_ref="source1",
            observed_at=NOW - timedelta(seconds=1),
            text="synthetic evidence",
        )
    )
    return source


class RetrievalSessionIncarnationTests(unittest.TestCase):
    def test_identical_public_session_identity_cannot_reuse_foreign_checkpoint(self):
        source = store()
        first = RetrievalSession(
            session_id="sharedsession",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        second = RetrievalSession(
            session_id="sharedsession",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        trusted_scope = scope()

        self.assertEqual(
            first.retrieve("request1", "rec1", source, trusted_scope, current_policy_revision="policy1", now=NOW).status,
            "returned",
        )
        self.assertEqual(
            second.retrieve("request2", "rec1", source, trusted_scope, current_policy_revision="policy1", now=NOW).status,
            "returned",
        )

        checkpoint = first.create_checkpoint(("rec1",), now=NOW)
        foreign = second.validate_checkpoint(
            checkpoint,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )
        owner = first.validate_checkpoint(
            checkpoint,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )

        self.assertEqual((foreign.status, foreign.reason), ("denied", "checkpoint_session_mismatch"))
        self.assertEqual((owner.status, owner.reason), ("accepted_for_read", "checkpoint_valid"))
        self.assertFalse(foreign.authorized)
        self.assertFalse(foreign.execute)
        self.assertEqual(foreign.external_actions, 0)

    def test_source_callback_cannot_replace_session_incarnation(self):
        session = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        original_incarnation = session._session_incarnation
        item = EvidenceRecord(
            partition="p1",
            record_id="rec1",
            source_ref="source1",
            observed_at=NOW - timedelta(seconds=1),
            text="synthetic evidence",
        )

        class MutatingSource:
            def get(self, partition, record_id):
                session._session_incarnation = "forgedincarnation"
                return item

        result = session.retrieve(
            "request1",
            "rec1",
            MutatingSource(),
            scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        later = session.retrieve(
            "request2",
            "rec1",
            store(),
            scope(),
            current_policy_revision="policy1",
            now=NOW,
        )

        self.assertEqual((result.status, result.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(session._session_incarnation, original_incarnation)
        self.assertEqual((later.status, later.reason), ("denied", "session_integrity_failure"))
        for receipt in (result, later):
            self.assertFalse(receipt.authorized)
            self.assertFalse(receipt.execute)
            self.assertEqual(receipt.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
