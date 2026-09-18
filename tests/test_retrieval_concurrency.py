from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock, Thread
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
        text=f"synthetic {record_id}",
    )


class _BlockingSource:
    def __init__(self):
        self.entered = Event()
        self.release = Event()
        self.calls = 0
        self._lock = Lock()

    def get(self, partition, record_id):
        with self._lock:
            self.calls += 1
        self.entered.set()
        if not self.release.wait(timeout=5.0):
            raise RuntimeError("synthetic_timeout")
        return _record(record_id)


class RetrievalConcurrencyTests(unittest.TestCase):
    def test_concurrent_duplicate_record_collapses_to_one_source_read(self):
        source = _BlockingSource()
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        results = {}

        def read(name, request_id):
            results[name] = session.retrieve(
                request_id,
                "rec1",
                source,
                _scope(),
                current_policy_revision="policy1",
                now=NOW,
            )

        first = Thread(target=read, args=("first", "req1"))
        second = Thread(target=read, args=("second", "req2"))
        first.start()
        self.assertTrue(source.entered.wait(timeout=5.0))
        second.start()
        source.release.set()
        first.join(timeout=5.0)
        second.join(timeout=5.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(source.calls, 1)
        self.assertEqual(
            sorted((item.status, item.reason, item.cached) for item in results.values()),
            [
                ("returned", "evidence_returned", False),
                ("returned", "evidence_returned", True),
            ],
        )
        for item in results.values():
            self.assertFalse(item.authorized)
            self.assertFalse(item.execute)
            self.assertEqual(item.external_actions, 0)

    def test_checkpoint_cannot_observe_inflight_uncommitted_evidence(self):
        source = _BlockingSource()
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
        )
        result = {}

        def read():
            result["receipt"] = session.retrieve(
                "req1",
                "rec1",
                source,
                _scope(),
                current_policy_revision="policy1",
                now=NOW,
            )

        worker = Thread(target=read)
        worker.start()
        self.assertTrue(source.entered.wait(timeout=5.0))
        with self.assertRaises(ValueError):
            session.create_checkpoint(("rec1",), now=NOW)
        self.assertEqual(session.cache_size, 0)
        source.release.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result["receipt"].status, "returned")
        checkpoint = session.create_checkpoint(("rec1",), now=NOW)
        self.assertEqual(checkpoint.evidence_refs, ("rec1",))
        self.assertEqual(len(checkpoint.evidence_digests), 1)

    def test_concurrent_distinct_reads_preserve_bounded_cache_without_eviction(self):
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
        gate = Barrier(3)
        results = {}

        def read(record_id):
            gate.wait(timeout=5.0)
            results[record_id] = session.retrieve(
                f"req-{record_id}",
                record_id,
                store,
                _scope(),
                current_policy_revision="policy1",
                now=NOW,
            )

        first = Thread(target=read, args=("rec1",))
        second = Thread(target=read, args=("rec2",))
        first.start()
        second.start()
        gate.wait(timeout=5.0)
        first.join(timeout=5.0)
        second.join(timeout=5.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(
            sorted((item.status, item.reason) for item in results.values()),
            [("denied", "cache_capacity"), ("returned", "evidence_returned")],
        )
        self.assertEqual(session.cache_size, 1)
        returned = next(item for item in results.values() if item.status == "returned")
        replay = session.retrieve(
            "req-replay",
            returned.record_id,
            store,
            _scope(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((replay.status, replay.cached), ("returned", True))
        self.assertEqual(session.cache_size, 1)


if __name__ == "__main__":
    unittest.main()
