from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest

from mosaic_lab.adapter_contract import CONTRACT_VERSION
from tools.check_release_security import active_adapter_contract_path, scan_source, validate_documents, validate_repository

ROOT = Path(__file__).resolve().parents[1]


class ReleaseSecurityTests(unittest.TestCase):
    def docs(self):
        security = {
            "schema": "k5-lab.security-review/v1",
            "scope": "public-core-shipping-candidate",
            "commercial_distribution": False,
            "production_qualified": False,
            "owner_security_approval": False,
            "privacy_review_approved": False,
            "external_pen_test_complete": False,
            "runtime_policy": {
                "network_default": False,
                "persistence_default": False,
                "unsafe_deserialization": False,
                "temporary_file_runtime": False,
                "unrestricted_subprocess": False,
                "subprocess_exception": {
                    "module": "native_runtime.py",
                    "executable": "ldd",
                    "max_timeout_seconds": 5.0,
                },
            },
            "checkpoint_policy": {
                "format": "canonical-json",
                "filesystem_io": False,
                "unsafe_deserialization": False,
                "trusted_origin_required": True,
                "integrity_is_authenticity": False,
            },
            "fixture_policy": {
                "public_fixture_class": "synthetic-or-opaque",
                "real_sensor_data_allowed": False,
            },
            "publication_boundary": {
                "credential_endpoint_scan": True,
                "private_address_scan": True,
                "forbidden_artifact_scan": True,
                "non_text_and_size_scan": True,
            },
        }
        adapter = {
            "transport": {"network_required": False, "persistence_required": False},
            "privacy": {"opaque_identifiers_only": True, "synthetic_public_fixtures_only": True},
        }
        manifest = {
            "commercial_distribution": False,
            "production_qualified": False,
            "owner_release_approved": False,
        }
        return security, adapter, manifest

    def test_repository_security_boundary_is_consistent(self):
        self.assertEqual(validate_repository(ROOT), [])

    def test_repository_security_tracks_active_adapter_contract(self):
        self.assertEqual(
            active_adapter_contract_path(ROOT),
            ROOT / f"docs/contracts/adapter-v{CONTRACT_VERSION}.json",
        )
        self.assertTrue(active_adapter_contract_path(ROOT).is_file())

    def test_cli_runs_from_repository_root(self):
        result = subprocess.run(
            [sys.executable, "tools/check_release_security.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_documents_clean(self):
        security, adapter, manifest = self.docs()
        self.assertEqual(
            validate_documents(
                security=security,
                adapter_contract=adapter,
                release_manifest=manifest,
            ),
            [],
        )

    def test_network_import_fails(self):
        errors = scan_source(Path("src/mosaic_lab/x.py"), "import socket\n")
        self.assertTrue(any("forbidden runtime import" in error for error in errors))

    def test_pickle_import_fails(self):
        self.assertTrue(scan_source(Path("src/mosaic_lab/x.py"), "import pickle\n"))

    def test_path_write_fails(self):
        errors = scan_source(
            Path("src/mosaic_lab/x.py"),
            "from pathlib import Path\nPath('x').write_text('y')\n",
        )
        self.assertTrue(any("filesystem mutation" in error for error in errors))

    def test_open_write_fails(self):
        errors = scan_source(Path("src/mosaic_lab/x.py"), "open('x','wb')\n")
        self.assertTrue(any("file write mode" in error for error in errors))

    def test_path_open_write_fails(self):
        errors = scan_source(
            Path("src/mosaic_lab/x.py"),
            "from pathlib import Path\nPath('x').open('wb')\n",
        )
        self.assertTrue(any("file write mode" in error for error in errors))

    def test_dynamic_import_fails(self):
        errors = scan_source(Path("src/mosaic_lab/x.py"), "__import__('socket')\n")
        self.assertTrue(any("dynamic runtime import" in error for error in errors))

    def test_harmless_string_replace_passes(self):
        errors = scan_source(
            Path("src/mosaic_lab/x.py"),
            "value = 'a\\b'.replace('\\\\', '/')\n",
        )
        self.assertEqual(errors, [])

    def test_subprocess_outside_native_fails(self):
        errors = scan_source(
            Path("src/mosaic_lab/x.py"),
            "import subprocess\nsubprocess.run(['ldd','x'], timeout=5)\n",
        )
        self.assertTrue(errors)

    def test_bounded_ldd_exception_passes(self):
        text = (
            "import subprocess\n"
            "MAX_LDD_SECONDS=4.0\n"
            "subprocess.run(['ldd','x'], timeout=MAX_LDD_SECONDS, check=False)\n"
        )
        self.assertEqual(scan_source(Path("src/mosaic_lab/native_runtime.py"), text), [])

    def test_shell_true_fails(self):
        text = (
            "import subprocess\n"
            "MAX_LDD_SECONDS=4.0\n"
            "subprocess.run(['ldd','x'], timeout=MAX_LDD_SECONDS, shell=True)\n"
        )
        errors = scan_source(Path("src/mosaic_lab/native_runtime.py"), text)
        self.assertTrue(any("shell=True" in error for error in errors))

    def test_security_approval_tamper_fails(self):
        security, adapter, manifest = self.docs()
        security = deepcopy(security)
        security["owner_security_approval"] = True
        errors = validate_documents(
            security=security,
            adapter_contract=adapter,
            release_manifest=manifest,
        )
        self.assertTrue(any("owner_security_approval=false" in error for error in errors))

    def test_adapter_network_tamper_fails(self):
        security, adapter, manifest = self.docs()
        adapter = deepcopy(adapter)
        adapter["transport"]["network_required"] = True
        errors = validate_documents(
            security=security,
            adapter_contract=adapter,
            release_manifest=manifest,
        )
        self.assertTrue(any("no network" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
