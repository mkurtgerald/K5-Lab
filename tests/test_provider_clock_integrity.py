import unittest

from mosaic_lab.text_interaction import (
    InteractionInput,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


class SequenceClock:
    def __init__(self, values):
        self._values = iter(values)

    def __call__(self):
        value = next(self._values)
        if isinstance(value, BaseException):
            raise value
        return value


class Provider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return ProviderReply("ok", "synthetic answer", "provider_ok", 3, 2)


def item(request_id="req1"):
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="synthetic question",
    )


class ProviderClockIntegrityTests(unittest.TestCase):
    def assert_non_authorizing(self, result):
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)
        self.assertEqual(result.text, "")

    def test_clock_regression_after_provider_fails_closed_and_blocks_replay(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = Provider()
        clock = SequenceClock((10.0, 9.0))

        first = run_interaction_turn(session, item(), provider, clock=clock)
        second = run_interaction_turn(session, item(), provider, clock=clock)

        self.assertEqual((first.status, first.reason), ("error", "clock_regression"))
        self.assert_non_authorizing(first)
        self.assertEqual((second.status, second.reason), ("error", "duplicate_request"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())

    def test_nonfinite_completion_clock_fails_closed(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = Provider()

        result = run_interaction_turn(
            session,
            item(),
            provider,
            clock=SequenceClock((10.0, float("nan"))),
        )

        self.assertEqual((result.status, result.reason), ("error", "clock_regression"))
        self.assert_non_authorizing(result)
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())

    def test_completion_clock_exception_fails_closed_and_request_stays_consumed(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = Provider()
        clock = SequenceClock((10.0, RuntimeError("synthetic clock failure")))

        first = run_interaction_turn(session, item(), provider, clock=clock)
        second = run_interaction_turn(session, item(), provider, clock=clock)

        self.assertEqual((first.status, first.reason), ("error", "clock_failure"))
        self.assert_non_authorizing(first)
        self.assertEqual((second.status, second.reason), ("error", "duplicate_request"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())


if __name__ == "__main__":
    unittest.main()
