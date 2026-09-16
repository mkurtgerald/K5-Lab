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
    def test_release_not_approved(self):
        doc=json.loads((ROOT/"provenance/components.json").read_text())
        self.assertGreater(len(blockers(doc)),0)
        self.assertFalse(doc["release_approved"])
