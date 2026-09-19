from datetime import datetime, timedelta, timezone
import unittest
from dataclasses import replace

from mosaic_lab.retrieval import EvidenceRecord, ReadScope, RetrievalCheckpoint, RetrievalSession, SyntheticEvidenceStore

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

def scope():
    return ReadScope(partition="p1", principal_ref="principal1", profile="read_only", policy_revision="policy1", allowed_record_ids=("rec1",), valid_until=NOW + timedelta(minutes=10))

def setup_session():
    record = EvidenceRecord(partition="p1", record_id="rec1", source_ref="source1", observed_at=NOW - timedelta(seconds=5), text="synthetic original")
    store = SyntheticEvidenceStore(); store.add(record)
    session = RetrievalSession(session_id="s1", partition="p1", principal_ref="principal1", policy_revision="policy1")
    receipt = session.retrieve("req1", "rec1", store, scope(), current_policy_revision="policy1", now=NOW)
    assert receipt.status == "returned"
    return session, record

class BindingTests(unittest.TestCase):
    def test_checkpoint_binds_exact_content_digest(self):
        session, record = setup_session()
        checkpoint = session.create_checkpoint(("rec1",), now=NOW)
        self.assertEqual(checkpoint.evidence_digests, (record.content_digest,))
        result = session.validate_checkpoint(checkpoint, scope(), current_policy_revision="policy1", now=NOW + timedelta(seconds=1))
        self.assertEqual((result.status, result.reason), ("accepted_for_read", "checkpoint_valid"))
        self.assertFalse(result.authorized); self.assertFalse(result.execute); self.assertEqual(result.external_actions, 0)

    def test_changed_cached_content_cannot_be_resumed_under_same_record_id(self):
        session, record = setup_session()
        checkpoint = session.create_checkpoint(("rec1",), now=NOW)
        session._cache["rec1"] = replace(record, text="synthetic changed")
        result = session.validate_checkpoint(checkpoint, scope(), current_policy_revision="policy1", now=NOW + timedelta(seconds=1))
        self.assertEqual((result.status, result.reason), ("denied", "checkpoint_evidence_changed"))
        self.assertEqual(result.evidence_refs, ())
        self.assertFalse(result.authorized); self.assertFalse(result.execute); self.assertEqual(result.external_actions, 0)

    def test_checkpoint_requires_one_valid_digest_per_ref(self):
        with self.assertRaises(ValueError):
            RetrievalCheckpoint("s1", "p1", "principal1", "policy1", ("rec1",), NOW)
        with self.assertRaises(ValueError):
            RetrievalCheckpoint("s1", "p1", "principal1", "policy1", ("rec1",), NOW, evidence_digests=("x" * 64,))

if __name__ == "__main__": unittest.main()
