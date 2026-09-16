from datetime import datetime, timedelta, timezone
import unittest

from mosaic_lab.memory import BoundedEventMemory, Event, MemoryConflict, MissingReference


BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def event(
    event_id: str,
    *,
    partition: str = "p1",
    entity: str = "entity_a",
    event_type: str = "type_a",
    offset: int = 0,
    parents: tuple[str, ...] = (),
    confidence: float = 0.8,
    abstained: bool = False,
) -> Event:
    stamp = BASE + timedelta(seconds=offset)
    return Event(
        partition=partition,
        event_id=event_id,
        entity_key=entity,
        event_type=event_type,
        source_ref="source_a",
        event_at=stamp,
        observed_at=stamp + timedelta(milliseconds=10),
        confidence=confidence,
        abstained=abstained,
        parents=parents,
    )


class MemoryTests(unittest.TestCase):
    def test_event_contract_rejects_bad_inputs(self):
        with self.assertRaises(ValueError):
            event("bad id")
        with self.assertRaises(ValueError):
            Event(
                partition="p1",
                event_id="e1",
                entity_key="entity_a",
                event_type="type_a",
                source_ref="source_a",
                event_at=datetime(2026, 1, 1),
                observed_at=BASE,
                confidence=0.5,
            )
        with self.assertRaises(ValueError):
            event("e1", confidence=float("nan"))
        with self.assertRaises(ValueError):
            event("e1", parents=("e0", "e0"))

    def test_constructor_resource_bounds(self):
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_events_per_partition=0)
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_events_per_partition=10001)
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_partitions=0)
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_partitions=1025)
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_age_seconds=float("nan"))
        with self.assertRaises(ValueError):
            BoundedEventMemory(max_age_seconds=10, max_query_window_seconds=11)

    def test_append_is_idempotent_and_conflict_fails_before_mutation(self):
        memory = BoundedEventMemory()
        first = event("e1")
        stored = memory.append(first)
        self.assertIs(memory.append(first), stored)
        with self.assertRaises(MemoryConflict):
            memory.append(event("e1", event_type="type_b"))
        self.assertEqual(memory.resident_count("p1"), 1)

    def test_partition_isolation_and_unresolved_parent(self):
        memory = BoundedEventMemory()
        memory.append(event("e1", partition="p1"))
        with self.assertRaises(MissingReference):
            memory.get("p2", "e1")
        with self.assertRaises(MissingReference):
            memory.append(event("e2", partition="p2", parents=("e1",)))
        self.assertEqual(memory.resident_count("p2"), 0)

    def test_total_partition_capacity_is_bounded(self):
        memory = BoundedEventMemory(max_partitions=2)
        memory.append(event("e1", partition="p1"))
        memory.append(event("e2", partition="p2"))
        before = (memory.partition_count(), memory.resident_count())
        with self.assertRaises(ValueError):
            memory.append(event("e3", partition="p3"))
        self.assertEqual((memory.partition_count(), memory.resident_count()), before)

    def test_out_of_order_query_is_deterministic(self):
        memory = BoundedEventMemory(max_query_window_seconds=100)
        memory.append(event("e3", offset=30))
        memory.append(event("e1", offset=10))
        memory.append(event("e2", offset=20))
        rows = memory.query(
            partition="p1", start=BASE, end=BASE + timedelta(seconds=40)
        )
        self.assertEqual([row.event.event_id for row in rows], ["e1", "e2", "e3"])
        self.assertEqual(
            memory.snapshot_signature("p1"), ((2, "e1"), (3, "e2"), (1, "e3"))
        )

    def test_time_eviction_and_too_late_event_fail_closed(self):
        memory = BoundedEventMemory(max_age_seconds=20, max_query_window_seconds=20)
        memory.append(event("e1", offset=0))
        memory.append(event("e2", offset=25))
        self.assertEqual(memory.resident_count("p1"), 1)
        with self.assertRaises(MissingReference):
            memory.get("p1", "e1")
        with self.assertRaises(ValueError):
            memory.append(event("late", offset=1))
        self.assertEqual(memory.resident_count("p1"), 1)

    def test_time_eviction_cascades_to_derived_descendants(self):
        memory = BoundedEventMemory(max_age_seconds=2, max_query_window_seconds=2)
        memory.append(event("e1", offset=0))
        memory.append(event("e2", offset=1, parents=("e1",)))
        memory.append(event("e3", offset=3))
        self.assertEqual(memory.snapshot_signature("p1"), ((3, "e3"),))
        for missing in ("e1", "e2"):
            with self.assertRaises(MissingReference):
                memory.get("p1", missing)

    def test_count_bound_and_late_capacity_rejection(self):
        memory = BoundedEventMemory(max_events_per_partition=2)
        memory.append(event("e1", offset=10))
        memory.append(event("e2", offset=20))
        with self.assertRaises(ValueError):
            memory.append(event("late", offset=5))
        memory.append(event("e3", offset=30))
        self.assertEqual(memory.resident_count("p1"), 2)
        with self.assertRaises(MissingReference):
            memory.get("p1", "e1")

    def test_count_eviction_cascades_to_derived_descendants(self):
        memory = BoundedEventMemory(max_events_per_partition=3)
        memory.append(event("e1", offset=0))
        memory.append(event("e2", offset=1, parents=("e1",)))
        memory.append(event("e3", offset=2, parents=("e2",)))
        memory.append(event("e4", offset=3))
        self.assertEqual(memory.snapshot_signature("p1"), ((4, "e4"),))

    def test_append_rejects_parent_that_count_eviction_would_remove(self):
        memory = BoundedEventMemory(max_events_per_partition=2)
        memory.append(event("e1", offset=0))
        memory.append(event("e2", offset=1))
        before = memory.snapshot_signature("p1")
        with self.assertRaises(MissingReference):
            memory.append(event("e3", offset=2, parents=("e1",)))
        self.assertEqual(memory.snapshot_signature("p1"), before)

    def test_derived_event_requires_resident_parent(self):
        memory = BoundedEventMemory()
        memory.append(event("e1"))
        memory.append(event("e2", offset=1, parents=("e1",)))
        self.assertEqual(memory.get("p1", "e2").event.parents, ("e1",))

    def test_query_bounds_and_filters(self):
        memory = BoundedEventMemory(max_query_window_seconds=30)
        memory.append(event("e1", entity="entity_a", event_type="type_a", offset=1))
        memory.append(event("e2", entity="entity_b", event_type="type_a", offset=2))
        rows = memory.query(
            partition="p1",
            start=BASE,
            end=BASE + timedelta(seconds=10),
            entity_key="entity_a",
            event_type="type_a",
        )
        self.assertEqual([row.event.event_id for row in rows], ["e1"])
        with self.assertRaises(ValueError):
            memory.query(
                partition="p1", start=BASE, end=BASE + timedelta(seconds=31)
            )

    def test_correlation_is_deterministic_and_non_authorizing(self):
        memory = BoundedEventMemory(max_query_window_seconds=60)
        memory.append(event("e1", offset=1))
        memory.append(event("e2", offset=3))
        first = memory.correlate(
            partition="p1", event_ids=("e2", "e1"), window_seconds=10
        )
        second = memory.correlate(
            partition="p1", event_ids=("e1", "e2"), window_seconds=10
        )
        self.assertEqual(first.correlation_id, second.correlation_id)
        self.assertEqual(first.event_ids, ("e1", "e2"))
        self.assertFalse(first.authorized)
        self.assertEqual(first.external_actions, 0)

    def test_correlation_fails_closed_for_mismatch_missing_and_window(self):
        memory = BoundedEventMemory(max_query_window_seconds=100)
        memory.append(event("e1", entity="entity_a", offset=0))
        memory.append(event("e2", entity="entity_b", offset=1))
        memory.append(event("e3", entity="entity_a", offset=80))
        with self.assertRaises(ValueError):
            memory.correlate(
                partition="p1", event_ids=("e1", "e2"), window_seconds=10
            )
        with self.assertRaises(MissingReference):
            memory.correlate(
                partition="p1", event_ids=("e1", "missing"), window_seconds=10
            )
        with self.assertRaises(ValueError):
            memory.correlate(
                partition="p1", event_ids=("e1", "e3"), window_seconds=10
            )

    def test_correlation_with_evicted_reference_fails_closed(self):
        memory = BoundedEventMemory(
            max_events_per_partition=2, max_query_window_seconds=20
        )
        memory.append(event("e1", offset=0))
        memory.append(event("e2", offset=1))
        memory.append(event("e3", offset=2))
        with self.assertRaises(MissingReference):
            memory.correlate(
                partition="p1", event_ids=("e1", "e2"), window_seconds=10
            )

    def test_correlation_input_is_bounded_and_unique(self):
        memory = BoundedEventMemory()
        memory.append(event("e1"))
        memory.append(event("e2", offset=1))
        with self.assertRaises(ValueError):
            memory.correlate(partition="p1", event_ids=("e1",), window_seconds=1)
        with self.assertRaises(ValueError):
            memory.correlate(
                partition="p1", event_ids=("e1", "e1"), window_seconds=1
            )

    def test_memory_never_exceeds_total_configured_bound(self):
        memory = BoundedEventMemory(max_events_per_partition=8, max_partitions=4)
        for partition_index in range(4):
            for index in range(64):
                memory.append(
                    event(
                        f"e{partition_index}_{index}",
                        partition=f"p{partition_index}",
                        offset=index,
                    )
                )
                self.assertLessEqual(
                    memory.resident_count(f"p{partition_index}"), 8
                )
                self.assertLessEqual(memory.resident_count(), 32)


if __name__ == "__main__":
    unittest.main()
