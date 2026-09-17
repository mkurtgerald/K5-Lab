from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from tools.check_release_licenses import parse_pins, validate_documents, validate_repository

ROOT = Path(__file__).resolve().parents[1]


class ReleaseLicenseTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "provenance/release-manifest.json").read_text())
        self.review = json.loads((ROOT / "provenance/license-review.json").read_text())
        self.pins = parse_pins((ROOT / "requirements-core.txt").read_text())

    def errors(self, *, manifest=None, review=None):
        return validate_documents(
            release_manifest=deepcopy(manifest or self.manifest),
            license_review=deepcopy(review or self.review),
            core_pins=self.pins,
        )

    def test_repository_review_is_consistent(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_cli_runs_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, "tools/check_release_licenses.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_unknown_license_fails_closed(self):
        review = deepcopy(self.review)
        review["components"][0]["license_expression"] = "UNKNOWN"
        self.assertTrue(any("forbidden/unreviewed" in error for error in self.errors(review=review)))

    def test_gpl_license_fails_closed(self):
        review = deepcopy(self.review)
        review["components"][0]["license_expression"] = "GPL-3.0-only"
        self.assertTrue(any("forbidden/unreviewed" in error for error in self.errors(review=review)))

    def test_agpl_license_fails_closed(self):
        review = deepcopy(self.review)
        review["components"][0]["license_expression"] = "AGPL-3.0-only"
        self.assertTrue(any("forbidden/unreviewed" in error for error in self.errors(review=review)))

    def test_missing_core_component_fails(self):
        review = deepcopy(self.review)
        review["components"].pop()
        self.assertTrue(any("missing core components" in error for error in self.errors(review=review)))

    def test_duplicate_component_fails(self):
        review = deepcopy(self.review)
        review["components"].append(deepcopy(review["components"][0]))
        self.assertTrue(any("duplicate license-review component" in error for error in self.errors(review=review)))

    def test_unreviewed_project_terms_fail(self):
        review = deepcopy(self.review)
        review["components"][0]["project_terms_reviewed"] = False
        self.assertTrue(any("project terms must be reviewed" in error for error in self.errors(review=review)))

    def test_distribution_attempt_fails_with_pending_notices_and_approvals(self):
        manifest = deepcopy(self.manifest)
        manifest["commercial_distribution"] = True
        errors = self.errors(manifest=manifest)
        self.assertTrue(any("owner license approval" in error for error in errors))
        self.assertTrue(any("legal review approval" in error for error in errors))
        self.assertTrue(any("pending bundle/notices" in error for error in errors))

    def test_optional_runtime_cannot_be_promoted_by_license_manifest(self):
        review = deepcopy(self.review)
        review["optional_non_shipping_scopes"][0]["shipping_candidate"] = True
        self.assertTrue(any("shipping_candidate=false" in error for error in self.errors(review=review)))


if __name__ == "__main__":
    unittest.main()
