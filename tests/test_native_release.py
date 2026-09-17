from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import unittest

from tools.check_native_release import validate_documents, validate_repository

ROOT = Path(__file__).resolve().parents[1]


class NativeReleaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "provenance/release-manifest.json").read_text(encoding="utf-8"))
        self.sbom = json.loads((ROOT / "provenance/sbom.json").read_text(encoding="utf-8"))

    def errors(self, *, manifest=None, sbom=None):
        return validate_documents(
            release_manifest=deepcopy(manifest or self.manifest),
            sbom=deepcopy(sbom or self.sbom),
        )

    def test_repository_native_boundary_is_consistent(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_cli_runs_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, "tools/check_native_release.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_distribution_attempt_with_pending_native_review_fails_closed(self):
        manifest = deepcopy(self.manifest)
        manifest["commercial_distribution"] = True
        manifest["owner_release_approved"] = True
        sbom = deepcopy(self.sbom)
        sbom["release_flags"]["commercial_distribution"] = True
        sbom["release_flags"]["owner_release_approved"] = True
        errors = self.errors(manifest=manifest, sbom=sbom)
        self.assertTrue(any("unresolved native review" in error for error in errors))

    def test_unreviewed_component_cannot_be_distribution_approved(self):
        sbom = deepcopy(self.sbom)
        sbom["scopes"]["core"]["components"][0]["distribution_approved"] = True
        self.assertTrue(any("completed native review" in error for error in self.errors(sbom=sbom)))

    def test_optional_runtime_cannot_be_distribution_approved(self):
        sbom = deepcopy(self.sbom)
        torch = sbom["scopes"]["learned_policy_torch"]["components"][0]
        torch["distribution_approved"] = True
        self.assertTrue(any("optional/non-shipping" in error for error in self.errors(sbom=sbom)))

    def test_reviewed_native_requires_exact_artifact_digest(self):
        sbom = deepcopy(self.sbom)
        row = sbom["scopes"]["core"]["components"][0]
        row["native_status"] = "reviewed-native"
        row.pop("artifact_sha256", None)
        self.assertTrue(any("requires exact artifact_sha256" in error for error in self.errors(sbom=sbom)))

    def test_unknown_native_status_fails_closed(self):
        sbom = deepcopy(self.sbom)
        sbom["scopes"]["core"]["components"][0]["native_status"] = "probably-fine"
        self.assertTrue(any("invalid native_status" in error for error in self.errors(sbom=sbom)))


if __name__ == "__main__":
    unittest.main()
