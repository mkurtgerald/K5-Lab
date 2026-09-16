"""Bounded, domain-neutral in-memory event memory and correlation mechanics."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from math import isfinite

from .contracts import token, unit_score, utc

MAX_PARENTS = 32
MAX_CORRELATION_EVENTS = 32
MAX_EVENTS_LIMIT = 10_000
MAX_PARTITIONS_LIMIT = 1_024
MAX_AGE_LIMIT_SECONDS = 31_536_000.0


class MemoryConflict(ValueError):
    """An event identifier was reused with different immutable content."""


class MissingReference(ValueError):
    """A required resident event or provenance reference was not available."""


def _positive_bound(value: object, *, name: str, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric")
    number = float(value)
    if not isfinite(number) or number <= 0.0 or number > maximum:
        raise ValueError(f"{name} out of range")
    return number


@dataclass(frozen=True)
class Event:
    partition: str
    event_id: str
    entity_key: str
    event_type: str
    source_ref: str
    event_at: datetime
    observed_at: datetime
    confidence: float
    abstained: bool = False
    parents: tuple[str, ...] = ()
    version: str = "1"

    def __post_init__(self) -> None:
        for value in (
            self.partition,
            self.event_id,
            self.entity_key,
            self.event_type,
            self.source_ref,
        ):
            token(value)
        utc(self.event_at)
        utc(self.observed_at)
        unit_score(self.confidence)
        if not isinstance(self.abstained, bool):
            raise ValueError("abstained must be boolean")
        if self.version != "1":
            raise ValueError("unsupported event version")
        if not isinstance(self.parents, tuple) or len(self.parents) > MAX_PARENTS:
            raise ValueError("bounded immutable provenance required")
        if len(set(self.parents)) != len(self.parents):
            raise ValueError("duplicate provenance reference")
        for parent in self.parents:
            token(parent)
        if self.event_id in self.parents:
            raise ValueError("event cannot reference itself")


@dataclass(frozen=True)
class StoredEvent:
    event: Event
    ingest_seq: int


@dataclass(frozen=True)
class CorrelationReceipt:
    correlation_id: str
    partition: str
    entity_key: str
    event_ids: tuple[str, ...]
    started_at: datetime
    ended_at: datetime
    authorized: bool = False
    external_actions: int = 0
    version: str = "1"


class BoundedEventMemory:
    """Deterministic bounded memory; no persistence, network, or external execution."""

    def __init__(
        self,
        *,
        max_events_per_partition: int = 512,
        max_partitions: int = 64,
        max_age_seconds: float = 3600.0,
        max_query_window_seconds: float = 600.0,
    ) -> None:
        if isinstance(max_events_per_partition, bool) or not isinstance(max_events_per_partition, int):
            raise ValueError("max_events_per_partition must be an integer")
        if not 1 <= max_events_per_partition <= MAX_EVENTS_LIMIT:
            raise ValueError("max_events_per_partition out of range")
        if isinstance(max_partitions, bool) or not isinstance(max_partitions, int):
            raise ValueError("max_partitions must be an integer")
        if not 1 <= max_partitions <= MAX_PARTITIONS_LIMIT:
            raise ValueError("max_partitions out of range")
        max_age = _positive_bound(
            max_age_seconds, name="max_age_seconds", maximum=MAX_AGE_LIMIT_SECONDS
        )
        max_query = _positive_bound(
            max_query_window_seconds,
            name="max_query_window_seconds",
            maximum=MAX_AGE_LIMIT_SECONDS,
        )
        if max_query > max_age:
            raise ValueError("query window cannot exceed retention age")
        self.max_events_per_partition = max_events_per_partition
        self.max_partitions = max_partitions
        self.max_age_seconds = max_age
        self.max_query_window_seconds = max_query
        self._events: dict[str, dict[str, StoredEvent]] = {}
        self._watermarks: dict[str, datetime] = {}
        self._next_seq = 1

    @staticmethod
    def _sort_key(entry: StoredEvent) -> tuple[datetime, int, str]:
        return (utc(entry.event.event_at), entry.ingest_seq, entry.event.event_id)

    @staticmethod
    def _dependent_closure(
        events: dict[str, StoredEvent], roots: set[str]
    ) -> set[str]:
        doomed = set(roots)
        changed = True
        while changed:
            changed = False
            for event_id, entry in events.items():
                if event_id not in doomed and any(
                    parent in doomed for parent in entry.event.parents
                ):
                    doomed.add(event_id)
                    changed = True
        return doomed

    def _prospective_watermark(self, event: Event) -> datetime:
        event_time = utc(event.event_at)
        current = self._watermarks.get(event.partition)
        return event_time if current is None or event_time > current else current

    def append(self, event: Event) -> StoredEvent:
        if not isinstance(event, Event):
            raise ValueError("Event instance required")
        known_partition = event.partition in self._events
        if not known_partition and len(self._events) >= self.max_partitions:
            raise ValueError("partition capacity exhausted")
        partition = self._events.get(event.partition, {})
        existing = partition.get(event.event_id)
        if existing is not None:
            if existing.event == event:
                return existing
            raise MemoryConflict("event_id already exists with different content")

        watermark = self._prospective_watermark(event)
        cutoff = watermark - timedelta(seconds=self.max_age_seconds)
        event_time = utc(event.event_at)
        if event_time < cutoff:
            raise ValueError("event falls outside retention window")

        expired = {
            event_id
            for event_id, entry in partition.items()
            if utc(entry.event.event_at) < cutoff
        }
        doomed = self._dependent_closure(partition, expired) if expired else set()

        for parent in event.parents:
            parent_entry = partition.get(parent)
            if parent_entry is None or parent in doomed:
                raise MissingReference("provenance reference is not resident")

        if len(partition) - len(doomed) >= self.max_events_per_partition:
            survivors = [
                entry for event_id, entry in partition.items() if event_id not in doomed
            ]
            oldest = min(survivors, key=self._sort_key)
            if event_time < utc(oldest.event.event_at):
                raise ValueError("late event would fall outside count bound")
            count_doomed = self._dependent_closure(
                partition, {oldest.event.event_id}
            )
            if any(parent in count_doomed for parent in event.parents):
                raise MissingReference("provenance would be evicted by count bound")

        stored = StoredEvent(event=event, ingest_seq=self._next_seq)
        self._next_seq += 1
        target = self._events.setdefault(event.partition, {})
        target[event.event_id] = stored
        self._watermarks[event.partition] = watermark
        self._evict(event.partition)
        return stored

    def _drop_with_dependents(self, partition: str, roots: set[str]) -> None:
        events = self._events.get(partition)
        if not events or not roots:
            return
        doomed = self._dependent_closure(events, roots)
        for event_id in doomed:
            events.pop(event_id, None)

    def _evict(self, partition: str) -> None:
        events = self._events.get(partition)
        if not events:
            return
        watermark = self._watermarks[partition]
        cutoff = watermark - timedelta(seconds=self.max_age_seconds)
        expired = {
            event_id
            for event_id, entry in events.items()
            if utc(entry.event.event_at) < cutoff
        }
        self._drop_with_dependents(partition, expired)
        events = self._events[partition]
        while len(events) > self.max_events_per_partition:
            oldest = min(events.values(), key=self._sort_key)
            self._drop_with_dependents(partition, {oldest.event.event_id})

    def get(self, partition: str, event_id: str) -> StoredEvent:
        token(partition)
        token(event_id)
        entry = self._events.get(partition, {}).get(event_id)
        if entry is None:
            raise MissingReference("event is not resident in partition")
        return entry

    def query(
        self,
        *,
        partition: str,
        start: datetime,
        end: datetime,
        entity_key: str | None = None,
        event_type: str | None = None,
        limit: int = 128,
    ) -> tuple[StoredEvent, ...]:
        token(partition)
        start_utc = utc(start)
        end_utc = utc(end)
        if end_utc < start_utc:
            raise ValueError("query end precedes start")
        if (end_utc - start_utc).total_seconds() > self.max_query_window_seconds:
            raise ValueError("query window exceeds configured bound")
        if entity_key is not None:
            token(entity_key)
        if event_type is not None:
            token(event_type)
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= self.max_events_per_partition
        ):
            raise ValueError("query limit out of range")

        rows = []
        for entry in self._events.get(partition, {}).values():
            event = entry.event
            event_time = utc(event.event_at)
            if not start_utc <= event_time <= end_utc:
                continue
            if entity_key is not None and event.entity_key != entity_key:
                continue
            if event_type is not None and event.event_type != event_type:
                continue
            rows.append(entry)
        rows.sort(key=self._sort_key)
        return tuple(rows[:limit])

    def correlate(
        self,
        *,
        partition: str,
        event_ids: tuple[str, ...],
        window_seconds: float,
    ) -> CorrelationReceipt:
        token(partition)
        if (
            not isinstance(event_ids, tuple)
            or not 2 <= len(event_ids) <= MAX_CORRELATION_EVENTS
            or len(set(event_ids)) != len(event_ids)
        ):
            raise ValueError("bounded unique event_ids tuple required")
        for event_id in event_ids:
            token(event_id)
        window = _positive_bound(
            window_seconds,
            name="window_seconds",
            maximum=self.max_query_window_seconds,
        )
        entries = [self.get(partition, event_id) for event_id in event_ids]
        entities = {entry.event.entity_key for entry in entries}
        if len(entities) != 1:
            raise ValueError("opaque grouping key mismatch")
        ordered = sorted(entries, key=self._sort_key)
        started = utc(ordered[0].event.event_at)
        ended = utc(ordered[-1].event.event_at)
        if (ended - started).total_seconds() > window:
            raise ValueError("events exceed correlation window")
        ordered_ids = tuple(entry.event.event_id for entry in ordered)
        entity_key = ordered[0].event.entity_key
        digest_input = "\n".join(("1", partition, entity_key, *ordered_ids))
        correlation_id = "corr_" + sha256(digest_input.encode("utf-8")).hexdigest()[:32]
        return CorrelationReceipt(
            correlation_id=correlation_id,
            partition=partition,
            entity_key=entity_key,
            event_ids=ordered_ids,
            started_at=started,
            ended_at=ended,
        )

    def resident_count(self, partition: str | None = None) -> int:
        if partition is None:
            return sum(len(events) for events in self._events.values())
        token(partition)
        return len(self._events.get(partition, {}))

    def partition_count(self) -> int:
        return len(self._events)

    def snapshot_signature(self, partition: str) -> tuple[tuple[int, str], ...]:
        token(partition)
        rows = sorted(self._events.get(partition, {}).values(), key=self._sort_key)
        return tuple((entry.ingest_seq, entry.event.event_id) for entry in rows)
