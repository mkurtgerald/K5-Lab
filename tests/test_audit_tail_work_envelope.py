from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.retrieval import ReadScope

NOW = datetime(2026, 9, 19, 5, 0, tzinfo=timezone.utc)
MAX_AUDIT_ENTRIES = 4096
MAX_EVIDENCE_REFS = 128


class CountingRefs(tuple):
    iterations = 0

    def __iter__(self):
        for item in super().__iter__():
            type(self).iterations += 1
            yield item


def build_full_buffer():
    evidence_refs = CountingRefs(f"rec{index}" for index in range(MAX_EVIDENCE_REFS))
    evidence_digests = tuple(f"{index:064x}" for index in range(MAX_EVIDENCE_REFS))
    sink = AuditBuffer(max_entries=MAX_AUDIT_ENTRIES)
    for index in range(MAX_AUDIT_ENTRIES):
        sink.append(
            AuditEvent(
                event_id=f"event{index}",
                request_id=f"request{index}",
                partition="p1",
                principal_ref="principal1",
                profile="read_only",
                policy_revision="policy1",
                model_revision="model1",
                tool_revision="tool1",
                evidence_refs=evidence_refs,
                evidence_digests=evidence_digests,
                decision="denied",
                reason="synthetic_denial",
                outcome="denied",
                recorded_at=NOW,
            )
        )
    CountingRefs.iterations = 0
    return sink, tuple(evidence_refs)


class AuditTailWorkEnvelopeTests(unittest.TestCase):
    def test_max_state_partition_read_has_linear_deterministic_scan_bound(self):
        sink, allowed_record_ids = build_full_buffer()
        scope = ReadScope(
            partition="p1",
            principal_ref="principal1",
            profile="read_only",
            policy_revision="policy1",
            allowed_record_ids=allowed_record_ids,
            valid_until=NOW + timedelta(minutes=5),
        )

        first = sink.read_partition("p1", scope, current_policy_revision="policy1", now=NOW)
        first_iterations = CountingRefs.iterations
        CountingRefs.iterations = 0
        second = sink.read_partition("p1", scope, current_policy_revision="policy1", now=NOW)
        second_iterations = CountingRefs.iterations

        expected_iterations = MAX_AUDIT_ENTRIES * MAX_EVIDENCE_REFS
        self.assertEqual((first.status, first.reason), ("returned", "audit_returned"))
        self.assertEqual(len(first.events), MAX_AUDIT_ENTRIES)
        self.assertEqual(second, first)
        self.assertEqual(first_iterations, expected_iterations)
        self.assertEqual(second_iterations, expected_iterations)
        self.assertEqual(len(sink.snapshot()), MAX_AUDIT_ENTRIES)

    def test_scope_partition_rejection_is_constant_work_before_evidence_scan(self):
        sink, allowed_record_ids = build_full_buffer()
        foreign_scope = ReadScope(
            partition="p2",
            principal_ref="principal1",
            profile="read_only",
            policy_revision="policy1",
            allowed_record_ids=allowed_record_ids,
            valid_until=NOW + timedelta(minutes=5),
        )

        result = sink.read_partition("p1", foreign_scope, current_policy_revision="policy1", now=NOW)

        self.assertEqual((result.status, result.reason), ("denied", "audit_partition_mismatch"))
        self.assertEqual(result.events, ())
        self.assertEqual(CountingRefs.iterations, 0)
        self.assertEqual(len(sink.snapshot()), MAX_AUDIT_ENTRIES)


if __name__ == "__main__":
    unittest.main()
