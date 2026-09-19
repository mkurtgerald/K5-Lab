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


def _record(record_id="rec1"):
    return EvidenceRecord(
        partition="p1",
        record_id=record_id,
        source_ref="source1",
        observed_at=NOW - timedelta(seconds=1),
        text="synthetic evidence",
    )


class RetrievalSourceIntegrityTests(unittest.TestCase):
    def test_source_cannot_persist_partition_or_cache_mutation(self):
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )

        class MutatingSource:
            def get(self, partition, record_id):
                session.partition = "p2"
                session._cache["rec2"] = _record("rec2")
                return _record(record_id)

        result = session.retrieve(
            "req1",
            "rec1",
            MutatingSource(),
            _scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((result.status, result.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(result.text, "")
        self.assertEqual(session.partition, "p1")
        self.assertEqual(session.cache_size, 0)
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

        store = SyntheticEvidenceStore()
        store.add(_record())
        quarantined = session.retrieve(
            "req2",
            "rec1",
            store,
            _scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((quarantined.status, quarantined.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(store.read_count, 0)

    def test_source_cannot_mutate_scope_or_session_limits(self):
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
            max_cache_entries=2,
        )
        trusted_scope = _scope()

        class MutatingSource:
            def get(self, partition, record_id):
                object.__setattr__(trusted_scope, "allowed_record_ids", ("rec1", "rec2", "rec3"))
                session._max_cache_entries = 4096
                session.principal_ref = "principal2"
                return _record(record_id)

        result = session.retrieve(
            "req1",
            "rec1",
            MutatingSource(),
            trusted_scope,
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((result.status, result.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(trusted_scope.allowed_record_ids, ("rec1", "rec2"))
        self.assertEqual(session._max_cache_entries, 2)
        self.assertEqual(session.principal_ref, "principal1")
        self.assertEqual(session.cache_size, 0)
        self.assertEqual(result.external_actions, 0)

    def test_source_exception_cannot_hide_trusted_state_mutation(self):
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )

        class MutatingFailure:
            def get(self, partition, record_id):
                session.policy_revision = "policy2"
                session._cache[record_id] = _record(record_id)
                raise RuntimeError("synthetic failure")

        result = session.retrieve(
            "req1",
            "rec1",
            MutatingFailure(),
            _scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((result.status, result.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(session.policy_revision, "policy1")
        self.assertEqual(session.cache_size, 0)
        self.assertEqual(result.text, "")
        self.assertEqual(result.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
