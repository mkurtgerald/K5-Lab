from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.delegation import AuditAdmissionBinding, AuditedDelegatedSimulation, DelegatedSimulation, DelegationGrant, SimulationStep

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
PROPOSAL = "a" * 64
STATE = "b" * 64


def grant():
    return DelegationGrant(
        grant_id="grant1",
        principal_ref="principal1",
        partition="p1",
        proposal_digest=PROPOSAL,
        policy_revision="policy1",
        state_digest=STATE,
        allowed_actions=("act1", "act2"),
        allowed_targets=("target1",),
        granted_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=2),
        max_steps=4,
        max_duration_seconds=90.0,
        max_actions_per_minute=4,
    )


def binding():
    return AuditAdmissionBinding(proposal_id="proposal1", proposal_digest=PROPOSAL)


def kwargs():
    return dict(
        now=NOW + timedelta(seconds=1),
        current_policy_revision="policy1",
        current_state_digest=STATE,
        current_profile="delegated_simulation",
        authority_available=True,
        cancelled=False,
        grant_revoked=False,
        mocked_outcome="verified_complete",
        reversible=True,
    )


def audit_event(event_id: str, step_id: str) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        request_id=step_id,
        partition="p1",
        principal_ref="principal1",
        profile="delegated_simulation",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=(),
        decision="attempted",
        reason="mocked_effect_admitted",
        outcome="attempted",
        recorded_at=NOW + timedelta(seconds=1),
        proposal_id="proposal1",
        grant_ref="grant1",
    )


class DeliveryBindingTests(unittest.TestCase):
    def test_delivery_id_cannot_be_rebound_to_different_step(self):
        subject = DelegatedSimulation(grant(), session_id="session1", started_at=NOW)
        original = SimulationStep("step1", "delivery1", "act1", "target1")
        first = subject.attempt_step(original, **kwargs())
        collision = subject.attempt_step(
            SimulationStep("step2", "delivery1", "act2", "target1"),
            **kwargs(),
        )
        replay = subject.attempt_step(original, **kwargs())
        self.assertEqual(first.status, "verified_complete")
        self.assertEqual((collision.status, collision.reason), ("denied", "delivery_identity_collision"))
        self.assertEqual(collision.mocked_effects, 0)
        self.assertEqual(collision.step_id, "step2")
        self.assertEqual(collision.delivery_id, "delivery1")
        self.assertEqual(collision.completed_steps, 1)
        self.assertEqual(collision.external_actions, 0)
        self.assertEqual(replay, first)

    def test_audited_collision_is_denied_before_second_audit_admission(self):
        sink = AuditBuffer(max_entries=4)
        subject = AuditedDelegatedSimulation(
            grant(), session_id="session1", started_at=NOW, audit_sink=sink, audit_binding=binding()
        )
        original = SimulationStep("step1", "delivery1", "act1", "target1")
        first = subject.attempt_step(original, audit_event=audit_event("event1", "step1"), **kwargs())
        collision = subject.attempt_step(
            SimulationStep("step2", "delivery1", "act2", "target1"),
            audit_event=audit_event("event2", "step2"),
            **kwargs(),
        )
        self.assertEqual(first.status, "verified_complete")
        self.assertEqual((collision.status, collision.reason), ("denied", "delivery_identity_collision"))
        self.assertEqual(collision.mocked_effects, 0)
        self.assertEqual(len(sink.snapshot()), 1)
        self.assertEqual(sink.snapshot()[0].event_id, "event1")


if __name__ == "__main__":
    unittest.main()
