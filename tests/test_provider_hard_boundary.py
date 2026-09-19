from threading import Event, Lock, Thread

from mosaic_lab.provider_boundary import (
    ProviderBoundaryContract,
    ProviderBoundaryGate,
    run_hardened_interaction_turn,
)
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


class BlockingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.active = 0
        self.peak_active = 0
        self.entered = Event()
        self.release = Event()
        self._lock = Lock()

    def complete(self, request):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            self.entered.set()
        self.release.wait(2.0)
        with self._lock:
            self.active -= 1
        return ProviderReply("ok", "synthetic answer", "provider_ok", 2, 2)


def item(request_id: str = "req1", session_id: str = "s1") -> InteractionInput:
    return InteractionInput(
        partition="p1",
        session_id=session_id,
        request_id=request_id,
        text="synthetic question",
    )


def hard_contract(max_inflight_calls: int = 2) -> ProviderBoundaryContract:
    return ProviderBoundaryContract(
        boundary_id="boundary1",
        hard_timeout_enforced=True,
        hard_cancellation_enforced=True,
        worker_termination_enforced=True,
        max_inflight_calls=max_inflight_calls,
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


def test_missing_shared_admission_gate_fails_closed_before_provider_call():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    contract = hard_contract()

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=contract,
    )

    assert (result.status, result.reason) == ("unavailable", "provider_inflight_gate_required")
    assert provider.calls == 0
    assert result.calls_used == 0
    assert session.turns() == ()


def test_mismatched_admission_gate_fails_closed_before_provider_call():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    contract = hard_contract(max_inflight_calls=1)
    other = ProviderBoundaryContract("boundary2", True, True, True, 1)
    gate = ProviderBoundaryGate(other)

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=contract,
        admission_gate=gate,
    )

    assert result.reason == "provider_inflight_gate_required"
    assert provider.calls == 0
    assert result.calls_used == 0


def test_qualified_hard_boundary_admits_existing_provider_path():
    session = InteractionSession(partition="p1", session_id="s1")
    provider = CountingProvider()
    contract = hard_contract()
    gate = ProviderBoundaryGate(contract)

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=contract,
        admission_gate=gate,
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
    contract = hard_contract()
    gate = ProviderBoundaryGate(contract)

    result = run_hardened_interaction_turn(
        session,
        item(),
        provider,
        execution_contract=contract,
        admission_gate=gate,
        cancellation=cancellation,
    )

    assert (result.status, result.reason) == ("cancelled", "cancelled_before_call")
    assert provider.calls == 0
    assert result.calls_used == 0
    assert session.turns() == ()


def test_max_inflight_bound_rejects_second_call_before_provider_entry():
    contract = hard_contract(max_inflight_calls=1)
    gate = ProviderBoundaryGate(contract)
    provider = BlockingProvider()
    first_session = InteractionSession(partition="p1", session_id="s1")
    second_session = InteractionSession(partition="p1", session_id="s2")
    first_result = {}

    def run_first() -> None:
        first_result["value"] = run_hardened_interaction_turn(
            first_session,
            item("req1", "s1"),
            provider,
            execution_contract=contract,
            admission_gate=gate,
        )

    worker = Thread(target=run_first)
    worker.start()
    assert provider.entered.wait(1.0)
    try:
        second = run_hardened_interaction_turn(
            second_session,
            item("req2", "s2"),
            provider,
            execution_contract=contract,
            admission_gate=gate,
        )
    finally:
        provider.release.set()
        worker.join(2.0)

    assert not worker.is_alive()
    assert (second.status, second.reason) == ("unavailable", "provider_inflight_limit_reached")
    assert second.calls_used == 0
    assert second_session.turns() == ()
    assert provider.calls == 1
    assert provider.peak_active == 1
    assert first_result["value"].status == "ok"
    assert second.authorized is False
    assert second.execute is False
    assert second.external_actions == 0


def test_admission_gate_is_released_after_provider_exception():
    class RaisingProvider:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request):
            self.calls += 1
            raise RuntimeError("synthetic provider failure")

    contract = hard_contract(max_inflight_calls=1)
    gate = ProviderBoundaryGate(contract)
    provider = RaisingProvider()
    first = run_hardened_interaction_turn(
        InteractionSession(partition="p1", session_id="s1"),
        item("req1", "s1"),
        provider,
        execution_contract=contract,
        admission_gate=gate,
    )
    second = run_hardened_interaction_turn(
        InteractionSession(partition="p1", session_id="s2"),
        item("req2", "s2"),
        provider,
        execution_contract=contract,
        admission_gate=gate,
    )

    assert (first.status, first.reason) == ("error", "provider_exception")
    assert (second.status, second.reason) == ("error", "provider_exception")
    assert provider.calls == 2


def test_reconstructed_gate_cannot_bypass_boundary_inflight_limit():
    contract = hard_contract(max_inflight_calls=1)
    first_gate = ProviderBoundaryGate(contract)
    second_gate = ProviderBoundaryGate(contract)
    provider = BlockingProvider()
    first_session = InteractionSession(partition="p1", session_id="s1")
    second_session = InteractionSession(partition="p1", session_id="s2")
    first_result = {}

    def run_first() -> None:
        first_result["value"] = run_hardened_interaction_turn(
            first_session,
            item("req1", "s1"),
            provider,
            execution_contract=contract,
            admission_gate=first_gate,
        )

    worker = Thread(target=run_first)
    worker.start()
    assert provider.entered.wait(1.0)
    try:
        second = run_hardened_interaction_turn(
            second_session,
            item("req2", "s2"),
            provider,
            execution_contract=contract,
            admission_gate=second_gate,
        )
    finally:
        provider.release.set()
        worker.join(2.0)

    assert not worker.is_alive()
    assert (second.status, second.reason) == ("unavailable", "provider_inflight_limit_reached")
    assert second.calls_used == 0
    assert second_session.turns() == ()
    assert provider.calls == 1
    assert provider.peak_active == 1
    assert first_result["value"].status == "ok"
    assert second.authorized is False
    assert second.execute is False
    assert second.external_actions == 0
