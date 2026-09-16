from pathlib import Path
import argparse
from datetime import datetime, timedelta, timezone
import json
from math import ceil
import sys
import tracemalloc
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mosaic_lab.memory import BoundedEventMemory, Event, MissingReference


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("values required")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def _populate(samples: int) -> tuple[BoundedEventMemory, list[float], float]:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    memory = BoundedEventMemory(
        max_events_per_partition=samples,
        max_partitions=1,
        max_age_seconds=float(samples + 120),
        max_query_window_seconds=120.0,
    )
    insert_ms: list[float] = []
    tracemalloc.start()
    for index in range(samples):
        stamp = base + timedelta(seconds=index)
        item = Event(
            partition="partition_a",
            event_id=f"ev_{index}",
            entity_key=f"entity_{index % 4}",
            event_type=f"type_{index % 3}",
            source_ref="source_a",
            event_at=stamp,
            observed_at=stamp + timedelta(milliseconds=5),
            confidence=0.75,
            abstained=False,
        )
        started = perf_counter()
        memory.append(item)
        insert_ms.append((perf_counter() - started) * 1000.0)
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return memory, insert_ms, peak_bytes / 1024.0


def _ops_per_second(values: list[float]) -> float:
    seconds = sum(values) / 1000.0
    return round(len(values) / seconds, 3) if seconds > 0 else 0.0


def run(samples: int) -> dict[str, object]:
    if not 32 <= samples <= 2000:
        raise ValueError("samples must be between 32 and 2000")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    memory, insert_ms, peak_kib = _populate(samples)

    end = base + timedelta(seconds=samples - 1)
    start = end - timedelta(seconds=60)
    query_ms: list[float] = []
    query_count = 0
    for _ in range(50):
        started = perf_counter()
        rows = memory.query(
            partition="partition_a",
            start=start,
            end=end,
            entity_key="entity_0",
            limit=min(128, samples),
        )
        query_ms.append((perf_counter() - started) * 1000.0)
        query_count = len(rows)

    event_ids = (f"ev_{samples - 8}", f"ev_{samples - 4}")
    correlate_ms: list[float] = []
    receipt = None
    for _ in range(50):
        started = perf_counter()
        receipt = memory.correlate(
            partition="partition_a",
            event_ids=event_ids,
            window_seconds=10.0,
        )
        correlate_ms.append((perf_counter() - started) * 1000.0)

    assert receipt is not None
    if receipt.authorized or receipt.external_actions:
        raise RuntimeError("correlation receipt violated non-authorizing contract")
    if memory.resident_count("partition_a") > samples or memory.resident_count() > samples:
        raise RuntimeError("memory exceeded configured count bound")

    scaling = []
    for bound in sorted({max(32, samples // 4), max(32, samples // 2), samples}):
        scaled, _, scaled_peak_kib = _populate(bound)
        scaling.append(
            {
                "configured_max_events": bound,
                "resident_count": scaled.resident_count(),
                "python_peak_kib": round(scaled_peak_kib, 3),
            }
        )

    overflow = BoundedEventMemory(
        max_events_per_partition=32,
        max_partitions=1,
        max_age_seconds=1000,
        max_query_window_seconds=120,
    )
    for index in range(64):
        stamp = base + timedelta(seconds=index)
        overflow.append(
            Event(
                "partition_b",
                f"ov_{index}",
                "entity_a",
                "type_a",
                "source_a",
                stamp,
                stamp,
                0.75,
            )
        )
    eviction_ok = overflow.resident_count("partition_b") == 32
    if not eviction_ok:
        raise RuntimeError("count eviction failed to preserve bound")

    replay = []
    for _ in range(2):
        probe = BoundedEventMemory(
            max_events_per_partition=8,
            max_partitions=1,
            max_age_seconds=120,
            max_query_window_seconds=60,
        )
        for index in (2, 1, 3):
            stamp = base + timedelta(seconds=index)
            probe.append(
                Event(
                    "partition_r",
                    f"rp_{index}",
                    "entity_a",
                    "type_a",
                    "source_a",
                    stamp,
                    stamp,
                    0.75,
                )
            )
        replay.append(
            (
                probe.snapshot_signature("partition_r"),
                probe.correlate(
                    partition="partition_r",
                    event_ids=("rp_1", "rp_3"),
                    window_seconds=10,
                ).correlation_id,
            )
        )
    replay_match = replay[0] == replay[1]
    if not replay_match:
        raise RuntimeError("deterministic replay mismatch")

    expected_negative_paths = {}
    try:
        memory.get("partition_a", "missing")
    except MissingReference:
        expected_negative_paths["missing_reference"] = True
    try:
        memory.get("partition_other", "ev_0")
    except MissingReference:
        expected_negative_paths["cross_partition_reference"] = True
    try:
        memory.query(
            partition="partition_a", start=end - timedelta(seconds=121), end=end
        )
    except ValueError:
        expected_negative_paths["oversized_query_window"] = True
    try:
        memory.correlate(
            partition="partition_a",
            event_ids=("ev_0", "missing"),
            window_seconds=10,
        )
    except MissingReference:
        expected_negative_paths["correlation_missing_reference"] = True
    late_stamp = base - timedelta(seconds=1000)
    try:
        memory.append(
            Event(
                "partition_a",
                "late_probe",
                "entity_a",
                "type_a",
                "source_a",
                late_stamp,
                late_stamp,
                0.75,
            )
        )
    except ValueError:
        expected_negative_paths["too_late_event"] = True
    required = {
        "missing_reference",
        "cross_partition_reference",
        "oversized_query_window",
        "correlation_missing_reference",
        "too_late_event",
    }
    if set(expected_negative_paths) != required:
        raise RuntimeError("expected negative-path observation incomplete")

    return {
        "samples": samples,
        "configured_max_events": samples,
        "max_partitions": 1,
        "resident_count": memory.resident_count("partition_a"),
        "query_count": query_count,
        "insert_p50_ms": round(percentile(insert_ms, 0.50), 6),
        "insert_p95_ms": round(percentile(insert_ms, 0.95), 6),
        "query_p50_ms": round(percentile(query_ms, 0.50), 6),
        "query_p95_ms": round(percentile(query_ms, 0.95), 6),
        "correlate_p50_ms": round(percentile(correlate_ms, 0.50), 6),
        "correlate_p95_ms": round(percentile(correlate_ms, 0.95), 6),
        "insert_ops_per_second": _ops_per_second(insert_ms),
        "query_ops_per_second": _ops_per_second(query_ms),
        "correlate_ops_per_second": _ops_per_second(correlate_ms),
        "python_peak_kib": round(peak_kib, 3),
        "capacity_scaling": scaling,
        "eviction_bound_preserved": eviction_ok,
        "deterministic_replay": replay_match,
        "expected_negative_paths": expected_negative_paths,
        "authorized": False,
        "external_actions": 0,
        "correlation_id": receipt.correlation_id,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=512)
    args = parser.parse_args()
    print(json.dumps(run(args.samples), sort_keys=True, separators=(",", ":")))
