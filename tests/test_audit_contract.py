from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.retrieval import ReadScope

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
EVIDENCE_DIGEST = "d" * 64


def scope(**changes):
    values = dict(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1", "rec2"),
        valid_until=NOW + timedelta(minutes=5),
    )
    values.update(changes)
    return ReadScope(**values)


def event(event_id="event1", **changes):
    values = dict(
        event_id=event_id,
        request_id="req1",
        proposal_id="prop1",
        partition="p1",
        principal_ref="principal1",
        profile="approval_required",
        grant_ref="grant1",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=("rec1",),
        decision="denied",
        reason="policy_changed",
        approval_ref="approval1",
        outcome="denied",
        recorded_at=NOW,
        evidence_digests=(EVIDENCE_DIGEST,),
    )
    values.update(changes)
    return AuditEvent(**values)


class AuditContractTests(unittest.TestCase):
    def test_contract_carries_required_identity_and_outcome_without_hidden_reasoning(self):
        item = event()
        self.assertEqual(item.request_id, "req1")
        self.assertEqual(item.proposal_id, "prop1")
        self.assertEqual(item.principal_ref, "principal1")
        self.assertEqual(item.policy_revision, "policy1")
        self.assertEqual(item.model_revision, "model1")
        self.assertEqual(item.tool_revision, "tool1")
        self.assertEqual(item.evidence_refs, ("rec1",))
        self.assertEqual(item.evidence_digests, (EVIDENCE_DIGEST,))
        self.assertEqual(item.approval_ref, "approval1")
        self.assertEqual(item.outcome, "denied")
        self.assertEqual(item.version, "2")
        self.assertFalse(hasattr(item, "reasoning"))
        self.assertFalse(hasattr(item, "details"))

    def test_denial_cancellation_revocation_failure_and_unknown_outcomes_are_representable(self):
        cases = (
            ("denied", "grant_revoked", "denied"),
            ("cancelled", "session_cancelled", "cancelled"),
            ("failed", "provider_failure", "failed"),
            ("attempted", "ambiguous_outcome", "outcome_unknown"),
        )
        for decision, reason, outcome in cases:
            with self.subTest(outcome=outcome):
                item = event(decision=decision, reason=reason, outcome=outcome)
                self.assertEqual((item.decision, item.reason, item.outcome), (decision, reason, outcome))

    def test_append_is_idempotent_under_concurrent_duplicate_delivery(self):
        buffer = AuditBuffer()
        item = event()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: buffer.append(item), range(8)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(len(buffer.snapshot()), 1)

    def test_event_identity_collision_is_rejected(self):
        buffer = AuditBuffer()
        buffer.append(event())
        with self.assertRaises(ValueError):
            buffer.append(event(reason="different_reason"))
        with self.assertRaises(ValueError):
            buffer.append(event(evidence_digests=("e" * 64,)))

    def test_capacity_fails_closed_without_eviction_and_claims_remain_honest(self):
        buffer = AuditBuffer(max_entries=1)
        buffer.append(event())
        with self.assertRaises(RuntimeError):
            buffer.append(event("event2", request_id="req2"))
        self.assertEqual(len(buffer.snapshot()), 1)
        self.assertFalse(buffer.durable)
        self.assertFalse(buffer.tamper_evident)

    def test_partition_read_rechecks_current_scope_and_evidence_refs(self):
        buffer = AuditBuffer(); buffer.append(event())
        ok = buffer.read_partition("p1", scope(), current_policy_revision="policy1", now=NOW)
        self.assertEqual((ok.status, ok.reason), ("returned", "audit_returned"))
        self.assertEqual(len(ok.events), 1)
        denied = buffer.read_partition("p2", scope(), current_policy_revision="policy1", now=NOW)
        self.assertEqual((denied.status, denied.reason), ("denied", "audit_partition_mismatch"))
        narrowed = buffer.read_partition("p1", scope(allowed_record_ids=("rec2",)), current_policy_revision="policy1", now=NOW)
        self.assertEqual((narrowed.status, narrowed.reason), ("denied", "audit_evidence_out_of_scope"))
        self.assertEqual(narrowed.events, ())

    def test_cross_principal_audit_material_is_not_returned(self):
        buffer = AuditBuffer()
        buffer.append(event())
        buffer.append(event("event2", request_id="req2", principal_ref="principal2"))
        result = buffer.read_partition("p1", scope(), current_policy_revision="policy1", now=NOW)
        self.assertEqual((result.status, result.reason), ("denied", "audit_principal_mismatch"))
        self.assertEqual(result.events, ())

    def test_policy_change_and_unauthenticated_scope_deny_audit_read(self):
        buffer = AuditBuffer(); buffer.append(event())
        changed = buffer.read_partition("p1", scope(policy_revision="policy2"), current_policy_revision="policy1", now=NOW)
        self.assertEqual((changed.status, changed.reason), ("denied", "audit_policy_context_mismatch"))
        historical = buffer.read_partition("p1", scope(policy_revision="policy2"), current_policy_revision="policy2", now=NOW)
        self.assertEqual((historical.status, historical.reason), ("returned", "audit_returned"))
        self.assertEqual(historical.events[0].policy_revision, "policy1")
        unauthenticated = buffer.read_partition("p1", scope(authenticated=False), current_policy_revision="policy1", now=NOW)
        self.assertEqual((unauthenticated.status, unauthenticated.reason), ("denied", "audit_unauthenticated"))

    def test_tokens_bounds_and_evidence_binding_fail_closed(self):
        with self.assertRaises(ValueError):
            event(reason="free form secret text")
        with self.assertRaises(ValueError):
            event(evidence_refs=("rec1", "rec1"), evidence_digests=(EVIDENCE_DIGEST, EVIDENCE_DIGEST))
        with self.assertRaises(ValueError):
            event(evidence_digests=())
        with self.assertRaises(ValueError):
            event(evidence_digests=("not-a-digest",))
        with self.assertRaises(ValueError):
            event(version="1")
        with self.assertRaises(ValueError):
            AuditBuffer(max_entries=0)


if __name__ == "__main__":
    unittest.main()
