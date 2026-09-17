from pathlib import Path
from datetime import datetime, timedelta, timezone
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.memory import BoundedEventMemory, Event, MissingReference


def _event(partition: str, event_id: str, second: float, *, parents: tuple[str, ...] = ()) -> Event:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    stamp = base + timedelta(seconds=second)
    return Event(
        partition=partition,
        event_id=event_id,
        entity_key="entity_a",
        event_type="type_a",
        source_ref="source_a",
        event_at=stamp,
        observed_at=stamp,
        confidence=0.75,
        parents=parents,
    )


def _missing(memory: BoundedEventMemory, partition: str, event_id: str) -> bool:
    try:
        memory.get(partition, event_id)
    except MissingReference:
        return True
    return False


def run() -> dict[str, object]:
    count_memory = BoundedEventMemory(
        max_events_per_partition=32,
        max_partitions=1,
        max_age_seconds=1000,
        max_query_window_seconds=120,
    )
    max_count_seen = 0
    for index in range(320):
        count_memory.append(_event("count_p", f"count_{index}", index))
        resident = count_memory.resident_count("count_p")
        max_count_seen = max(max_count_seen, resident)
        if resident > 32:
            raise RuntimeError("count stress exceeded configured bound")
    expected_tail = tuple(f"count_{index}" for index in range(288, 320))
    actual_tail = tuple(event_id for _, event_id in count_memory.snapshot_signature("count_p"))
    if actual_tail != expected_tail:
        raise RuntimeError("count stress retained an unexpected tail")

    count_cascade = BoundedEventMemory(
        max_events_per_partition=4,
        max_partitions=1,
        max_age_seconds=1000,
        max_query_window_seconds=60,
    )
    count_cascade.append(_event("cascade_p", "parent", 0))
    count_cascade.append(_event("cascade_p", "child", 1, parents=("parent",)))
    count_cascade.append(_event("cascade_p", "keep_2", 2))
    count_cascade.append(_event("cascade_p", "keep_3", 3))
    count_cascade.append(_event("cascade_p", "trigger", 4))
    count_cascade_ok = (
        _missing(count_cascade, "cascade_p", "parent")
        and _missing(count_cascade, "cascade_p", "child")
        and count_cascade.resident_count("cascade_p") <= 4
    )
    if not count_cascade_ok:
        raise RuntimeError("count eviction failed dependent cascade")

    age_memory = BoundedEventMemory(
        max_events_per_partition=16,
        max_partitions=1,
        max_age_seconds=5,
        max_query_window_seconds=5,
    )
    age_memory.append(_event("age_p", "age_parent", 0))
    age_memory.append(_event("age_p", "age_child", 1, parents=("age_parent",)))
    age_memory.append(_event("age_p", "age_survivor", 4))
    age_memory.append(_event("age_p", "age_trigger", 6))
    age_cascade_ok = (
        _missing(age_memory, "age_p", "age_parent")
        and _missing(age_memory, "age_p", "age_child")
        and not _missing(age_memory, "age_p", "age_survivor")
        and not _missing(age_memory, "age_p", "age_trigger")
        and age_memory.resident_count("age_p") == 2
    )
    if not age_cascade_ok:
        raise RuntimeError("age eviction failed dependent cascade")

    before_late = age_memory.snapshot_signature("age_p")
    late_rejected = False
    try:
        age_memory.append(_event("age_p", "late", 0.5))
    except ValueError:
        late_rejected = True
    after_late = age_memory.snapshot_signature("age_p")
    late_state_preserved = late_rejected and before_late == after_late
    if not late_state_preserved:
        raise RuntimeError("late rejection mutated resident state")

    partitions = BoundedEventMemory(
        max_events_per_partition=4,
        max_partitions=2,
        max_age_seconds=1000,
        max_query_window_seconds=60,
    )
    partitions.append(_event("partition_b", "sentinel", 0))
    for index in range(8):
        partitions.append(_event("partition_a", f"a_{index}", index))
    partition_isolation = (
        not _missing(partitions, "partition_b", "sentinel")
        and partitions.resident_count("partition_a") == 4
        and partitions.resident_count("partition_b") == 1
        and partitions.partition_count() == 2
    )
    if not partition_isolation:
        raise RuntimeError("partition eviction leaked across boundary")

    replay_signatures = []
    for _ in range(2):
        replay = BoundedEventMemory(
            max_events_per_partition=4,
            max_partitions=1,
            max_age_seconds=1000,
            max_query_window_seconds=60,
        )
        for index in range(12):
            replay.append(_event("replay_p", f"replay_{index}", index))
        replay_signatures.append(replay.snapshot_signature("replay_p"))
    deterministic_replay = replay_signatures[0] == replay_signatures[1]
    if not deterministic_replay:
        raise RuntimeError("eviction replay diverged")

    return {
        "scope": "synthetic_memory_eviction_stress_only",
        "count_insertions": 320,
        "count_limit": 32,
        "max_count_seen": max_count_seen,
        "count_tail_exact": actual_tail == expected_tail,
        "count_cascade_ok": count_cascade_ok,
        "age_cascade_ok": age_cascade_ok,
        "late_rejected": late_rejected,
        "late_state_preserved": late_state_preserved,
        "partition_isolation": partition_isolation,
        "deterministic_replay": deterministic_replay,
        "production_qualified": False,
        "authorized": False,
        "external_actions": 0,
    }


if __name__ == "__main__":
    print(json.dumps(run(), sort_keys=True, separators=(",", ":")))
