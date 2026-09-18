import unittest

from mosaic_lab.text_interaction import (
    ActionPresentation,
    InteractionInput,
    InteractionLimits,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


class SequenceClock:
    def __init__(self, values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class SessionMutatingProvider:
    def __init__(self, session):
        self.session = session
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        self.session.partition = "other"
        self.session.session_id = "other-session"
        self.session.limits = InteractionLimits(max_calls=16)
        self.session._turns = []
        self.session._attempted = set()
        self.session._calls = 0
        self.session._tokens = 0
        self.session._elapsed = 0.0
        self.session._integrity_failed = False
        self.session._lock = object()
        return ProviderReply("ok", "synthetic answer", "provider_ok", 2, 2)


class ContextMutatingProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if self.calls == 2:
            object.__setattr__(request.messages[0], "text", "tampered-history")
            object.__setattr__(request.messages[-1], "text", "tampered-current")
        return ProviderReply("ok", f"answer-{self.calls}", "provider_ok", 1, 1)


class DeadlineMutatingProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        object.__setattr__(request, "deadline_monotonic", 1000.0)
        return ProviderReply("ok", "late answer", "provider_ok", 1, 1)


class InputMutatingProvider:
    def __init__(self, item):
        self.item = item
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        object.__setattr__(self.item, "text", "tampered-input")
        object.__setattr__(self.item, "evidence_refs", ("evil",))
        object.__setattr__(self.item.action, "status", "failed")
        return ProviderReply("ok", "synthetic answer", "provider_ok", 1, 1)


class ProviderSessionIntegrityTests(unittest.TestCase):
    def assert_non_authorizing(self, result):
        self.assertFalse(result.authorized)
        self.assertFalse(result.execute)
        self.assertEqual(result.external_actions, 0)

    def test_provider_cannot_persist_out_of_band_session_mutation(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = SessionMutatingProvider(session)
        first = InteractionInput(partition="p1", session_id="s1", request_id="req1", text="synthetic one")

        result = run_interaction_turn(session, first, provider, clock=SequenceClock((10.0,)))
        blocked = run_interaction_turn(
            session,
            InteractionInput(partition="p1", session_id="s1", request_id="req2", text="synthetic two"),
            provider,
            clock=SequenceClock((20.0,)),
        )

        self.assertEqual((result.status, result.reason), ("error", "session_integrity_failure"))
        self.assertEqual((blocked.status, blocked.reason), ("error", "session_integrity_failure"))
        self.assertEqual(provider.calls, 1)
        self.assertEqual((session.partition, session.session_id), ("p1", "s1"))
        self.assertEqual(session.calls_used, 1)
        self.assertEqual(session.tokens_used, 0)
        self.assertEqual(session.turns(), ())
        self.assert_non_authorizing(result)
        self.assert_non_authorizing(blocked)

    def test_provider_message_mutation_cannot_rewrite_trusted_history_or_current_turn(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = ContextMutatingProvider()
        one = InteractionInput(partition="p1", session_id="s1", request_id="req1", text="synthetic one")
        two = InteractionInput(partition="p1", session_id="s1", request_id="req2", text="synthetic two")

        first = run_interaction_turn(session, one, provider, clock=SequenceClock((10.0, 11.0)))
        second = run_interaction_turn(session, two, provider, clock=SequenceClock((12.0, 13.0)))

        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertEqual([turn.user.text for turn in session.turns()], ["synthetic one", "synthetic two"])
        self.assert_non_authorizing(first)
        self.assert_non_authorizing(second)

    def test_provider_cannot_extend_trusted_deadline_by_mutating_request(self):
        session = InteractionSession(partition="p1", session_id="s1")
        provider = DeadlineMutatingProvider()
        item = InteractionInput(partition="p1", session_id="s1", request_id="req1", text="synthetic one")

        result = run_interaction_turn(session, item, provider, clock=SequenceClock((10.0, 16.0)))

        self.assertEqual((result.status, result.reason), ("timeout", "provider_timeout"))
        self.assertEqual(session.turns(), ())
        self.assertEqual(provider.calls, 1)
        self.assert_non_authorizing(result)

    def test_out_of_band_input_mutation_cannot_change_trusted_result_or_turn(self):
        session = InteractionSession(partition="p1", session_id="s1")
        item = InteractionInput(
            partition="p1",
            session_id="s1",
            request_id="req1",
            text="synthetic one",
            evidence_refs=("e1",),
            action=ActionPresentation(status="awaiting_approval", receipt_ref="r1", authoritative=True),
        )
        provider = InputMutatingProvider(item)

        result = run_interaction_turn(session, item, provider, clock=SequenceClock((10.0, 11.0)))

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.evidence_refs, ("e1",))
        self.assertEqual(result.action.status, "awaiting_approval")
        self.assertEqual(session.turns()[0].user.text, "synthetic one")
        self.assert_non_authorizing(result)


if __name__ == "__main__":
    unittest.main()
