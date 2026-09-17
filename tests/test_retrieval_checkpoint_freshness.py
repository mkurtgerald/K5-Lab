from datetime import datetime, timedelta, timezone

import pytest

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def scope():
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=("rec1",),
        valid_until=NOW + timedelta(minutes=10),
    )


def session_with_cached_record(*, observed_at=NOW - timedelta(seconds=5)):
    store = SyntheticEvidenceStore()
    store.add(
        EvidenceRecord(
            partition="p1",
            record_id="rec1",
            source_ref="source1",
            observed_at=observed_at,
            text="synthetic checkpoint evidence",
        )
    )
    session = RetrievalSession(
        session_id="s1",
        partition="p1",
        principal_ref="principal1",
        policy_revision="policy1",
    )
    result = session.retrieve(
        "req1",
        "rec1",
        store,
        scope(),
        current_policy_revision="policy1",
        now=NOW,
        max_age_seconds=60,
    )
    assert result.status == "returned"
    return session


def test_resumed_checkpoint_expires_even_while_scope_is_still_valid():
    session = session_with_cached_record()
    checkpoint = session.create_checkpoint(("rec1",), now=NOW)

    result = session.validate_checkpoint(
        checkpoint,
        scope(),
        current_policy_revision="policy1",
        now=NOW + timedelta(seconds=61),
        max_age_seconds=60,
    )

    assert (result.status, result.reason) == ("denied", "checkpoint_stale")
    assert result.evidence_refs == ()
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0


def test_fresh_checkpoint_cannot_resurrect_stale_cached_evidence():
    session = session_with_cached_record(observed_at=NOW - timedelta(seconds=50))
    checkpoint = session.create_checkpoint(("rec1",), now=NOW)

    result = session.validate_checkpoint(
        checkpoint,
        scope(),
        current_policy_revision="policy1",
        now=NOW + timedelta(seconds=20),
        max_age_seconds=60,
    )

    assert (result.status, result.reason) == ("denied", "checkpoint_evidence_stale")
    assert result.evidence_refs == ()


def test_future_checkpoint_fails_closed():
    session = session_with_cached_record()
    checkpoint = session.create_checkpoint(("rec1",), now=NOW + timedelta(seconds=1))

    result = session.validate_checkpoint(
        checkpoint,
        scope(),
        current_policy_revision="policy1",
        now=NOW,
        max_age_seconds=60,
    )

    assert (result.status, result.reason) == ("denied", "checkpoint_future")


def test_fresh_checkpoint_remains_non_authorizing():
    session = session_with_cached_record()
    checkpoint = session.create_checkpoint(("rec1",), now=NOW)

    result = session.validate_checkpoint(
        checkpoint,
        scope(),
        current_policy_revision="policy1",
        now=NOW + timedelta(seconds=10),
        max_age_seconds=60,
    )

    assert (result.status, result.reason) == ("accepted_for_read", "checkpoint_valid")
    assert result.evidence_refs == ("rec1",)
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0


@pytest.mark.parametrize("max_age_seconds", [0, -1, float("inf"), float("nan"), True])
def test_checkpoint_age_bound_must_be_positive_finite_number(max_age_seconds):
    session = session_with_cached_record()
    checkpoint = session.create_checkpoint(("rec1",), now=NOW)

    with pytest.raises(ValueError):
        session.validate_checkpoint(
            checkpoint,
            scope(),
            current_policy_revision="policy1",
            now=NOW,
            max_age_seconds=max_age_seconds,
        )
