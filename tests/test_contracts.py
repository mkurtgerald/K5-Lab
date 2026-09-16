from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
import unittest
from mosaic_lab.contracts import Record, Proposal, token, unit_score, utc

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

def record(**kw):
    values = dict(partition="p1",record_id="r1",source_id="s1",observed_at=NOW,score=.9)
    values.update(kw)
    return Record(**values)

class Contracts(unittest.TestCase):
    def test_record(self):
        self.assertEqual(record().kind,"observed")
    def test_opaque_tokens(self):
        for value in ("", "a b", "../x", "a/b", "a"*65, None):
            with self.subTest(value=value), self.assertRaises(ValueError): token(value)
    def test_scores(self):
        for value in (math.nan, math.inf, -math.inf, -.1, 1.1, True, "0.5"):
            with self.subTest(value=value), self.assertRaises(ValueError): unit_score(value)
    def test_score_bounds(self):
        self.assertEqual(unit_score(0),0)
        self.assertEqual(unit_score(1),1)
    def test_naive_time(self):
        with self.assertRaises(ValueError): record(observed_at=datetime(2026,1,1))
    def test_offset_normalization(self):
        self.assertEqual(utc(NOW.astimezone(timezone(timedelta(hours=2)))),NOW)
    def test_unknown_version(self):
        with self.assertRaises(ValueError): record(version="2")
    def test_unknown_kind(self):
        with self.assertRaises(ValueError): record(kind="other")
    def test_inference_needs_provenance(self):
        with self.assertRaises(ValueError): record(kind="inferred")
    def test_valid_inference(self):
        self.assertEqual(record(record_id="r2",kind="inferred",parents=("r1",)).parents,("r1",))
    def test_observation_no_inference_parents(self):
        with self.assertRaises(ValueError): record(parents=("r2",))
    def test_immutable_parents(self):
        with self.assertRaises(ValueError): record(kind="inferred",parents=["r2"])
    def test_duplicate_parents(self):
        with self.assertRaises(ValueError): record(kind="inferred",parents=("r2","r2"))
    def test_self_reference(self):
        with self.assertRaises(ValueError): record(kind="inferred",parents=("r1",))
    def test_bounded_parents(self):
        with self.assertRaises(ValueError): record(kind="inferred",parents=tuple(f"x{i}" for i in range(33)))
    def test_no_live_mode(self):
        with self.assertRaises(ValueError): Proposal("p1","p","r1","noop",.9,NOW,mode="live")
    def test_shadow_default(self):
        self.assertEqual(Proposal("p1","p","r1","noop",.9,NOW).mode,"shadow")
    def test_extra_fields_rejected(self):
        with self.assertRaises(TypeError): Record(**dict(record().__dict__, unknown=1))
