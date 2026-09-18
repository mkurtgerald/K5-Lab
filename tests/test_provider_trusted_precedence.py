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
        return next(self._values)


class InvalidReplyProvider:
    def __init__(self, *, cancel=False):
        self.calls = 0
        self.cancel = cancel

    def complete(self, request):
        self.calls += 1
        if self.cancel:
            request.cancellation.cancel()
        return object()


class ValidProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return ProviderReply("ok", "synthetic answer", "provider_ok", 3, 2)


def item():
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id="req1",
        text="synthetic question",
    )


class ProviderTrustedPrecedenceTests(unittest.TestCase):
    def assert_non_authorizing(self, result):
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

    def test_cancelled_invalid_reply_cannot_mask_cancellation(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = InvalidReplyProvider(cancel=True)

        result = run_interaction_turn(
            session,
            item(),
            provider,
            clock=SequenceClock((10.0, 11.0)),
        )

        self.assertEqual((result.status, result.reason), ("cancelled", "cancelled_during_call"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())
        self.assert_non_authorizing(result)

    def test_timeout_invalid_reply_cannot_mask_timeout(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = InvalidReplyProvider()

        result = run_interaction_turn(
            session,
            item(),
            provider,
            clock=SequenceClock((10.0, 16.0)),
        )

        self.assertEqual((result.status, result.reason), ("timeout", "provider_timeout"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())
        self.assert_non_authorizing(result)

    def test_unrepresentable_deadline_fails_before_provider_and_does_not_consume_request(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = ValidProvider()
        max_float = float.fromhex("0x1.fffffffffffffp+1023")

        first = run_interaction_turn(
            session,
            item(),
            provider,
            clock=SequenceClock((max_float,)),
        )
        second = run_interaction_turn(
            session,
            item(),
            provider,
            clock=SequenceClock((10.0, 11.0)),
        )

        self.assertEqual((first.status, first.reason), ("error", "clock_failure"))
        self.assertEqual((second.status, second.reason), ("ok", "provider_ok"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(len(session.turns()), 1)
        self.assert_non_authorizing(first)
        self.assert_non_authorizing(second)


if __name__ == "__main__":
    unittest.main()
