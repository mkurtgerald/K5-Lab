from datetime import datetime, timedelta, timezone

from mosaic_lab.interaction import EvidenceRef, ProposalEnvelope, TrustedAuthority, evaluate_proposal

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)


class BrokenEvidence:
    def get(self, record_id):
        raise RuntimeError("synthetic evidence backend failure")


def proposal():
    return ProposalEnvelope(
        partition="p1",
        request_id="req1",
        proposal_id="prop1",
        action_ref="a1",
        target_ref="t1",
        parameters=(),
        evidence_refs=("rec1",),
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )


def authority():
    return TrustedAuthority(
        partition="p1",
        principal_ref="principal1",
        profile="recommend",
        allowed_actions=("a1",),
        allowed_targets=("t1",),
        policy_revision="policy1",
        valid_until=NOW + timedelta(minutes=1),
    )


def test_evidence_provider_exception_abstains_without_authority():
    valid = evaluate_proposal(
        proposal(),
        authority(),
        evidence={"rec1": EvidenceRef("p1", "rec1", NOW - timedelta(seconds=1))},
        current_policy_revision="policy1",
        now=NOW,
    )
    assert valid.status == "recommendation"

    result = evaluate_proposal(
        proposal(),
        authority(),
        evidence=BrokenEvidence(),
        current_policy_revision="policy1",
        now=NOW,
    )
    assert (result.status, result.reason) == ("abstain", "evidence_unavailable")
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0
