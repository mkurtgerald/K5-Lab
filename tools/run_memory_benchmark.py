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

from mosaic_lab.memory import BoundedEventMemory, Event


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        raise ValueError("values required")
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def run(samples: int) -> dict[str, object]:
    if not 32 <= samples <= 2000:
        raise ValueError("samples must be between 32 and 2000")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    memory = BoundedEventMemory(
        max_events_per_partition=samples,
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
    if memory.resident_count("partition_a") > samples:
        raise RuntimeError("memory exceeded configured count bound")

    return {
        "samples": samples,
        "resident_count": memory.resident_count("partition_a"),
        "query_count": query_count,
        "insert_p50_ms": round(percentile(insert_ms, 0.50), 6),
        "insert_p95_ms": round(percentile(insert_ms, 0.95), 6),
        "query_p50_ms": round(percentile(query_ms, 0.50), 6),
        "query_p95_ms": round(percentile(query_ms, 0.95), 6),
        "correlate_p50_ms": round(percentile(correlate_ms, 0.50), 6),
        "correlate_p95_ms": round(percentile(correlate_ms, 0.95), 6),
        "python_peak_kib": round(peak_bytes / 1024.0, 3),
        "authorized": False,
        "external_actions": 0,
        "correlation_id": receipt.correlation_id,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=512)
    args = parser.parse_args()
    print(json.dumps(run(args.samples), sort_keys=True, separators=(",", ":")))
