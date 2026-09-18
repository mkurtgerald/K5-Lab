from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def scope():
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1", "rec2"),
        valid_until=NOW + timedelta(minutes=5),
    )


def record(record_id="rec1"):
    return EvidenceRecord(
        partition="p1",
        record_id=record_id,
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=1),
        text="synthetic original",
    )


class RetrievalPartitionIntegrityTests(unittest.TestCase):
    def test_source_retained_record_mutation_cannot_change_cached_evidence(self):
        retained = record()

        class Source:
            def get(self, partition, record_id):
                return retained

        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        first = session.retrieve(
            "req1", "rec1", Source(), scope(), current_policy_revision="policy1", now=NOW
        )
        original_digest = first.content_digest
        object.__setattr__(retained, "text", "synthetic changed")
        second = session.retrieve(
            "req2", "rec1", Source(), scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual(
            (second.status, second.reason, second.cached),
            ("returned", "evidence_returned", True),
        )
        self.assertEqual(second.text, "synthetic original")
        self.assertEqual(second.content_digest, original_digest)
        self.assertFalse(second.authorized)
        self.assertFalse(second.execute)
        self.assertEqual(second.external_actions, 0)

    def test_mutated_checkpoint_shape_denies_before_cache_scan(self):
        store = SyntheticEvidenceStore()
        store.add(record())
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        self.assertEqual(
            session.retrieve(
                "req1", "rec1", store, scope(), current_policy_revision="policy1", now=NOW
            ).status,
            "returned",
        )
        checkpoint = session.create_checkpoint(("rec1",), now=NOW)
        object.__setattr__(checkpoint, "evidence_refs", tuple(f"r{i}" for i in range(129)))
        result = session.validate_checkpoint(
            checkpoint, scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual(
            (result.status, result.reason, result.evidence_refs),
            ("denied", "invalid_checkpoint", ()),
        )
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

    def test_mutated_scope_shape_is_revalidated_for_checkpoint(self):
        store = SyntheticEvidenceStore()
        store.add(record())
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        trusted_scope = scope()
        self.assertEqual(
            session.retrieve(
                "req1",
                "rec1",
                store,
                trusted_scope,
                current_policy_revision="policy1",
                now=NOW,
            ).status,
            "returned",
        )
        checkpoint = session.create_checkpoint(("rec1",), now=NOW)
        object.__setattr__(
            trusted_scope,
            "allowed_record_ids",
            tuple(f"r{i}" for i in range(129)),
        )
        result = session.validate_checkpoint(
            checkpoint, trusted_scope, current_policy_revision="policy1", now=NOW
        )
        self.assertEqual(
            (result.status, result.reason, result.evidence_refs),
            ("denied", "invalid_scope", ()),
        )
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

    def test_evidence_subclass_is_not_accepted_across_source_boundary(self):
        class DerivedEvidence(EvidenceRecord):
            pass

        item = DerivedEvidence(
            partition="p1",
            record_id="rec1",
            source_ref="source1",
            observed_at=NOW - timedelta(seconds=1),
            text="synthetic",
        )

        class Source:
            def get(self, partition, record_id):
                return item

        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        result = session.retrieve(
            "req1", "rec1", Source(), scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual(
            (result.status, result.reason),
            ("denied", "invalid_evidence_type"),
        )
        self.assertEqual(session.cache_size, 0)


if __name__ == "__main__":
    unittest.main()
