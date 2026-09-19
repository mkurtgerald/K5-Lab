from threading import Event, Lock, RLock, Thread

from mosaic_lab.provider_boundary import (
    ProviderBoundaryContract,
    ProviderBoundaryGate,
    run_hardened_interaction_turn,
)
from mosaic_lab.text_interaction import InteractionInput, InteractionSession, ProviderReply


class CountingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def complete(self, request):
        with self._lock:
            self.calls += 1
        return ProviderReply("ok", "synthetic answer", "provider_ok", 2, 2)


class ObservableRLock:
    """Test-only lock that signals an attempted session-lock entry."""

    def __init__(self) -> None:
        self._lock = RLock()
        self.enter_attempted = Event()

    def __enter__(self):
        self.enter_attempted.set()
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
        return False

    def hold_for_test(self) -> None:
        self._lock.acquire()

    def release_for_test(self) -> None:
        self._lock.release()


def _item(request_id: str, session_id: str) -> InteractionInput:
    return InteractionInput(
        partition="p1",
        session_id=session_id,
        request_id=request_id,
        text="synthetic question",
    )


def _contract() -> ProviderBoundaryContract:
    return ProviderBoundaryContract(
        boundary_id="boundary_fairness",
        hard_timeout_enforced=True,
        hard_cancellation_enforced=True,
        worker_termination_enforced=True,
        max_inflight_calls=1,
    )


def test_same_session_waiter_does_not_consume_global_provider_capacity():
    contract = _contract()
    gate = ProviderBoundaryGate(contract)
    provider = CountingProvider()
    blocked_session = InteractionSession(partition="p1", session_id="s1")
    other_session = InteractionSession(partition="p1", session_id="s2")
    observable = ObservableRLock()
    blocked_session._lock = observable
    blocked_result = {}
    started = Event()

    def run_blocked() -> None:
        started.set()
        blocked_result["value"] = run_hardened_interaction_turn(
            blocked_session,
            _item("req1", "s1"),
            provider,
            execution_contract=contract,
            admission_gate=gate,
        )

    observable.hold_for_test()
    worker = Thread(target=run_blocked)
    worker.start()
    assert started.wait(1.0)
    assert observable.enter_attempted.wait(1.0)
    try:
        other = run_hardened_interaction_turn(
            other_session,
            _item("req2", "s2"),
            provider,
            execution_contract=contract,
            admission_gate=gate,
        )
    finally:
        observable.release_for_test()
        worker.join(2.0)

    assert not worker.is_alive()
    assert (other.status, other.reason) == ("ok", "provider_ok")
    assert blocked_result["value"].status == "ok"
    assert provider.calls == 2
    assert other.authorized is False
    assert other.execute is False
    assert other.external_actions == 0
