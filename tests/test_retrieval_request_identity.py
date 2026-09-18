from datetime import datetime, timedelta, timezone
from threading import Lock
import unittest

from mosaic_lab.request_ledger import RequestBinding
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


def _session(**kwargs):
    return RetrievalSession(
        session_id="s1",
        partition="p1",
        principal_ref="principal1",
        policy_revision="policy1",
        **kwargs,
    )


class _MutatingSource:
    def __init__(self, session):
        self.session = session
        self.calls = 0

    def get(self, partition, record_id):
        self.calls += 1
        self.session._request_ledger._bindings["evil"] = RequestBinding(
            request_id="evil",
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
            operation="retrieve",
            subject_ref="rec2",
        )
        self.session._request_ledger._lock = Lock()
        return _record(record_id)


class RetrievalRequestIdentityTests(unittest.TestCase):
    def test_exact_request_replay_is_denied_before_cached_return(self):
        store = SyntheticEvidenceStore()
        store.add(_record("rec1"))
        session = _session()

        first = session.retrieve(
            "req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        replay = session.retrieve(
            "req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )

        self.assertEqual((first.status, first.reason), ("returned", "evidence_returned"))
        self.assertEqual((replay.status, replay.reason), ("denied", "request_replayed"))
        self.assertEqual(store.read_count, 1)
        self.assertFalse(replay.authorized)
        self.assertFalse(replay.execute)
        self.assertEqual(replay.external_actions, 0)

    def test_request_identity_collision_is_denied_before_new_source_read(self):
        store = SyntheticEvidenceStore()
        store.add(_record("rec1"))
        store.add(_record("rec2"))
        session = _session()

        first = session.retrieve(
            "req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        collision = session.retrieve(
            "req1", "rec2", store, _scope(), current_policy_revision="policy1", now=NOW
        )

        self.assertEqual(first.status, "returned")
        self.assertEqual((collision.status, collision.reason), ("denied", "request_identity_collision"))
        self.assertEqual(store.read_count, 1)

    def test_request_ledger_capacity_fails_closed_before_cached_return(self):
        store = SyntheticEvidenceStore()
        store.add(_record("rec1"))
        session = _session(max_request_entries=1)

        first = session.retrieve(
            "req1", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )
        blocked = session.retrieve(
            "req2", "rec1", store, _scope(), current_policy_revision="policy1", now=NOW
        )

        self.assertEqual(first.status, "returned")
        self.assertEqual((blocked.status, blocked.reason), ("denied", "request_ledger_capacity"))
        self.assertEqual(store.read_count, 1)

    def test_source_cannot_mutate_request_replay_state(self):
        session = _session()
        source = _MutatingSource(session)

        receipt = session.retrieve(
            "req1", "rec1", source, _scope(), current_policy_revision="policy1", now=NOW
        )

        self.assertEqual((receipt.status, receipt.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(source.calls, 1)
        self.assertEqual(
            tuple(request_id for request_id, _ in session._request_ledger.snapshot().bindings),
            ("req1",),
        )
        second = session.retrieve(
            "req2", "rec1", source, _scope(), current_policy_revision="policy1", now=NOW
        )
        self.assertEqual((second.status, second.reason), ("denied", "session_integrity_failure"))
        self.assertEqual(source.calls, 1)


if __name__ == "__main__":
    unittest.main()
