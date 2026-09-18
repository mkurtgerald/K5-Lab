from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _scope():
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1", "rec2"),
        valid_until=NOW + timedelta(minutes=5),
    )


def _record(record_id):
    return EvidenceRecord(
        partition="p1",
        record_id=record_id,
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=1),
        text=f"synthetic {record_id}",
    )


class RetrievalCapacityPreflightTests(unittest.TestCase):
    def test_full_cache_rejects_uncached_record_before_source_read(self):
        store = SyntheticEvidenceStore()
        store.add(_record("rec1"))
        store.add(_record("rec2"))
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
            max_cache_entries=1,
        )
        first = session.retrieve(
            "req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual(first.status, "returned")
        self.assertEqual(store.read_count, 1)
        blocked = session.retrieve(
            "req2", "rec2", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual((blocked.status, blocked.reason), ("denied", "cache_capacity"))
        self.assertEqual(store.read_count, 1)
        self.assertEqual(session.cache_size, 1)
        self.assertFalse(blocked.authorized)
        self.assertFalse(blocked.execute)
        self.assertEqual(blocked.external_actions, 0)

    def test_full_cache_still_serves_cached_record_without_source_read(self):
        store = SyntheticEvidenceStore()
        store.add(_record("rec1"))
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
            max_cache_entries=1,
        )
        session.retrieve("req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW)
        replay = session.retrieve(
            "req2", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual((replay.status, replay.reason, replay.cached), ("returned", "evidence_returned", True))
        self.assertEqual(store.read_count, 1)


if __name__ == "__main__":
    unittest.main()
