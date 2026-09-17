from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.simulation import DelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64


def grant(**changes):
    value = {
        "grant_id": "grant1",
        "principal_ref": "principal1",
        "partition": "p1",
        "proposal_digest": PROPOSAL,
        "policy_revision": "policy1",
        "state_digest": STATE,
        "allowed_actions": ("act1", "act2"),
        "allowed_targets": ("target1",),
        "granted_at": NOW - timedelta(seconds=5),
        "expires_at": NOW + timedelta(minutes=2),
        "max_steps": 4,
        "max_duration_seconds": 90.0,
        "max_actions_per_minute": 4,
    }
    value.update(changes)
    return DelegationGrant(**value)


def session(g=None, **changes):
    return DelegatedSimulation(g or grant(), session_id="session1", started_at=NOW, **changes)


def step(index=1, **changes):
    value = {
        "step_id": f"step{index}",
        "delivery_id": f"delivery{index}",
        "action_ref": "act1",
        "target_ref": "target1",
    }
    value.update(changes)
    return SimulationStep(**value)


def attempt(subject, item, **changes):
    value = {
        "now": NOW + timedelta(seconds=1),
        "current_policy_revision": "policy1",
        "current_state_digest": STATE,
        "current_profile": "delegated_simulation",
        "authority_available": True,
        "cancelled": False,
        "grant_revoked": False,
        "mocked_outcome": "verified_complete",
        "reversible": True,
    }
    value.update(changes)
    return subject.attempt_step(item, **value)


class DelegatedSimulationTests(unittest.TestCase):
    def test_positive_steps_remain_mock_only_and_reauthorized(self):
        subject = session()
        first = attempt(subject, step(1))
        second = attempt(subject, step(2), now=NOW + timedelta(seconds=2))
        self.assertEqual((first.status, second.status), ("verified_complete", "verified_complete"))
        self.assertEqual((first.mocked_effects, second.mocked_effects), (1, 1))
        self.assertEqual(second.completed_steps, 2)
        self.assertFalse(second.authorized)
        self.assertFalse(second.execute)
        self.assertEqual(second.external_actions, 0)

    def test_cancellation_revocation_and_authority_failure_block_later_effects(self):
        cases = (
            ({"cancelled": True}, ("cancelled", "session_cancelled")),
            ({"grant_revoked": True}, ("denied", "grant_revoked")),
            ({"authority_available": False}, ("denied", "authority_unavailable")),
        )
        for changes, expected in cases:
            with self.subTest(expected=expected):
                subject = session()
                attempt(subject, step(1))
                receipt = attempt(subject, step(2), now=NOW + timedelta(seconds=2), **changes)
                self.assertEqual((receipt.status, receipt.reason), expected)
                self.assertEqual(receipt.mocked_effects, 0)
                self.assertEqual(receipt.external_actions, 0)

    def test_policy_state_profile_and_scope_are_rechecked_each_step(self):
        cases = (
            ({"current_policy_revision": "policy2"}, "policy_changed"),
            ({"current_state_digest": "c" * 64}, "state_changed"),
            ({"current_profile": "recommend"}, "profile_changed"),
        )
        for changes, reason in cases:
            with self.subTest(reason=reason):
                receipt = attempt(session(), step(1), **changes)
                self.assertEqual((receipt.status, receipt.reason), ("denied", reason))
                self.assertEqual(receipt.mocked_effects, 0)
        self.assertEqual(attempt(session(), step(1, action_ref="other")).reason, "action_out_of_scope")
        self.assertEqual(attempt(session(), step(1, target_ref="other")).reason, "target_out_of_scope")

    def test_step_time_expiry_and_rate_budgets_fail_closed(self):
        one_step = session(grant(max_steps=1))
        attempt(one_step, step(1))
        exhausted = attempt(one_step, step(2), now=NOW + timedelta(seconds=2))
        self.assertEqual((exhausted.status, exhausted.reason), ("budget_exhausted", "step_budget"))

        timed = session(grant(max_duration_seconds=1.0))
        timeout = attempt(timed, step(1), now=NOW + timedelta(seconds=2))
        self.assertEqual((timeout.status, timeout.reason), ("budget_exhausted", "time_budget"))

        expired = session(grant(expires_at=NOW + timedelta(seconds=1)))
        expired_receipt = attempt(expired, step(1), now=NOW + timedelta(seconds=1))
        self.assertEqual((expired_receipt.status, expired_receipt.reason), ("denied", "grant_expired"))

        limited = session(grant(max_actions_per_minute=1))
        attempt(limited, step(1))
        rate = attempt(limited, step(2), now=NOW + timedelta(seconds=2))
        self.assertEqual((rate.status, rate.reason), ("rate_limited", "rate_budget"))
        self.assertEqual(rate.mocked_effects, 0)

    def test_duplicate_delivery_is_idempotent_and_concurrent(self):
        subject = session()
        item = step(1)
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: attempt(subject, item), range(8)))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual(receipts[0].mocked_effects, 1)
        second = attempt(subject, step(2), now=NOW + timedelta(seconds=2))
        self.assertEqual(second.step_index, 2)

    def test_ambiguous_outcome_requires_reconciliation_before_any_retry(self):
        subject = session()
        ambiguous = attempt(subject, step(1), mocked_outcome="outcome_unknown", reversible=False)
        self.assertEqual(ambiguous.status, "outcome_unknown")
        retry = attempt(
            subject,
            step(1, delivery_id="delivery2"),
            now=NOW + timedelta(seconds=2),
        )
        self.assertEqual((retry.status, retry.reason), ("reconciliation_required", "ambiguous_prior_outcome"))
        self.assertEqual(retry.mocked_effects, 0)
        resolved = subject.reconcile("step1", authoritative_outcome="verified_complete", reversible=False)
        self.assertEqual((resolved.status, resolved.reason), ("verified_complete", "reconciled"))
        self.assertEqual(resolved.mocked_effects, 0)
        self.assertFalse(resolved.rollback_available)

    def test_partial_failure_and_nonreversible_outcome_are_represented_honestly(self):
        subject = session()
        first = attempt(subject, step(1), reversible=False)
        self.assertFalse(first.rollback_available)
        second = attempt(
            subject,
            step(2),
            now=NOW + timedelta(seconds=2),
            mocked_outcome="failed",
            reversible=False,
        )
        self.assertEqual(second.status, "failed")
        self.assertEqual((second.completed_steps, second.failed_steps), (1, 1))
        self.assertFalse(second.rollback_available)
        self.assertEqual(second.external_actions, 0)

    def test_new_delivery_for_terminal_step_does_not_duplicate_effect(self):
        subject = session()
        attempt(subject, step(1))
        duplicate = attempt(subject, step(1, delivery_id="delivery2"), now=NOW + timedelta(seconds=2))
        self.assertEqual((duplicate.status, duplicate.reason), ("denied", "duplicate_step"))
        self.assertEqual(duplicate.mocked_effects, 0)

    def test_replay_ledger_capacity_fails_closed(self):
        subject = session(max_tracked_deliveries=1)
        attempt(subject, step(1))
        blocked = attempt(subject, step(2), now=NOW + timedelta(seconds=2))
        self.assertEqual((blocked.status, blocked.reason), ("denied", "replay_ledger_capacity"))
        self.assertEqual(blocked.mocked_effects, 0)

    def test_contract_bounds_reject_invalid_grants_and_outcomes(self):
        with self.assertRaises(ValueError):
            grant(max_steps=65)
        with self.assertRaises(ValueError):
            grant(max_duration_seconds=float("inf"))
        with self.assertRaises(ValueError):
            grant(max_actions_per_minute=0)
        with self.assertRaises(ValueError):
            attempt(session(), step(1), mocked_outcome="success")


if __name__ == "__main__":
    unittest.main()
