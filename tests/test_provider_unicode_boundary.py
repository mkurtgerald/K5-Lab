import unittest

from mosaic_lab.text_interaction import (
    InteractionInput,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


class ForgedUnicodeProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        reply = object.__new__(ProviderReply)
        object.__setattr__(reply, "status", "ok")
        object.__setattr__(reply, "text", "\ud800")
        object.__setattr__(reply, "reason", "provider_ok")
        object.__setattr__(reply, "input_tokens", 1)
        object.__setattr__(reply, "output_tokens", 1)
        object.__setattr__(reply, "version", "1")
        return reply


class ProviderUnicodeBoundaryTests(unittest.TestCase):
    def test_unencodable_user_text_is_rejected_at_input_boundary(self):
        with self.assertRaises(ValueError):
            InteractionInput(
                partition="p1",
                session_id="s1",
                request_id="req1",
                text="\ud800",
            )

    def test_forged_unencodable_provider_text_fails_closed_without_escaping_text(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = ForgedUnicodeProvider()
        item = InteractionInput(
            partition="p1",
            session_id="s1",
            request_id="req1",
            text="synthetic question",
        )

        result = run_interaction_turn(session, item, provider)
        replay = run_interaction_turn(session, item, provider)

        self.assertEqual((result.status, result.reason), ("error", "invalid_provider_reply"))
        self.assertEqual(result.text, "")
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)
        self.assertEqual(session.turns(), ())
        self.assertEqual(provider.calls, 1)
        self.assertEqual((replay.status, replay.reason), ("error", "duplicate_request"))
        self.assertEqual(provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
