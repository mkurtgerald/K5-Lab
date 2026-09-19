from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def scope(partition: str, principal_ref: str) -> ReadScope:
    return ReadScope(
        partition=partition,
        principal_ref=principal_ref,
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1",),
        valid_until=NOW + timedelta(minutes=5),
    )


def record(partition: str, text: str) -> EvidenceRecord:
    return EvidenceRecord(
        partition=partition,
        record_id="rec1",
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=1),
        text=text,
    )


class RetrievalCrossSessionIsolationTests(unittest.TestCase):
    def test_shared_source_same_record_identity_remains_partition_isolated(self):
        store = SyntheticEvidenceStore()
        store.add(record("p1", "synthetic partition one"))
        store.add(record("p2", "synthetic partition two"))

        first = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        second = RetrievalSession(
            session_id="session2",
            partition="p2",
            principal_ref="principal2",
            policy_revision="policy1",
        )

        first_result = first.retrieve(
            "request1",
            "rec1",
            store,
            scope("p1", "principal1"),
            current_policy_revision="policy1",
            now=NOW,
        )
        second_result = second.retrieve(
            "request2",
            "rec1",
            store,
            scope("p2", "principal2"),
            current_policy_revision="policy1",
            now=NOW,
        )

        self.assertEqual((first_result.status, first_result.text), ("returned", "synthetic partition one"))
        self.assertEqual((second_result.status, second_result.text), ("returned", "synthetic partition two"))
        self.assertNotEqual(first_result.content_digest, second_result.content_digest)
        for result in (first_result, second_result):
            self.assertFalse(result.authorized)
            self.assertFalse(result.execute)
            self.assertEqual(result.external_actions, 0)

    def test_foreign_checkpoint_is_denied_even_with_matching_partition_principal_policy_and_cache(self):
        store = SyntheticEvidenceStore()
        store.add(record("p1", "synthetic shared evidence"))

        owner = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        peer = RetrievalSession(
            session_id="session2",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        trusted_scope = scope("p1", "principal1")

        self.assertEqual(
            owner.retrieve(
                "request1",
                "rec1",
                store,
                trusted_scope,
                current_policy_revision="policy1",
                now=NOW,
            ).status,
            "returned",
        )
        self.assertEqual(
            peer.retrieve(
                "request2",
                "rec1",
                store,
                trusted_scope,
                current_policy_revision="policy1",
                now=NOW,
            ).status,
            "returned",
        )

        checkpoint = owner.create_checkpoint(("rec1",), now=NOW)
        foreign = peer.validate_checkpoint(
            checkpoint,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )
        owner_result = owner.validate_checkpoint(
            checkpoint,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )

        self.assertEqual((foreign.status, foreign.reason), ("denied", "checkpoint_session_mismatch"))
        self.assertEqual((owner_result.status, owner_result.reason), ("accepted_for_read", "checkpoint_valid"))
        self.assertFalse(foreign.authorized)
        self.assertFalse(foreign.execute)
        self.assertEqual(foreign.external_actions, 0)

    def test_cached_evidence_objects_are_not_aliased_across_sessions(self):
        store = SyntheticEvidenceStore()
        store.add(record("p1", "synthetic original"))
        trusted_scope = scope("p1", "principal1")

        first = RetrievalSession(
            session_id="session1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        second = RetrievalSession(
            session_id="session2",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )

        first_result = first.retrieve(
            "request1",
            "rec1",
            store,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )
        second_result = second.retrieve(
            "request2",
            "rec1",
            store,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual(first_result.text, "synthetic original")
        self.assertEqual(second_result.text, "synthetic original")

        object.__setattr__(first._cache["rec1"], "text", "synthetic changed")
        second_cached = second.retrieve(
            "request3",
            "rec1",
            store,
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )

        self.assertEqual(
            (second_cached.status, second_cached.reason, second_cached.cached),
            ("returned", "evidence_returned", True),
        )
        self.assertEqual(second_cached.text, "synthetic original")
        self.assertEqual(second_cached.content_digest, second_result.content_digest)
        self.assertFalse(second_cached.authorized)
        self.assertFalse(second_cached.execute)
        self.assertEqual(second_cached.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
