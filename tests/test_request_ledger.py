import threading
import unittest

from mosaic_lab.request_ledger import BoundedRequestLedger, RequestBinding


def binding(request_id="req1", *, record_id="rec1"):
    return RequestBinding(
        request_id=request_id,
        session_id="session1",
        partition="partition1",
        principal_ref="principal1",
        policy_revision="policy1",
        operation="retrieve",
        subject_ref=record_id,
    )


class RequestLedgerTests(unittest.TestCase):
    def test_exact_replay_is_denied_without_new_admission(self):
        ledger = BoundedRequestLedger(max_entries=2)
        first = ledger.admit(binding())
        replay = ledger.admit(binding())
        self.assertEqual((first.status, first.reason), ("accepted", "request_bound"))
        self.assertEqual((replay.status, replay.reason), ("denied", "request_replayed"))
        self.assertEqual(ledger.entry_count, 1)
        self.assertFalse(replay.authorized)
        self.assertFalse(replay.execute)
        self.assertEqual(replay.external_actions, 0)

    def test_request_identity_collision_is_denied(self):
        ledger = BoundedRequestLedger(max_entries=2)
        ledger.admit(binding())
        collision = ledger.admit(binding(record_id="rec2"))
        self.assertEqual((collision.status, collision.reason), ("denied", "request_identity_collision"))
        self.assertEqual(collision.binding.subject_ref, "rec1")
        self.assertEqual(ledger.entry_count, 1)

    def test_capacity_fails_closed_without_eviction(self):
        ledger = BoundedRequestLedger(max_entries=1)
        ledger.admit(binding())
        blocked = ledger.admit(binding("req2", record_id="rec2"))
        self.assertEqual((blocked.status, blocked.reason), ("denied", "request_ledger_capacity"))
        self.assertEqual(ledger.entry_count, 1)
        replay = ledger.admit(binding())
        self.assertEqual((replay.status, replay.reason), ("denied", "request_replayed"))

    def test_concurrent_duplicate_admission_has_single_winner(self):
        ledger = BoundedRequestLedger(max_entries=2)
        barrier = threading.Barrier(3)
        results = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            result = ledger.admit(binding())
            with lock:
                results.append((result.status, result.reason))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(("accepted", "request_bound")), 1)
        self.assertEqual(results.count(("denied", "request_replayed")), 1)
        self.assertEqual(ledger.entry_count, 1)

    def test_snapshot_detects_out_of_band_mutation(self):
        ledger = BoundedRequestLedger(max_entries=2)
        ledger.admit(binding())
        snapshot = ledger.snapshot()
        ledger._bindings["req1"] = binding(record_id="rec2")
        self.assertNotEqual(ledger.snapshot(), snapshot)

    def test_snapshot_is_canonical_and_bounded(self):
        ledger = BoundedRequestLedger(max_entries=2)
        ledger.admit(binding("req2", record_id="rec2"))
        ledger.admit(binding("req1", record_id="rec1"))
        snapshot = ledger.snapshot()
        self.assertEqual(tuple(request_id for request_id, _ in snapshot.bindings), ("req1", "req2"))
        self.assertEqual(snapshot.max_entries, 2)


if __name__ == "__main__":
    unittest.main()
