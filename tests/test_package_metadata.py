from copy import deepcopy
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.check_package_metadata import load_repository, validate_documents, validate_repository

ROOT = Path(__file__).resolve().parents[1]


class PackageMetadataTests(unittest.TestCase):
    def setUp(self):
        self.pyproject, self.manifest, self.build_tools, self.core = load_repository(ROOT)

    def errors(self, *, pyproject=None, manifest=None, build_tools=None):
        return validate_documents(
            pyproject=deepcopy(pyproject or self.pyproject),
            manifest=deepcopy(manifest or self.manifest),
            build_tools=deepcopy(build_tools or self.build_tools),
            core_pins=self.core,
        )

    def test_repository_is_consistent(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_missing_runtime_pin_fails(self):
        document = deepcopy(self.pyproject)
        document["project"]["dependencies"].pop()
        self.assertTrue(any("missing core runtime pins" in error for error in self.errors(pyproject=document)))

    def test_loose_runtime_pin_fails(self):
        document = deepcopy(self.pyproject)
        document["project"]["dependencies"][0] = "numpy>=2"
        self.assertTrue(any("expected exact == pin" in error for error in self.errors(pyproject=document)))

    def test_stale_runtime_pin_fails(self):
        document = deepcopy(self.pyproject)
        document["project"]["dependencies"][0] = "numpy==0.0.0"
        self.assertTrue(any("stale core runtime versions" in error for error in self.errors(pyproject=document)))

    def test_unpinned_builder_fails(self):
        document = deepcopy(self.pyproject)
        document["build-system"]["requires"] = ["setuptools>=77"]
        self.assertTrue(any("exactly pin" in error for error in self.errors(pyproject=document)))

    def test_package_version_drift_fails(self):
        document = deepcopy(self.pyproject)
        document["project"]["version"] = "0.2.0"
        self.assertTrue(any("package version" in error for error in self.errors(pyproject=document)))

    def test_build_tool_cannot_ship(self):
        document = deepcopy(self.build_tools)
        document["tools"][0]["shipping_candidate"] = True
        self.assertTrue(any("non-shipping" in error for error in self.errors(build_tools=document)))

    def test_build_tool_hash_required(self):
        document = deepcopy(self.build_tools)
        document["tools"][0]["artifact_sha256"] = "bad"
        self.assertTrue(any("exact sha256" in error for error in self.errors(build_tools=document)))

    def _minimal_root(self, *, manifest_text=None):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "provenance").mkdir()
        shutil.copy(ROOT / "pyproject.toml", root / "pyproject.toml")
        shutil.copy(ROOT / "requirements-core.txt", root / "requirements-core.txt")
        shutil.copy(ROOT / "provenance/build-tools.json", root / "provenance/build-tools.json")
        if manifest_text is not None:
            (root / "provenance/release-manifest.json").write_text(manifest_text, encoding="utf-8")
        return temp, root

    def test_missing_release_manifest_fails_closed(self):
        temp, root = self._minimal_root()
        with temp:
            self.assertTrue(any("inputs unavailable or invalid" in error for error in validate_repository(root)))

    def test_corrupt_release_manifest_fails_closed(self):
        temp, root = self._minimal_root(manifest_text="{bad")
        with temp:
            self.assertTrue(any("inputs unavailable or invalid" in error for error in validate_repository(root)))


if __name__ == "__main__":
    unittest.main()
