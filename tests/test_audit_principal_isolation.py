from datetime import datetime, timedelta, timezone

from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.retrieval import ReadScope


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
DIGEST = "d" * 64


def _scope(*, allowed_record_ids=("rec1",)) -> ReadScope:
    return ReadScope(
        partition="p1",
        principal_ref="principal1",
        profile="read_only",
        policy_revision="policy1",
        allowed_record_ids=allowed_record_ids,
        valid_until=NOW + timedelta(minutes=5),
    )


def _event(
    event_id: str,
    *,
    principal_ref: str,
    request_id: str,
    evidence_refs=("rec1",),
) -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        request_id=request_id,
        partition="p1",
        principal_ref=principal_ref,
        profile="approval_required",
        policy_revision="policy1",
        model_revision="model1",
        tool_revision="tool1",
        evidence_refs=evidence_refs,
        evidence_digests=tuple(DIGEST for _ in evidence_refs),
        decision="denied",
        reason="policy_changed",
        outcome="denied",
        recorded_at=NOW,
    )


def test_cross_principal_material_is_filtered_without_poisoning_authorized_read():
    buffer = AuditBuffer()
    own = _event("event1", principal_ref="principal1", request_id="req1")
    foreign = _event(
        "event2",
        principal_ref="principal2",
        request_id="req2",
        evidence_refs=("foreign_rec",),
    )
    buffer.append(own)
    buffer.append(foreign)

    result = buffer.read_partition(
        "p1",
        _scope(),
        current_policy_revision="policy1",
        now=NOW,
    )

    assert (result.status, result.reason) == ("returned", "audit_returned")
    assert result.events == (own,)
    assert foreign not in result.events


def test_same_principal_out_of_scope_evidence_still_fails_closed():
    buffer = AuditBuffer()
    buffer.append(_event("event1", principal_ref="principal1", request_id="req1"))
    buffer.append(
        _event(
            "event2",
            principal_ref="principal1",
            request_id="req2",
            evidence_refs=("rec2",),
        )
    )

    result = buffer.read_partition(
        "p1",
        _scope(),
        current_policy_revision="policy1",
        now=NOW,
    )

    assert (result.status, result.reason) == ("denied", "audit_evidence_out_of_scope")
    assert result.events == ()
