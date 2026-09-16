from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import unittest
from tools.check_public import scan, ROOT
from tools.release_check import blockers

class PublicationTests(unittest.TestCase):
    def test_current_scaffold(self): self.assertEqual(scan(ROOT),[])
    def fixture(self):
        tmp=tempfile.TemporaryDirectory();root=Path(tmp.name)
        (root/"provenance").mkdir()
        data={"digests":[hashlib.sha256(b"reservedword").hexdigest()]}
        (root/"provenance/public-token-denylist.json").write_text(json.dumps(data))
        return tmp,root
    def test_protected_word(self):
        tmp,root=self.fixture()
        with tmp:
            (root/"README.md").write_text("reservedword")
            self.assertTrue(any("protected token" in e for e in scan(root)))
    def test_artifact_file(self):
        tmp,root=self.fixture()
        with tmp:
            (root/"weights.pt").write_text("test")
            self.assertTrue(any("protected artifact" in e for e in scan(root)))
    def test_stream_endpoint(self):
        tmp,root=self.fixture()
        with tmp:
            (root/"README.md").write_text("rt"+"sp://example.invalid")
            self.assertTrue(any("endpoint" in e for e in scan(root)))
    def test_s3_runtime_manifest_is_an_explicit_public_root_file(self):
        tmp,root=self.fixture()
        with tmp:
            (root/"requirements-s3-runtime.txt").write_text("stable-baselines3==2.9.0\n")
            self.assertEqual(scan(root), [])
    def test_unknown_root_file_remains_blocked(self):
        tmp,root=self.fixture()
        with tmp:
            (root/"requirements-unreviewed.txt").write_text("example==1.0\n")
            self.assertTrue(any("unapproved path" in e for e in scan(root)))
    def test_release_not_approved(self):
        doc=json.loads((ROOT/"provenance/components.json").read_text())
        self.assertGreater(len(blockers(doc)),0)
        self.assertFalse(doc["release_approved"])
