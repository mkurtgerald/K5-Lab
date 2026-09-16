from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest

from mosaic_lab.stream_checkpoint import (
    MAX_CHECKPOINT_BYTES,
    export_stream_checkpoint,
    restore_stream_checkpoint,
)
from mosaic_lab.streaming import RiverBinaryAdapter, StreamSample

BASE = datetime(2026, 2, 1, tzinfo=timezone.utc)


def training_sample(index: int, *, label: bool | None = None) -> StreamSample:
    features = (
        ((index % 17) - 8) / 8.0,
        ((index % 11) - 5) / 5.0,
        ((index % 7) - 3) / 3.0,
    )
    if label is None:
        label = (0.9 * features[0] - 0.6 * features[1] + 0.2 * features[2]) > 0.0
    return StreamSample(
        partition="p1",
        sample_id=f"s{index}",
        source_id="src1",
        observed_at=BASE + timedelta(milliseconds=index + 1),
        features=features,
        label=label,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class StreamCheckpointTests(unittest.TestCase):
    def test_round_trip_preserves_predictions_and_continuation(self):
        left = RiverBinaryAdapter("p1", feature_count=3)
        for index in range(140):
            left.process(training_sample(index))

        encoded = export_stream_checkpoint(left)
        right = restore_stream_checkpoint(encoded, expected_partition="p1")
        self.assertEqual(left.state_receipt(), right.state_receipt())
        self.assertEqual(left.updates, right.updates)
        self.assertEqual(left.source_count, right.source_count)

        probe = training_sample(140, label=None)
        self.assertEqual(left.predict(probe), right.predict(probe))
        for index in range(140, 220):
            self.assertEqual(left.process(training_sample(index)), right.process(training_sample(index)))
        self.assertEqual(left.state_receipt(), right.state_receipt())

    def test_corruption_is_rejected_before_restore(self):
        adapter = RiverBinaryAdapter("p1", feature_count=3)
        for index in range(30):
            adapter.process(training_sample(index))
        encoded = bytearray(export_stream_checkpoint(adapter))
        encoded[len(encoded) // 2] ^= 1
        with self.assertRaises(ValueError):
            restore_stream_checkpoint(bytes(encoded), expected_partition="p1")

    def test_semantic_tamper_and_partition_crossing_are_rejected(self):
        adapter = RiverBinaryAdapter("p1", feature_count=3)
        for index in range(30):
            adapter.process(training_sample(index))
        encoded = export_stream_checkpoint(adapter)
        with self.assertRaises(ValueError):
            restore_stream_checkpoint(encoded, expected_partition="p2")

        envelope = json.loads(encoded.decode("utf-8"))
        envelope["payload"]["model_id"] = "unsupported-model"
        envelope["sha256"] = hashlib.sha256(_canonical(envelope["payload"])).hexdigest()
        with self.assertRaises(ValueError):
            restore_stream_checkpoint(_canonical(envelope), expected_partition="p1")

    def test_malformed_and_oversized_inputs_fail_closed(self):
        for encoded in (b"not-json", b"{}", b"x" * (MAX_CHECKPOINT_BYTES + 1)):
            with self.subTest(size=len(encoded)):
                with self.assertRaises(ValueError):
                    restore_stream_checkpoint(encoded)


if __name__ == "__main__":
    unittest.main()
