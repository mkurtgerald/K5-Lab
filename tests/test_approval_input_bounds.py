from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64


def approval(index: int = 1) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=f"approval{index}",
        approver_ref=f"principal{index}",
        partition="p1",
        proposal_digest=PROPOSAL,
        policy_revision="policy1",
        state_digest=STATE,
        profile="approval_required",
        granted_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(seconds=30),
    )


def check(ledger: ApprovalUseLedger, records, *, required_approvals: int = 1):
    return ledger.validate_and_consume(
        records,
        partition="p1",
        proposal_digest=PROPOSAL,
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="approval_required",
        now=NOW,
        required_approvals=required_approvals,
    )


class BoundedApprovalInputTests(unittest.TestCase):
    def test_overfull_or_unbounded_iterable_consumes_only_required_plus_one(self):
        seen = []

        def records():
            index = 1
            while True:
                seen.append(index)
                yield approval(index)
                index += 1

        result = check(ApprovalUseLedger(), records(), required_approvals=1)
        self.assertEqual((result.status, result.reason), ("denied", "unexpected_approval_count"))
        self.assertEqual(seen, [1, 2])
        self.assertEqual(result.external_actions, 0)

    def test_iterator_failure_fails_closed_without_consumption(self):
        class FaultingRecords:
            def __iter__(self):
                yield approval(1)
                raise RuntimeError("synthetic_iterator_failure")

        ledger = ApprovalUseLedger()
        with self.assertRaisesRegex(ValueError, "approval record iteration failed"):
            check(ledger, FaultingRecords(), required_approvals=2)
        self.assertEqual(ledger.used_count, 0)


if __name__ == "__main__":
    unittest.main()
