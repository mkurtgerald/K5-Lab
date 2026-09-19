from mosaic_lab.provider_boundary import ProviderBoundaryContract, run_hardened_interaction_turn
from mosaic_lab.text_interaction import (
    CancellationFlag,
    InteractionInput,
    InteractionSession,
    ProviderReply,
)


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return ProviderReply("ok", "synthetic answer", "provider_ok", 2, 2)


def item(request_id: str = "req1") -> InteractionInput:
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="synthetic question",
    )


def hard_contract() -> ProviderBoundaryContract:
    return ProviderBoundaryContract(
        boundary_id="boundary1",
        hard_timeout_enforced=True,
        hard_cancellation_enforced=True,
        worker_termination_enforced=True,
        max_inflight_calls=2,
    )


def test_missing_hard_boundary_fails_closed_before_provider_call():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=None,
    )

    assert (result.status, result.reason) == ("unavailable", "provider_hard_boundary_required")
    assert provider.calls == 0
    assert result.calls_used == 0
    assert session.turns() == ()
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0


def test_nonterminating_boundary_contract_fails_closed_before_provider_call():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    cooperative = ProviderBoundaryContract(
        boundary_id="boundary1",
        hard_timeout_enforced=True,
        hard_cancellation_enforced=True,
        worker_termination_enforced=False,
        max_inflight_calls=2,
    )

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=cooperative,
    )

    assert result.reason == "provider_hard_boundary_required"
    assert provider.calls == 0
    assert result.calls_used == 0
    assert session.turns() == ()


def test_forged_contract_subclass_is_not_trusted():
    class ForgedContract(ProviderBoundaryContract):
        pass

    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    forged = ForgedContract("boundary1", True, True, True, 2)

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=forged,
    )

    assert result.reason == "provider_hard_boundary_required"
    assert provider.calls == 0


def test_boundary_contract_rejects_truthy_non_boolean_claims():
    try:
        ProviderBoundaryContract("boundary1", 1, True, True, 2)
    except ValueError as exc:
        assert "hard_timeout_enforced" in str(exc)
    else:
        raise AssertionError("truthy integer must not satisfy hard-timeout contract")


def test_qualified_hard_boundary_admits_existing_provider_path():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=hard_contract(),
    )

    assert (result.status, result.reason, result.text) == ("ok", "provider_ok", "synthetic answer")
    assert provider.calls == 1
    assert result.calls_used == 1
    assert len(session.turns()) == 1
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0


def test_pre_call_cancellation_still_blocks_qualified_provider():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    cancellation = CancellationFlag()
    cancellation.cancel()

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=hard_contract(),
        cancellation=cancellation,
    )

    assert (result.status, result.reason) == ("cancelled", "cancelled_before_call")
    assert provider.calls == 0
    assert result.calls_used == 0
    assert session.turns() == ()
