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


class TimedProvider:
    def __init__(
        self,
        *,
        clock: Clock,
        advance: float,
        reply: ProviderReply,
        cancel: CancellationFlag | None = None,
    ) -> None:
        self.clock = clock
        self.advance = advance
        self.reply = reply
        self.cancel = cancel
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        self.clock.advance(self.advance)
        if self.cancel is not None:
            self.cancel.cancel()
        return self.reply


def item(request_id: str = "req1") -> InteractionInput:
    return InteractionInput(
        partition="p1",
        session_id="s1",
        request_id=request_id,
        text="synthetic question",
    )


def limits() -> InteractionLimits:
    return InteractionLimits(
        per_call_timeout_seconds=1.0,
        max_total_seconds=2.0,
        max_total_tokens=4096,
        max_output_tokens=128,
    )


def test_timeout_dominates_late_generated_text_and_commits_no_turn():
    clock = Clock()
    session = InteractionSession(partition="p1", session_id="s1", limits=limits())
    provider = TimedProvider(
        clock=clock,
        advance=1.0,
        reply=ProviderReply("ok", "late text", "provider_ok", 4, 2),
    )

    result = run_interaction_turn(session, item(), provider, clock=clock)

    assert (result.status, result.reason, result.text) == ("timeout", "provider_timeout", "")
    assert result.calls_used == 1
    assert result.elapsed_seconds == 1.0
    assert result.tokens_used > 0
    assert result.authorized is False
    assert result.execute is False
    assert result.external_actions == 0
    assert session.turns() == ()


def test_timeout_dominates_provider_reported_error_after_deadline():
    clock = Clock()
    session = InteractionSession(partition="p1", session_id="s1", limits=limits())
    provider = TimedProvider(
        clock=clock,
        advance=1.0,
        reply=ProviderReply("error", reason="provider_error", input_tokens=4),
    )

    result = run_interaction_turn(session, item(), provider, clock=clock)

    assert (result.status, result.reason) == ("timeout", "provider_timeout")
    assert result.external_actions == 0
    assert session.turns() == ()


def test_cancellation_dominates_timeout_and_generated_text():
    clock = Clock()
    flag = CancellationFlag()
    session = InteractionSession(partition="p1", session_id="s1", limits=limits())
    provider = TimedProvider(
        clock=clock,
        advance=1.5,
        reply=ProviderReply("ok", "must not commit", "provider_ok", 4, 2),
        cancel=flag,
    )

    result = run_interaction_turn(session, item(), provider, cancellation=flag, clock=clock)

    assert (result.status, result.reason, result.text) == ("cancelled", "cancelled_during_call", "")
    assert result.elapsed_seconds == 1.5
    assert result.calls_used == 1
    assert result.tokens_used > 0
    assert result.external_actions == 0
    assert session.turns() == ()


def test_timed_out_request_cannot_be_replayed_into_second_provider_call():
    clock = Clock()
    session = InteractionSession(partition="p1", session_id="s1", limits=limits())
    provider = TimedProvider(
        clock=clock,
        advance=1.0,
        reply=ProviderReply("ok", "late text", "provider_ok", 4, 2),
    )

    first = run_interaction_turn(session, item(), provider, clock=clock)
    second = run_interaction_turn(session, item(), provider, clock=clock)

    assert first.reason == "provider_timeout"
    assert (second.status, second.reason) == ("error", "duplicate_request")
    assert len(provider.requests) == 1
    assert session.turns() == ()


def test_repeated_timeouts_exhaust_total_session_time_budget():
    clock = Clock()
    session = InteractionSession(partition="p1", session_id="s1", limits=limits())
    provider = TimedProvider(
        clock=clock,
        advance=1.0,
        reply=ProviderReply("unavailable", reason="provider_unavailable", input_tokens=1),
    )

    first = run_interaction_turn(session, item("req1"), provider, clock=clock)
    second = run_interaction_turn(session, item("req2"), provider, clock=clock)
    third = run_interaction_turn(session, item("req3"), provider, clock=clock)

    assert first.reason == "provider_timeout"
    assert second.reason == "provider_timeout"
    assert (third.status, third.reason) == ("budget_exhausted", "time_budget")
    assert len(provider.requests) == 2
    assert session.elapsed_seconds == 2.0
    assert session.turns() == ()
