import unittest

from tools.run_failure_paths import run


class FailurePathQualificationTests(unittest.TestCase):
    def test_cross_stage_failure_paths_are_fail_closed(self):
        report = run()
        self.assertTrue(report["passed"])
        self.assertFalse(report["production_qualified"])
        self.assertFalse(report["authorized"])
        self.assertEqual(report["external_actions"], 0)

        self.assertEqual(report["high_fan_in"]["accepted_event_count"], 32)
        self.assertTrue(report["high_fan_in"]["oversized_rejected"])
        self.assertTrue(report["provenance_eviction"]["correlation_fails_closed"])
        self.assertTrue(report["provenance_eviction"]["evidence_fails_closed"])
        self.assertEqual(report["confidence_edges"]["scores"], [0.0, 1.0])
        self.assertTrue(report["confidence_edges"]["uncalibrated"])

        for name in (
            "prohibited_fallback",
            "predictor_error_fallback",
            "invalid_output_fallback",
            "non_authorizing",
        ):
            self.assertTrue(report["policy_failures"][name])

    def test_cross_stage_failure_paths_are_deterministic(self):
        self.assertEqual(run(), run())


if __name__ == "__main__":
    unittest.main()
