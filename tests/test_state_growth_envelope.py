from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.retrieval import ReadScope, RetrievalSession, SyntheticEvidenceStore
from mosaic_lab.text_interaction import (
    InteractionInput,
    InteractionLimits,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)

NOW = datetime(2026, 9, 19, 4, 0, tzinfo=timezone.utc)


class CountingUnavailableProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return ProviderReply("unavailable", reason="provider_unavailable")


def interaction_input(request_id: str) -> InteractionInput:
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="synthetic question",
    )


def audit_event(index: int) -> AuditEvent:
    return AuditEvent(
        event_id=f"event{index}",
        request_id=f"request{index}",
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=(),
        evidence_digests=(),
        decision="denied",
        reason="synthetic_denial",
        outcome="denied",
        recorded_at=NOW + timedelta(microseconds=index),
    )


class StateGrowthEnvelopeTests(unittest.TestCase):
    def test_interaction_unique_request_flood_stops_growing_after_call_budget(self):
        session = InteractionSession(
            partition="p1",
            session_id="s1",
            limits=InteractionLimits(max_calls=4),
        )
        provider = CountingUnavailableProvider()

        for index in range(4):
            result = run_interaction_turn(session, interaction_input(f"req{index}"), provider)
            self.assertEqual((result.status, result.reason), ("unavailable", "provider_unavailable"))
            self.assertFalse(result.authorized)
            self.assertFalse(result.execute)
            self.assertEqual(result.external_actions, 0)

        baseline = (
            session.calls_used,
            session.tokens_used,
            session.elapsed_seconds,
            len(session.turns()),
            len(session._attempted),
        )
        for index in range(4, 516):
            blocked = run_interaction_turn(session, interaction_input(f"req{index}"), provider)
            self.assertEqual((blocked.status, blocked.reason), ("budget_exhausted", "call_limit"))
            self.assertFalse(blocked.authorized)
            self.assertFalse(blocked.execute)
            self.assertEqual(blocked.external_actions, 0)

        self.assertEqual(provider.calls, 4)
        self.assertEqual(
            (
                session.calls_used,
                session.tokens_used,
                session.elapsed_seconds,
                len(session.turns()),
                len(session._attempted),
            ),
            baseline,
        )
        self.assertEqual(len(session._attempted), 4)
        self.assertEqual(session.turns(), ())

    def test_retrieval_request_flood_fails_closed_without_source_or_state_growth(self):
        session = RetrievalSession(
            session_id="s1",
            partition="p1",
            principal_ref="principal1",
            policy_revision="policy1",
            max_cache_entries=2,
            max_request_entries=4,
        )
        source = SyntheticEvidenceStore()
        scope = ReadScope(
            partition="p1",
            principal_ref="principal1",
            profile="read_only",
            policy_revision="policy1",
            allowed_record_ids=("rec1",),
            valid_until=NOW + timedelta(minutes=5),
        )

        for index in range(4):
            result = session.retrieve(
                f"req{index}",
                "rec1",
                source,
                scope,
                current_policy_revision="policy1",
                now=NOW,
            )
            self.assertEqual((result.status, result.reason), ("abstain", "missing_evidence"))
            self.assertFalse(result.authorized)
            self.assertFalse(result.execute)
            self.assertEqual(result.external_actions, 0)

        self.assertEqual((session.request_count, session.cache_size, source.read_count), (4, 0, 4))
        for index in range(4, 516):
            blocked = session.retrieve(
                f"req{index}",
                "rec1",
                source,
                scope,
                current_policy_revision="policy1",
                now=NOW,
            )
            self.assertEqual((blocked.status, blocked.reason), ("denied", "request_ledger_capacity"))
            self.assertFalse(blocked.authorized)
            self.assertFalse(blocked.execute)
            self.assertEqual(blocked.external_actions, 0)

        self.assertEqual((session.request_count, session.cache_size, source.read_count), (4, 0, 4))

    def test_audit_capacity_pressure_never_evicts_or_grows_past_bound(self):
        sink = AuditBuffer(max_entries=4)
        for index in range(4):
            self.assertTrue(sink.append(audit_event(index)))
        baseline = sink.snapshot()

        for index in range(4, 516):
            with self.assertRaisesRegex(RuntimeError, "audit_capacity"):
                sink.append(audit_event(index))

        self.assertEqual(sink.snapshot(), baseline)
        self.assertEqual(len(sink.snapshot()), 4)
        self.assertEqual(len(sink._by_id), 4)


if __name__ == "__main__":
    unittest.main()
