from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.delegation import DelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64


class DelegationReconciliationReplayTests(unittest.TestCase):
    def test_reconciled_duplicate_delivery_returns_terminal_receipt(self):
        grant = DelegationGrant(
            grant_id="grant1",
            principal_ref="principal1",
            partition="p1",
            proposal_digest=PROPOSAL,
            policy_revision="policy1",
            state_digest=STATE,
            allowed_actions=("act1",),
            allowed_targets=("target1",),
            granted_at=NOW - timedelta(seconds=5),
            expires_at=NOW + timedelta(minutes=2),
            max_steps=4,
            max_duration_seconds=90.0,
            max_actions_per_minute=4,
        )
        subject = DelegatedSimulation(grant, session_id="session1", started_at=NOW)
        item = SimulationStep("step1", "delivery1", "act1", "target1")
        kwargs = {
            "now": NOW + timedelta(seconds=1),
            "current_policy_revision": "policy1",
            "current_state_digest": STATE,
            "current_profile": "delegated_simulation",
            "authority_available": True,
            "cancelled": False,
            "grant_revoked": False,
            "mocked_outcome": "outcome_unknown",
            "reversible": False,
        }

        ambiguous = subject.attempt_step(item, **kwargs)
        self.assertEqual(ambiguous.status, "outcome_unknown")

        resolved = subject.reconcile(
            "step1",
            authoritative_outcome="verified_complete",
            reversible=False,
        )
        replay = subject.attempt_step(item, **kwargs)

        self.assertEqual(replay, resolved)
        self.assertEqual((replay.status, replay.reason), ("verified_complete", "reconciled"))
        self.assertEqual(replay.mocked_effects, 0)
        self.assertFalse(replay.authorized)
        self.assertFalse(replay.execute)
        self.assertEqual(replay.external_actions, 0)


if __name__ == "__main__":
    unittest.main()
