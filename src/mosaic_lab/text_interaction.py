"""Bounded provider-independent text interaction; no transport or executor."""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from threading import Event, RLock
from time import monotonic
from typing import Callable, Protocol

from .contracts import token

_ACTION = frozenset({"none", "proposed", "awaiting_approval", "denied", "cancelled", "attempted", "verified_complete", "failed", "outcome_unknown"})
_PROVIDER = frozenset({"ok", "abstain", "unavailable", "error"})
_RESULT = _PROVIDER | frozenset({"cancelled", "timeout", "budget_exhausted"})


def _pos_int(value: object, maximum: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
        raise ValueError(f"{field} outside bounded limit")


def _pos_float(value: object, maximum: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(float(value)) or not 0 < float(value) <= maximum:
        raise ValueError(f"{field} outside bounded limit")


def _text(value: object, maximum: int, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value) or len(value) > maximum:
        raise ValueError(f"{field} outside bounded text limit")
    try:
        str.encode(value, "utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{field} must be valid UTF-8 text") from exc
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise ValueError(f"{field} contains unsupported control characters")
    return value


@dataclass(frozen=True)
class InteractionLimits:
    max_context_messages: int = 8
    max_context_chars: int = 4096
    max_turn_chars: int = 1024
    max_output_chars: int = 2048
    max_calls: int = 4
    max_total_tokens: int = 8192
    max_output_tokens: int = 512
    max_total_seconds: float = 30.0
    per_call_timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        for value, maximum, field in (
            (self.max_context_messages, 32, "max_context_messages"),
            (self.max_context_chars, 32768, "max_context_chars"),
            (self.max_turn_chars, 4096, "max_turn_chars"),
            (self.max_output_chars, 8192, "max_output_chars"),
            (self.max_calls, 16, "max_calls"),
            (self.max_total_tokens, 32768, "max_total_tokens"),
            (self.max_output_tokens, 2048, "max_output_tokens"),
        ):
            _pos_int(value, maximum, field)
        _pos_float(self.max_total_seconds, 120.0, "max_total_seconds")
        _pos_float(self.per_call_timeout_seconds, 30.0, "per_call_timeout_seconds")
        if self.max_output_tokens >= self.max_total_tokens:
            raise ValueError("output token budget must leave room for input")


class CancellationFlag:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


@dataclass(frozen=True)
class ActionPresentation:
    status: str = "none"
    receipt_ref: str | None = None
    authoritative: bool = False
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in _ACTION:
            raise ValueError("unsupported action presentation")
        if not isinstance(self.authoritative, bool):
            raise ValueError("authoritative must be boolean")
        if self.receipt_ref is not None:
            token(self.receipt_ref)
        if self.authoritative and self.receipt_ref is None:
            raise ValueError("authoritative state requires receipt reference")
        if self.status == "verified_complete" and not self.authoritative:
            raise ValueError("verified_complete requires authoritative receipt")


@dataclass(frozen=True)
class InteractionInput:
    partition: str
    session_id: str
    request_id: str
    text: str
    evidence_refs: tuple[str, ...] = ()
    action: ActionPresentation = ActionPresentation()
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1":
            raise ValueError("unsupported interaction version")
        for value in (self.partition, self.session_id, self.request_id):
            token(value)
        _text(self.text, 4096, "interaction text")
        if not isinstance(self.evidence_refs, tuple) or len(self.evidence_refs) > 32 or len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("evidence refs must be a bounded unique tuple")
        for value in self.evidence_refs:
            token(value)
        if not isinstance(self.action, ActionPresentation):
            raise ValueError("trusted action presentation required")


@dataclass(frozen=True)
class ProviderMessage:
    role: str
    text: str
    evidence_refs: tuple[str, ...] = ()
    action_status: str = "none"

    def __post_init__(self) -> None:
        if self.role not in {"user", "assistant"} or self.action_status not in _ACTION:
            raise ValueError("invalid provider message")
        _text(self.text, 8192, "provider message")
        if len(self.evidence_refs) > 32:
            raise ValueError("too many evidence refs")
        for value in self.evidence_refs:
            token(value)


@dataclass(frozen=True)
class ProviderRequest:
    request_id: str
    messages: tuple[ProviderMessage, ...]
    max_output_tokens: int
    deadline_monotonic: float
    cancellation: CancellationFlag
    version: str = "1"

    def __post_init__(self) -> None:
        token(self.request_id)
        if self.version != "1" or not isinstance(self.messages, tuple) or not self.messages or len(self.messages) > 32:
            raise ValueError("invalid provider request")
        _pos_int(self.max_output_tokens, 2048, "max_output_tokens")
        if not isinstance(self.deadline_monotonic, (int, float)) or not isfinite(float(self.deadline_monotonic)):
            raise ValueError("deadline must be finite")
        if not isinstance(self.cancellation, CancellationFlag):
            raise ValueError("cancellation flag required")


@dataclass(frozen=True)
class ProviderReply:
    status: str
    text: str = ""
    reason: str = "provider_reply"
    input_tokens: int = 0
    output_tokens: int = 0
    version: str = "1"

    def __post_init__(self) -> None:
        if self.version != "1" or self.status not in _PROVIDER:
            raise ValueError("unsupported provider reply")
        token(self.reason)
        for value in (self.input_tokens, self.output_tokens):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("token counts must be non-negative integers")
        _text(self.text, 8192, "provider reply", empty=self.status != "ok")
        if self.status != "ok" and self.text:
            raise ValueError("non-ok reply cannot carry generated text")


def _validated_provider_reply(value: object) -> ProviderReply | None:
    """Revalidate provider-owned data at the session trust boundary."""
    if type(value) is not ProviderReply:
        return None
    if any(type(field) is not str for field in (value.status, value.text, value.reason, value.version)):
        return None
    if type(value.input_tokens) is not int or type(value.output_tokens) is not int:
        return None
    try:
        return ProviderReply(
            value.status,
            value.text,
            value.reason,
            value.input_tokens,
            value.output_tokens,
            value.version,
        )
    except (TypeError, ValueError, OverflowError):
        return None


class TextProvider(Protocol):
    def complete(self, request: ProviderRequest) -> ProviderReply: ...


@dataclass(frozen=True)
class Turn:
    request_id: str
    user: ProviderMessage
    assistant: ProviderMessage
    charged_tokens: int


@dataclass(frozen=True)
class InteractionResult:
    status: str
    reason: str
    request_id: str
    text: str
    evidence_refs: tuple[str, ...]
    action: ActionPresentation
    calls_used: int
    tokens_used: int
    elapsed_seconds: float
    authorized: bool = False
    execute: bool = False
    external_actions: int = 0

    def __post_init__(self) -> None:
        if self.status not in _RESULT:
            raise ValueError("unsupported interaction result")
        token(self.reason)
        token(self.request_id)
        if self.authorized is not False or self.execute is not False or self.external_actions != 0:
            raise ValueError("interaction cannot grant execution authority")


class InteractionSession:
    """One bounded interaction session.

    Calls are intentionally serialized per session so request replay checks,
    context selection and resource accounting are atomic relative to one
    another. Provider cancellation/timeouts remain cooperative; a private
    adapter must honor the supplied deadline/cancellation contract.
    """

    def __init__(self, *, partition: str, session_id: str, limits: InteractionLimits = InteractionLimits()) -> None:
        self.partition = token(partition)
        self.session_id = token(session_id)
        if not isinstance(limits, InteractionLimits):
            raise ValueError("limits required")
        self.limits = limits
        self._turns: list[Turn] = []
        self._attempted: set[str] = set()
        self._calls = 0
        self._tokens = 0
        self._elapsed = 0.0
        self._lock = RLock()

    @property
    def calls_used(self) -> int:
        with self._lock:
            return self._calls

    @property
    def tokens_used(self) -> int:
        with self._lock:
            return self._tokens

    @property
    def elapsed_seconds(self) -> float:
        with self._lock:
            return self._elapsed

    def turns(self) -> tuple[Turn, ...]:
        with self._lock:
            return tuple(self._turns)

    def _result(self, item: InteractionInput, status: str, reason: str, text: str = "") -> InteractionResult:
        with self._lock:
            return InteractionResult(status, reason, item.request_id, text, item.evidence_refs, item.action, self._calls, self._tokens, self._elapsed)


def _bytes(message: ProviderMessage) -> int:
    return len(message.text.encode()) + len(message.action_status.encode()) + sum(len(v.encode()) for v in message.evidence_refs)


def _context(session: InteractionSession, current: ProviderMessage) -> tuple[ProviderMessage, ...] | None:
    if _bytes(current) > session.limits.max_context_chars:
        return None
    chosen: list[Turn] = []
    count = 1
    chars = _bytes(current)
    for turn in reversed(session._turns):
        pair_chars = _bytes(turn.user) + _bytes(turn.assistant)
        if count + 2 > session.limits.max_context_messages or chars + pair_chars > session.limits.max_context_chars:
            break
        chosen.append(turn)
        count += 2
        chars += pair_chars
    messages: list[ProviderMessage] = []
    for turn in reversed(chosen):
        messages.extend((turn.user, turn.assistant))
    messages.append(current)
    return tuple(messages)


def run_interaction_turn(
    session: InteractionSession,
    item: InteractionInput,
    provider: TextProvider,
    *,
    cancellation: CancellationFlag | None = None,
    clock: Callable[[], float] = monotonic,
) -> InteractionResult:
    """Run one cooperative bounded call; only successful turns enter context.

    The complete turn is serialized by the session lock. This intentionally
    prevents concurrent duplicate delivery or concurrent budget oversubscription
    from causing multiple provider calls for one session.
    """
    if not isinstance(session, InteractionSession):
        raise ValueError("interaction session required")
    if not isinstance(item, InteractionInput):
        raise ValueError("interaction input required")

    with session._lock:
        if item.partition != session.partition or item.session_id != session.session_id:
            return session._result(item, "error", "session_scope_mismatch")
        if len(item.text) > session.limits.max_turn_chars:
            return session._result(item, "budget_exhausted", "turn_char_limit")
        cancel = cancellation or CancellationFlag()
        if cancel.cancelled:
            return session._result(item, "cancelled", "cancelled_before_call")
        if item.request_id in session._attempted:
            return session._result(item, "error", "duplicate_request")
        if session._calls >= session.limits.max_calls:
            return session._result(item, "budget_exhausted", "call_limit")
        if session._elapsed >= session.limits.max_total_seconds:
            return session._result(item, "budget_exhausted", "time_budget")

        current = ProviderMessage("user", item.text, item.evidence_refs, item.action.status)
        messages = _context(session, current)
        if messages is None:
            return session._result(item, "budget_exhausted", "context_char_limit")
        local_input = sum(max(1, _bytes(message)) for message in messages)
        if local_input + session.limits.max_output_tokens > session.limits.max_total_tokens - session._tokens:
            return session._result(item, "budget_exhausted", "token_budget_preflight")

        try:
            start = float(clock())
        except Exception:
            return session._result(item, "error", "clock_failure")
        if not isfinite(start):
            return session._result(item, "error", "clock_failure")
        allowed = min(session.limits.per_call_timeout_seconds, session.limits.max_total_seconds - session._elapsed)
        deadline = start + allowed
        if not isfinite(deadline) or deadline <= start:
            return session._result(item, "error", "clock_failure")
        request = ProviderRequest(item.request_id, messages, session.limits.max_output_tokens, deadline, cancel)
        session._attempted.add(item.request_id)
        session._calls += 1
        try:
            reply = provider.complete(request)
        except Exception:
            try:
                end = float(clock())
            except Exception:
                end = start
            if isfinite(end) and end >= start:
                session._elapsed += end - start
                if cancel.cancelled:
                    return session._result(item, "cancelled", "cancelled_during_call")
                if end >= request.deadline_monotonic or session._elapsed > session.limits.max_total_seconds:
                    return session._result(item, "timeout", "provider_timeout")
            return session._result(item, "error", "provider_exception")
        try:
            end = float(clock())
        except Exception:
            return session._result(item, "error", "clock_failure")
        if not isfinite(end) or end < start:
            return session._result(item, "error", "clock_regression")
        session._elapsed += end - start
        cancelled = cancel.cancelled
        timed_out = end >= request.deadline_monotonic or session._elapsed > session.limits.max_total_seconds
        validated_reply = _validated_provider_reply(reply)

        charged = 0
        effective_output = 0
        if validated_reply is not None:
            local_output = len(validated_reply.text.encode()) if validated_reply.text else 0
            accounting_cap = session.limits.max_total_tokens + 1
            input_claim = min(validated_reply.input_tokens, accounting_cap)
            output_claim = min(validated_reply.output_tokens, accounting_cap)
            effective_output = max(local_output, output_claim)
            charged = max(local_input, input_claim) + effective_output
            session._tokens = min(accounting_cap, session._tokens + charged)

        if cancelled:
            return session._result(item, "cancelled", "cancelled_during_call")
        if timed_out:
            return session._result(item, "timeout", "provider_timeout")
        if validated_reply is None:
            return session._result(item, "error", "invalid_provider_reply")
        reply = validated_reply
        if effective_output > session.limits.max_output_tokens:
            return session._result(item, "error", "provider_output_token_limit")
        if len(reply.text) > session.limits.max_output_chars:
            return session._result(item, "error", "provider_output_char_limit")
        if session._tokens > session.limits.max_total_tokens:
            return session._result(item, "budget_exhausted", "reported_token_budget")
        if reply.status != "ok":
            return session._result(item, reply.status, reply.reason)

        assistant = ProviderMessage("assistant", reply.text)
        session._turns.append(Turn(item.request_id, current, assistant, charged))
        return session._result(item, "ok", reply.reason, reply.text)