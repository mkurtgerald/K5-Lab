from mosaic_lab.text_interaction import (
    CancellationFlag,
    InteractionInput,
    InteractionLimits,
    InteractionSession,
    ProviderReply,
    run_interaction_turn,
)


class Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class RaisingProvider:
    def __init__(self, *, clock: Clock, advance: float = 0.0, cancel: CancellationFlag | None = None) -> None:
        self.clock = clock
        self.advance = advance
        self.cancel = cancel
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.advance:
            self.clock.advance(self.advance)
        if self.cancel is not None:
            self.cancel.cancel()
        raise RuntimeError("synthetic provider failure")


def item(request_id: str = "req1") -> InteractionInput:
    return InteractionInput(partition="p1", session_id="s1", request_id=request_id, text="question")


def test_cancelled_raising_provider_reports_cancelled_and_commits_no_turn():
    clock = Clock()
    flag = CancellationFlag()
    session = InteractionSession(partition="p1", session_id="s1")
    provider = RaisingProvider(clock=clock, cancel=flag)

    result = run_interaction_turn(session, item(), provider, cancellation=flag, clock=clock)

    assert (result.status, result.reason) == ("cancelled", "cancelled_during_call")
    assert result.calls_used == 1
    assert result.external_actions == 0
    assert session.turns() == ()


def test_timed_out_raising_provider_reports_timeout_and_accounts_elapsed():
    clock = Clock()
    limits = InteractionLimits(per_call_timeout_seconds=1.0, max_total_seconds=2.0)
    session = InteractionSession(partition="p1", session_id="s1", limits=limits)
    provider = RaisingProvider(clock=clock, advance=1.0)

    result = run_interaction_turn(session, item(), provider, clock=clock)

    assert (result.status, result.reason) == ("timeout", "provider_timeout")
    assert result.elapsed_seconds == 1.0
    assert result.calls_used == 1
    assert result.external_actions == 0
    assert session.turns() == ()


def test_cancellation_precedes_timeout_when_both_happen_during_failure():
    clock = Clock()
    flag = CancellationFlag()
    limits = InteractionLimits(per_call_timeout_seconds=1.0, max_total_seconds=2.0)
    session = InteractionSession(partition="p1", session_id="s1", limits=limits)
    provider = RaisingProvider(clock=clock, advance=1.5, cancel=flag)

    result = run_interaction_turn(session, item(), provider, cancellation=flag, clock=clock)

    assert (result.status, result.reason) == ("cancelled", "cancelled_during_call")
    assert result.elapsed_seconds == 1.5
    assert result.external_actions == 0
    assert session.turns() == ()


def test_fast_provider_exception_remains_provider_exception():
    clock = Clock()
    session = InteractionSession(partition="p1", session_id="s1")
    provider = RaisingProvider(clock=clock)

    result = run_interaction_turn(session, item(), provider, clock=clock)

    assert (result.status, result.reason) == ("error", "provider_exception")
    assert result.elapsed_seconds == 0.0
    assert session.turns() == ()
