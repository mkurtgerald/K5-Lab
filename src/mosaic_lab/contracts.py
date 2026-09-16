"""Closed, domain-neutral contracts. Values and names are never deployment data."""
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
import re

TOKEN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")


def token(value: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise ValueError("expected an opaque bounded token")
    return value


def unit_score(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be numeric")
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("score out of range")
    return float(value)


def utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timezone-aware timestamp required")
    if value.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Record:
    partition: str
    record_id: str
    source_id: str
    observed_at: datetime
    score: float
    kind: str = "observed"
    parents: tuple[str, ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        for value in (self.partition, self.record_id, self.source_id):
            token(value)
        utc(self.observed_at)
        unit_score(self.score)
        if self.version != "1":
            raise ValueError("unsupported contract version")
        if self.kind not in {"observed", "inferred"}:
            raise ValueError("unsupported record kind")
        if not isinstance(self.parents, tuple) or len(self.parents) > 32:
            raise ValueError("bounded immutable provenance required")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("duplicate provenance")
        for parent in self.parents:
            token(parent)
        if self.record_id in self.parents:
            raise ValueError("self-reference is not provenance")
        if self.kind == "inferred" and not self.parents:
            raise ValueError("inference requires provenance")
        if self.kind == "observed" and self.parents:
            raise ValueError("observations cannot claim inference provenance")


@dataclass(frozen=True)
class Proposal:
    partition: str
    proposal_id: str
    record_id: str
    operation: str
    score: float
    created_at: datetime
    mode: str = "shadow"

    def __post_init__(self) -> None:
        for value in (self.partition, self.proposal_id, self.record_id, self.operation):
            token(value)
        utc(self.created_at)
        unit_score(self.score)
        if self.mode not in {"shadow", "simulate"}:
            raise ValueError("only non-executing modes are supported")
