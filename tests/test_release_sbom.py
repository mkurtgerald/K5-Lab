from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import unittest

from tools.check_release_provenance import parse_pins
from tools.check_release_sbom import build_sbom, canonical_text, validate_repository, validate_sbom_text

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSbomTests(unittest.TestCase):
    def test_repository_sbom_matches_authoritative_inputs(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_checker_cli_runs_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_release_sbom.py")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def _document(self):
        manifest = json.loads((ROOT / "provenance/release-manifest.json").read_text(encoding="utf-8"))
        components = json.loads((ROOT / "provenance/components.json").read_text(encoding="utf-8"))
        s3_review = json.loads((ROOT / "provenance/s3-rl-review.json").read_text(encoding="utf-8"))
        core = parse_pins((ROOT / "requirements-core.txt").read_text(encoding="utf-8"), source="core")
        runtime = parse_pins(
            (ROOT / "requirements-s3-runtime.txt").read_text(encoding="utf-8"),
            source="runtime",
        )
        neural = parse_pins(
            (ROOT / "requirements-neural.txt").read_text(encoding="utf-8"),
            source="neural",
        )
        return build_sbom(
            manifest=manifest,
            core_pins=core,
            runtime_pins=runtime,
            neural_pins=neural,
            components=components,
            s3_review=s3_review,
        )

    def _core_component(self, name):
        return next(
            row
            for row in self._document()["scopes"]["core"]["components"]
            if row["name"] == name
        )

    def test_sbom_is_deterministic(self):
        document = self._document()
        self.assertEqual(canonical_text(document), canonical_text(deepcopy(document)))

    def test_stale_component_version_is_rejected(self):
        document = self._document()
        stale = deepcopy(document)
        stale["scopes"]["core"]["components"][0]["runtime_version"] = "0.0.0"
        self.assertTrue(validate_sbom_text(document, canonical_text(stale)))

    def test_non_shipping_candidates_are_not_selected(self):
        document = self._document()
        self.assertTrue(document["non_shipping_candidates"])
        self.assertTrue(all(row["selected"] is False for row in document["non_shipping_candidates"]))
        self.assertTrue(
            all(row["distribution_approved"] is False for row in document["non_shipping_candidates"])
        )

    def test_torch_records_evaluated_runtime_without_granting_distribution(self):
        document = self._document()
        torch = next(
            row
            for row in document["scopes"]["learned_policy_torch"]["components"]
            if row["name"] == "torch"
        )
        self.assertEqual(torch["runtime_version"], "2.14.0+cpu")
        self.assertEqual(torch["native_status"], "confirmed-native")
        self.assertFalse(torch["distribution_approved"])
        self.assertIn("artifact_sha256", torch)

    def test_s1_allocation_artifact_evidence_is_carried_into_sbom(self):
        ortools = self._core_component("ortools")
        self.assertEqual(
            ortools["artifact_sha256"],
            "ebd5aea00374e3aad7a78de59058aca5e871a26a3c385cd0860ef1d685d03c9a",
        )
        self.assertEqual(ortools["license_expression"], "Apache-2.0")
        self.assertEqual(ortools["native_status"], "review-required")
        self.assertFalse(ortools["distribution_approved"])

    def test_s2_streaming_artifact_evidence_is_carried_into_sbom(self):
        narwhals = self._core_component("narwhals")
        self.assertEqual(
            narwhals["artifact_sha256"],
            "29326d74f107c347fd1009bd58e38d9f7c7c5b51e6de97bc93dbc325d9038b54",
        )
        self.assertEqual(narwhals["license_expression"], "MIT")
        self.assertFalse(narwhals["distribution_approved"])

    def test_release_flags_remain_false(self):
        document = self._document()
        self.assertEqual(
            document["release_flags"],
            {
                "commercial_distribution": False,
                "production_qualified": False,
                "owner_release_approved": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
