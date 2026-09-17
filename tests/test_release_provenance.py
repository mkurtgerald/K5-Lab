from copy import deepcopy
from pathlib import Path
import unittest

from tools.check_release_provenance import (
    parse_pins,
    validate_documents,
    validate_repository,
)

ROOT = Path(__file__).resolve().parents[1]


class ReleaseProvenanceTests(unittest.TestCase):
    def test_repository_release_provenance_is_consistent(self):
        self.assertEqual(validate_repository(ROOT), [])

    def _fixture(self):
        import json
        import tomllib

        manifest = json.loads((ROOT / "provenance/release-manifest.json").read_text(encoding="utf-8"))
        components = json.loads((ROOT / "provenance/components.json").read_text(encoding="utf-8"))
        s3_review = json.loads((ROOT / "provenance/s3-rl-review.json").read_text(encoding="utf-8"))
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        core_pins = parse_pins(
            (ROOT / "requirements-core.txt").read_text(encoding="utf-8"),
            source="requirements-core.txt",
        )
        neural_pins = parse_pins(
            (ROOT / "requirements-neural.txt").read_text(encoding="utf-8"),
            source="requirements-neural.txt",
        )
        runtime_pins = parse_pins(
            (ROOT / "requirements-s3-runtime.txt").read_text(encoding="utf-8"),
            source="requirements-s3-runtime.txt",
        )
        return manifest, pyproject, core_pins, neural_pins, runtime_pins, components, s3_review

    def _errors(self, *, mutate_components=None, mutate_manifest=None, mutate_s3=None):
        (
            manifest,
            pyproject,
            core_pins,
            neural_pins,
            runtime_pins,
            components,
            s3_review,
        ) = self._fixture()
        manifest = deepcopy(manifest)
        components = deepcopy(components)
        s3_review = deepcopy(s3_review)
        if mutate_components is not None:
            mutate_components(components)
        if mutate_manifest is not None:
            mutate_manifest(manifest)
        if mutate_s3 is not None:
            mutate_s3(s3_review)
        return validate_documents(
            manifest=manifest,
            pyproject=pyproject,
            core_pins=core_pins,
            neural_pins=neural_pins,
            runtime_pins=runtime_pins,
            components=components,
            s3_review=s3_review,
        )

    def test_stale_torch_aggregate_version_fails(self):
        def mutate(components):
            next(row for row in components["components"] if row["name"] == "torch")["version"] = "2.10.0+cpu"
        errors = self._errors(mutate_components=mutate)
        self.assertTrue(any("torch" in error and "2.10.0+cpu" in error for error in errors))

    def test_manufactured_distribution_approval_fails(self):
        def mutate(components):
            next(row for row in components["components"] if row["name"] == "River")[
                "distribution_approved"
            ] = True
        errors = self._errors(mutate_components=mutate)
        self.assertTrue(any("distribution_approved" in error for error in errors))

    def test_duplicate_component_identity_fails(self):
        def mutate(components):
            components["components"].append(deepcopy(components["components"][0]))
        errors = self._errors(mutate_components=mutate)
        self.assertTrue(any("duplicate aggregate component identity" in error for error in errors))

    def test_stale_runtime_ledger_fails(self):
        def mutate(s3_review):
            s3_review["torch"]["evaluated_runtime"] = "2.10.0+cpu"
        errors = self._errors(mutate_s3=mutate)
        self.assertTrue(any("evaluated torch runtime" in error for error in errors))

    def test_release_flags_fail_closed(self):
        def mutate(manifest):
            manifest["commercial_distribution"] = True
        errors = self._errors(mutate_manifest=mutate)
        self.assertTrue(any("commercial_distribution=false" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
