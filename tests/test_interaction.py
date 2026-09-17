from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.interaction import (
    EvidenceRef,
    TrustedAuthority,
    effect_digest,
    evaluate_proposal,
    parse_untrusted_proposal,
)


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def payload(**changes):
    value = {
        "version": "1",
        "partition": "p1",
        "request_id": "req1",
        "proposal_id": "prop1",
        "action_ref": "act1",
        "target_ref": "target1",
        "parameters": {"level": "medium"},
        "evidence_refs": ["rec1"],
        "issued_at": (NOW - timedelta(seconds=5)).isoformat(),
        "expires_at": (NOW + timedelta(seconds=30)).isoformat(),
        "untrusted_score": 1.0,
        "untrusted_rationale": "model supplied text",
    }
    value.update(changes)
    return value


def authority(**changes):
    value = {
        "partition": "p1",
        "principal_ref": "principal1",
        "profile": "approval_required",
        "allowed_actions": ("act1",),
        "allowed_targets": ("target1",),
        "policy_revision": "policy1",
        "valid_until": NOW + timedelta(minutes=5),
        "authenticated": True,
    }
    value.update(changes)
    return TrustedAuthority(**value)


def evidence(**changes):
    value = {
        "partition": "p1",
        "record_id": "rec1",
        "observed_at": NOW - timedelta(seconds=10),
    }
    value.update(changes)
    return {"rec1": EvidenceRef(**value)}


class InteractionBoundaryTests(unittest.TestCase):
    def test_matching_proposal_awaits_approval_without_authority(self):
        proposal = parse_untrusted_proposal(payload())
        receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual(receipt.status, "awaiting_approval")
        self.assertEqual(receipt.reason, "approval_required")
        self.assertFalse(receipt.authorized)
        self.assertFalse(receipt.execute)
        self.assertEqual(receipt.external_actions, 0)

    def test_forged_approval_and_identity_fields_are_rejected(self):
        for field in ("approved", "principal_ref", "permissions", "policy_revision"):
            candidate = payload()
            candidate[field] = True
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    parse_untrusted_proposal(candidate)

    def test_untrusted_score_and_rationale_do_not_change_effect_digest(self):
        first = parse_untrusted_proposal(payload(untrusted_score=0.0, untrusted_rationale="a"))
        second = parse_untrusted_proposal(payload(untrusted_score=1.0, untrusted_rationale="b"))
        self.assertEqual(effect_digest(first), effect_digest(second))

    def test_unauthenticated_context_denies_even_with_max_model_score(self):
        proposal = parse_untrusted_proposal(payload(untrusted_score=1.0))
        receipt = evaluate_proposal(
            proposal,
            authority(authenticated=False),
            evidence=evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "unauthenticated"))
        self.assertFalse(receipt.authorized)

    def test_cross_partition_proposal_denied(self):
        proposal = parse_untrusted_proposal(payload(partition="p2"))
        receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "partition_mismatch"))

    def test_cross_partition_evidence_denied(self):
        proposal = parse_untrusted_proposal(payload())
        receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=evidence(partition="p2"),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "cross_partition_evidence"))

    def test_unknown_action_and_target_deny(self):
        for field, reason in (("action_ref", "action_out_of_scope"), ("target_ref", "target_out_of_scope")):
            proposal = parse_untrusted_proposal(payload(**{field: "unknown"}))
            receipt = evaluate_proposal(
                proposal,
                authority(),
                evidence=evidence(),
                current_policy_revision="policy1",
                now=NOW,
            )
            self.assertEqual((receipt.status, receipt.reason), ("denied", reason))

    def test_policy_change_denies(self):
        proposal = parse_untrusted_proposal(payload())
        receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=evidence(),
            current_policy_revision="policy2",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "policy_changed"))

    def test_expired_proposal_and_authority_deny(self):
        proposal = parse_untrusted_proposal(
            payload(
                issued_at=(NOW - timedelta(minutes=2)).isoformat(),
                expires_at=(NOW - timedelta(seconds=1)).isoformat(),
            )
        )
        receipt = evaluate_proposal(
            proposal,
            authority(),
            evidence=evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "proposal_expired"))

        fresh = parse_untrusted_proposal(payload())
        expired_authority = authority(valid_until=NOW - timedelta(seconds=1))
        receipt = evaluate_proposal(
            fresh,
            expired_authority,
            evidence=evidence(),
            current_policy_revision="policy1",
            now=NOW,
        )
        self.assertEqual((receipt.status, receipt.reason), ("denied", "authority_expired"))

    def test_missing_stale_and_future_evidence_abstain(self):
        proposal = parse_untrusted_proposal(payload())
        cases = (
            ({}, "missing_evidence"),
            (evidence(observed_at=NOW - timedelta(minutes=3)), "stale_evidence"),
            (evidence(observed_at=NOW + timedelta(seconds=1)), "future_evidence"),
        )
        for items, reason in cases:
            with self.subTest(reason=reason):
                receipt = evaluate_proposal(
                    proposal,
                    authority(),
                    evidence=items,
                    current_policy_revision="policy1",
                    now=NOW,
                    max_evidence_age_seconds=60,
                )
                self.assertEqual((receipt.status, receipt.reason), ("abstain", reason))

    def test_read_only_profile_denies_and_other_profiles_stay_non_executing(self):
        proposal = parse_untrusted_proposal(payload())
        expected = {
            "read_only": ("denied", "profile_read_only"),
            "recommend": ("recommendation", "non_executing_only"),
            "approval_required": ("awaiting_approval", "approval_required"),
            "delegated_simulation": ("recommendation", "simulation_only"),
        }
        for profile, result in expected.items():
            with self.subTest(profile=profile):
                receipt = evaluate_proposal(
                    proposal,
                    authority(profile=profile),
                    evidence=evidence(),
                    current_policy_revision="policy1",
                    now=NOW,
                )
                self.assertEqual((receipt.status, receipt.reason), result)
                self.assertFalse(receipt.authorized)
                self.assertFalse(receipt.execute)
                self.assertEqual(receipt.external_actions, 0)

    def test_parameter_and_evidence_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            parse_untrusted_proposal(payload(parameters={f"k{i}": "v" for i in range(17)}))
        with self.assertRaises(ValueError):
            parse_untrusted_proposal(payload(evidence_refs=[f"r{i}" for i in range(33)]))

    def test_nonfinite_model_score_rejected(self):
        with self.assertRaises(ValueError):
            parse_untrusted_proposal(payload(untrusted_score=float("nan")))

    def test_effect_digest_changes_for_effect_fields(self):
        proposal = parse_untrusted_proposal(payload())
        changed = replace(proposal, target_ref="target2")
        self.assertNotEqual(effect_digest(proposal), effect_digest(changed))


if __name__ == "__main__":
    unittest.main()
