import unittest

from mosaic_lab.text_interaction import (
    ActionPresentation,
    InteractionInput,
    InteractionLimits,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


class Provider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self.reply


def inp(request_id="req1"):
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="q",
        action=ActionPresentation("awaiting_approval"),
    )


class ProviderReplyBoundaryTests(unittest.TestCase):
    def test_mutated_reply_fails_closed_without_escaping_exception(self):
        reply = ProviderReply("ok", "answer", "provider_ok", 4, 2)
        object.__setattr__(reply, "output_tokens", "malformed")
        provider = Provider(reply)
        session = InteractionSession(partition="p1", session_id="s1")

        result = run_interaction_turn(session, inp(), provider)

        self.assertEqual((result.status, result.reason), ("error", "invalid_provider_reply"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual(session.turns(), ())
        self.assertEqual(session.tokens_used, 0)
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

    def test_extreme_reported_input_tokens_are_bounded_and_exhaust_session(self):
        limits = InteractionLimits(max_total_tokens=64, max_output_tokens=16, max_context_chars=128)
        session = InteractionSession(partition="p1", session_id="s1", limits=limits)
        provider = Provider(ProviderReply("ok", "a", "provider_ok", 10**1000, 1))

        result = run_interaction_turn(session, inp(), provider)

        self.assertEqual((result.status, result.reason), ("budget_exhausted", "reported_token_budget"))
        self.assertEqual(session.tokens_used, 65)
        self.assertEqual(session.turns(), ())
        second_provider = Provider(ProviderReply("ok", "b", "provider_ok", 1, 1))
        second = run_interaction_turn(session, inp("req2"), second_provider)
        self.assertEqual((second.status, second.reason), ("budget_exhausted", "token_budget_preflight"))
        self.assertEqual(second_provider.calls, 0)

    def test_extreme_output_claim_is_bounded_before_rejection(self):
        limits = InteractionLimits(max_total_tokens=64, max_output_tokens=16, max_context_chars=128)
        session = InteractionSession(partition="p1", session_id="s1", limits=limits)

        result = run_interaction_turn(
            session,
            inp(),
            Provider(ProviderReply("ok", "a", "provider_ok", 1, 10**1000)),
        )

        self.assertEqual((result.status, result.reason), ("error", "provider_output_token_limit"))
        self.assertEqual(session.tokens_used, 65)
        self.assertEqual(session.turns(), ())

    def test_provider_reply_subclass_is_rejected_at_boundary(self):
        class DerivedReply(ProviderReply):
            pass

        session = InteractionSession(partition="p1", session_id="s1")
        result = run_interaction_turn(
            session,
            inp(),
            Provider(DerivedReply("ok", "a", "provider_ok", 1, 1)),
        )

        self.assertEqual((result.status, result.reason), ("error", "invalid_provider_reply"))
        self.assertEqual(session.turns(), ())


if __name__ == "__main__":
    unittest.main()
