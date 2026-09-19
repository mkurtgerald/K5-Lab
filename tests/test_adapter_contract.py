from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import unittest

from mosaic_lab.adapter_contract import (
    AdapterRequest,
    AdapterResponse,
    IncompatibleAdapterContract,
    fallback_response,
    negotiate_version,
    normalize_response,
)

ROOT = Path(__file__).resolve().parents[1]


class AdapterContractTests(unittest.TestCase):
    def request(self, **changes):
        values = dict(request_id="req1", partition="p1", record_id="r1", timeout_ms=250)
        values.update(changes)
        return AdapterRequest(**values)

    def response(self, **changes):
        values = dict(
            request_id="req1",
            partition="p1",
            record_id="r1",
            status="abstain",
            reason_code="low_confidence",
        )
        values.update(changes)
        return AdapterResponse(**values)

    def test_contract_file_is_canonical(self):
        result = subprocess.run(
            [sys.executable, "tools/check_adapter_contract.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_version_negotiation(self):
        self.assertEqual(negotiate_version(("2",)), "2")
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version(("1",))

    def test_version_list_is_bounded_unique_and_structured(self):
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version(())
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version(("2", "2"))
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version(tuple(str(i) for i in range(9)))
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version("2")
        with self.assertRaises(IncompatibleAdapterContract):
            negotiate_version(("bad version",))

    def test_timeout_is_bounded_integer(self):
        for value in (0, 5001, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.request(timeout_ms=value)

    def test_response_cannot_authorize(self):
        with self.assertRaises(ValueError):
            self.response(authorized=True)

    def test_recommendation_shape(self):
        response = self.response(
            status="recommendation",
            reason_code="model_candidate",
            operation="op1",
            confidence=0.9,
        )
        self.assertFalse(response.authorized)
        with self.assertRaises(ValueError):
            self.response(status="recommendation", reason_code="missing_fields")
        with self.assertRaises(ValueError):
            self.response(operation="op1", confidence=0.2)

    def test_correlation_mismatch_fails_closed(self):
        request = self.request()
        candidate = self.response(request_id="other")
        result = normalize_response(request, candidate)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason_code, "contract_mismatch")
        self.assertEqual((result.request_id, result.partition, result.record_id), ("req1", "p1", "r1"))
        self.assertFalse(result.authorized)

    def test_same_request_id_cannot_alias_partition_or_record(self):
        source_request = self.request()
        candidate = self.response()
        self.assertEqual(normalize_response(source_request, candidate), candidate)

        for target in (
            self.request(partition="p2"),
            self.request(record_id="r2"),
            self.request(partition="p2", record_id="r2"),
        ):
            with self.subTest(partition=target.partition, record_id=target.record_id):
                result = normalize_response(target, candidate)
                self.assertEqual(result.status, "error")
                self.assertEqual(result.reason_code, "contract_mismatch")
                self.assertEqual(result.request_id, target.request_id)
                self.assertEqual(result.partition, target.partition)
                self.assertEqual(result.record_id, target.record_id)
                self.assertFalse(result.authorized)

    def test_malformed_response_fails_closed(self):
        result = normalize_response(self.request(), {"status": "recommendation"})
        self.assertEqual(result.status, "error")
        self.assertEqual((result.partition, result.record_id), ("p1", "r1"))
        self.assertFalse(result.authorized)

    def test_fallback_is_non_authorizing_and_actionless(self):
        result = fallback_response(self.request())
        self.assertEqual(result.status, "unavailable")
        self.assertEqual((result.partition, result.record_id), ("p1", "r1"))
        self.assertIsNone(result.operation)
        self.assertIsNone(result.confidence)
        self.assertFalse(result.authorized)

    def test_unknown_contract_version_is_rejected(self):
        with self.assertRaises(IncompatibleAdapterContract):
            self.request(contract_version="1")
        valid = self.response()
        with self.assertRaises(IncompatibleAdapterContract):
            replace(valid, contract_version="1")


if __name__ == "__main__":
    unittest.main()
