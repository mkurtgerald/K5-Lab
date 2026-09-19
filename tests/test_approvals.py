from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import unittest

from mosaic_lab.approvals import ApprovalRecord, ApprovalUseLedger

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64


def approval(**changes):
    value = {
        "approval_id": "approval1",
        "approver_ref": "principal1",
        "partition": "p1",
        "proposal_digest": PROPOSAL,
        "policy_revision": "policy1",
        "state_digest": STATE,
        "profile": "approval_required",
        "granted_at": NOW - timedelta(seconds=5),
        "expires_at": NOW + timedelta(seconds=30),
    }
    value.update(changes)
    return ApprovalRecord(**value)


def check(ledger, records, **changes):
    value = {
        "partition": "p1",
        "proposal_digest": PROPOSAL,
        "current_policy_revision": "policy1",
        "current_state_digest": STATE,
        "current_profile": "approval_required",
        "now": NOW,
        "required_approvals": 1,
    }
    value.update(changes)
    return ledger.validate_and_consume(records, **value)


class ApprovalContractTests(unittest.TestCase):
    def test_valid_record_is_simulation_only_and_single_use(self):
        ledger = ApprovalUseLedger()
        first = check(ledger, (approval(),))
        self.assertEqual((first.status, first.reason), ("accepted_for_simulation", "trusted_approval_bound"))
        self.assertEqual(first.consumed_approval_ids, ("approval1",))
        self.assertFalse(first.authorized)
        self.assertFalse(first.execute)
        self.assertEqual(first.external_actions, 0)
        second = check(ledger, (approval(),))
        self.assertEqual((second.status, second.reason), ("denied", "approval_reused"))

    def test_two_principal_requirement_requires_distinct_approvers(self):
        ledger = ApprovalUseLedger()
        one = check(ledger, (approval(),), required_approvals=2)
        self.assertEqual((one.status, one.reason), ("awaiting_approval", "insufficient_approvals"))

        records = (
            approval(),
            approval(approval_id="approval2", approver_ref="principal2"),
        )
        accepted = check(ledger, records, required_approvals=2)
        self.assertEqual(accepted.status, "accepted_for_simulation")

        duplicate_principal = (
            approval(approval_id="approval3"),
            approval(approval_id="approval4"),
        )
        denied = check(ApprovalUseLedger(), duplicate_principal, required_approvals=2)
        self.assertEqual((denied.status, denied.reason), ("denied", "duplicate_approver"))

    def test_changed_binding_revocation_and_expiry_deny(self):
        cases = (
            ((approval(proposal_digest="c" * 64),), {}, "proposal_changed"),
            ((approval(policy_revision="policy2"),), {}, "policy_changed"),
            ((approval(state_digest="d" * 64),), {}, "state_changed"),
            ((approval(profile="delegated_simulation"),), {}, "profile_changed"),
            ((approval(partition="p2"),), {}, "partition_mismatch"),
            ((approval(revoked=True),), {}, "approval_revoked"),
            ((approval(expires_at=NOW),), {}, "approval_expired"),
            ((approval(granted_at=NOW + timedelta(seconds=1), expires_at=NOW + timedelta(seconds=2)),), {}, "future_approval"),
        )
        for records, changes, reason in cases:
            with self.subTest(reason=reason):
                result = check(ApprovalUseLedger(), records, **changes)
                self.assertEqual((result.status, result.reason), ("denied", reason))
                self.assertFalse(result.authorized)
                self.assertEqual(result.external_actions, 0)

    def test_profile_reduction_invalidates_queued_approval(self):
        result = check(ApprovalUseLedger(), (approval(),), current_profile="read_only")
        self.assertEqual((result.status, result.reason), ("denied", "profile_reduced"))

    def test_chat_claim_or_untrusted_mapping_is_not_an_approval_record(self):
        for records in (("approved",), ({"approved": True},)):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    check(ApprovalUseLedger(), records)

    def test_atomic_concurrent_replay_allows_exactly_one_simulation_consumption(self):
        ledger = ApprovalUseLedger()
        record = approval()
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: check(ledger, (record,)), range(8)))
        accepted = [result for result in results if result.status == "accepted_for_simulation"]
        reused = [result for result in results if result.reason == "approval_reused"]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(reused), 7)
        self.assertEqual(ledger.used_count, 1)

    def test_capacity_exhaustion_fails_closed_without_eviction(self):
        ledger = ApprovalUseLedger(max_entries=1)
        first = check(ledger, (approval(),))
        self.assertEqual(first.status, "accepted_for_simulation")
        second = check(
            ledger,
            (approval(approval_id="approval2", approver_ref="principal2"),),
        )
        self.assertEqual((second.status, second.reason), ("denied", "ledger_capacity"))
        self.assertEqual(ledger.used_count, 1)

    def test_record_validation_rejects_invalid_binding(self):
        with self.assertRaises(ValueError):
            approval(proposal_digest="short")
        with self.assertRaises(ValueError):
            approval(granted_at=NOW, expires_at=NOW)
        with self.assertRaises(ValueError):
            ApprovalUseLedger(max_entries=0)


if __name__ == "__main__":
    unittest.main()
