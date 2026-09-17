import unittest
from threading import Event, Lock, Thread

from mosaic_lab.text_interaction import (
    ActionPresentation,
    InteractionInput,
    InteractionLimits,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


def inp(request_id="req1"):
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="question",
        evidence_refs=("rec1",),
        action=ActionPresentation("awaiting_approval"),
    )


class BlockingProvider:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self._lock = Lock()
        self.requests = []

    def complete(self, request):
        with self._lock:
            self.requests.append(request)
        self.started.set()
        if not self.release.wait(timeout=2.0):
            raise RuntimeError("synthetic provider release timeout")
        return ProviderReply("ok", "answer", "provider_ok", 4, 2)


class FastProvider:
    def __init__(self):
        self._lock = Lock()
        self.requests = []

    def complete(self, request):
        with self._lock:
            self.requests.append(request)
        return ProviderReply("ok", "answer", "provider_ok", 4, 2)


class HostileInteractionSequencingTests(unittest.TestCase):
    def test_concurrent_duplicate_request_causes_exactly_one_provider_call(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = BlockingProvider()
        results = []

        first = Thread(target=lambda: results.append(run_interaction_turn(session, inp("req1"), provider)))
        second = Thread(target=lambda: results.append(run_interaction_turn(session, inp("req1"), provider)))
        first.start()
        self.assertTrue(provider.started.wait(timeout=1.0))
        second.start()
        provider.release.set()
        first.join(timeout=2.0)
        second.join(timeout=2.0)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(sorted((item.status, item.reason) for item in results), [("error", "duplicate_request"), ("ok", "provider_ok")])
        for item in results:
            self.assertFalse(item.authorized)
            self.assertFalse(item.execute)
            self.assertEqual(item.external_actions, 0)

    def test_concurrent_distinct_requests_cannot_oversubscribe_call_budget(self):
        session = InteractionSession(
            partition="p1",
            session_id="s1",
            limits=InteractionLimits(max_calls=1),
        )
        provider = FastProvider()
        start = Event()
        results = []

        def worker(request_id):
            self.assertTrue(start.wait(timeout=1.0))
            results.append(run_interaction_turn(session, inp(request_id), provider))

        threads = [Thread(target=worker, args=("req1",)), Thread(target=worker, args=("req2",))]
        for thread in threads:
            thread.start()
        start.set()
        for thread in threads:
            thread.join(timeout=2.0)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(sorted((item.status, item.reason) for item in results), [("budget_exhausted", "call_limit"), ("ok", "provider_ok")])
        self.assertEqual(session.calls_used, 1)
        for item in results:
            self.assertFalse(item.authorized)
            self.assertFalse(item.execute)
            self.assertEqual(item.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
