from pathlib import Path
import subprocess
import sys
import unittest

from tools.run_release_failsafe import run

ROOT = Path(__file__).resolve().parents[1]


class ReleaseFailSafeTests(unittest.TestCase):
    def test_release_failure_paths_preserve_safe_planners(self):
        evidence = run()
        self.assertTrue(evidence["passed"])
        self.assertFalse(evidence["authorized"])
        self.assertEqual(evidence["external_actions"], 0)
        for case in evidence["cases"].values():
            self.assertTrue(case["deterministic_available"])
            self.assertTrue(case["cp_sat_available"])
            self.assertTrue(case["non_authorizing"])

    def test_optional_learned_failures_fall_back_without_authority(self):
        evidence = run()
        for name in ("learned_runtime_absent", "learned_health_failure"):
            case = evidence["cases"][name]
            self.assertEqual(case["fallback_reason"], "predictor_error")
            self.assertEqual(case["fallback_action"], 0)
            self.assertTrue(case["fallback_non_authorizing"])

    def test_corruption_and_incompatibility_fail_closed(self):
        evidence = run()
        self.assertTrue(evidence["cases"]["corrupted_checkpoint"]["corrupted_checkpoint_rejected"])
        incompatible = evidence["cases"]["incompatible_adapter"]
        self.assertTrue(incompatible["incompatible_contract_rejected"])
        self.assertEqual(incompatible["fallback_status"], "unavailable")
        self.assertTrue(incompatible["fallback_non_authorizing"])

    def test_cli_emits_passing_non_authorizing_evidence(self):
        result = subprocess.run(
            [sys.executable, "tools/run_release_failsafe.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn('"passed":true', result.stdout)
        self.assertIn('"authorized":false', result.stdout)
        self.assertIn('"production_qualified":false', result.stdout)


if __name__ == "__main__":
    unittest.main()
