from dataclasses import replace
from datetime import timedelta
import math
import unittest
from mosaic_lab.contracts import Proposal
from mosaic_lab.graph import RecordGraph
from mosaic_lab.guard import ProposalGate, Verdict, audit_digest
from test_contracts import NOW, record

class GraphTests(unittest.TestCase):
    def setUp(self): self.g = RecordGraph("p1",capacity=3)
    def test_add_replay(self):
        self.assertTrue(self.g.add(record()))
        self.assertFalse(self.g.add(record()))
        self.assertEqual(len(self.g),1)
    def test_conflicting_replay(self):
        self.g.add(record())
        with self.assertRaises(ValueError): self.g.add(record(score=.5))
    def test_partition_isolation(self):
        with self.assertRaises(ValueError): self.g.add(record(partition="p2"))
        self.assertEqual(len(self.g),0)
    def test_unresolved_provenance(self):
        with self.assertRaises(ValueError): self.g.add(record(record_id="r2",kind="inferred",parents=("r1",)))
    def test_time_order(self):
        self.g.add(record(observed_at=NOW+timedelta(seconds=1)))
        with self.assertRaises(ValueError): self.g.add(record(record_id="r2",kind="inferred",parents=("r1",)))
    def test_provenance_triples(self):
        self.g.add(record())
        self.g.add(record(record_id="r2",kind="inferred",parents=("r1",)))
        self.assertEqual(len(self.g.triples()),11)
    def test_capacity(self):
        g=RecordGraph("p1",capacity=1);g.add(record())
        with self.assertRaises(ValueError): g.add(record(record_id="r2"))
    def test_invalid_capacity(self):
        for c in (0,-1,True,1.2):
            with self.subTest(capacity=c),self.assertRaises(ValueError): RecordGraph("p1",capacity=c)
    def test_distinct_partition_uris(self):
        g2=RecordGraph("p2");self.g.add(record());g2.add(record(partition="p2"))
        self.assertFalse({t[0] for t in self.g.triples()} & {t[0] for t in g2.triples()})

class GateTests(unittest.TestCase):
    def setUp(self):
        self.g=RecordGraph("p1"); self.g.add(record())
        self.gate=ProposalGate(self.g)
        self.p=Proposal("p1","proposal1","r1","recommend",.9,NOW)
    def assess(self,p=None,now=NOW): return self.gate.assess(p or self.p,now=now)
    def test_never_executes(self):
        v=self.assess();self.assertEqual(v.status,"recommendation");self.assertFalse(v.execute)
        self.assertFalse(v.authorized);self.assertEqual(v.external_actions,0)
    def test_simulate_no_executor(self):
        self.assertFalse(self.assess(replace(self.p,mode="simulate")).execute)
    def test_partition(self): self.assertEqual(self.assess(replace(self.p,partition="p2")).status,"denied")
    def test_unknown_operation(self): self.assertEqual(self.assess(replace(self.p,operation="delete")).status,"denied")
    def test_missing_record(self): self.assertEqual(self.assess(replace(self.p,record_id="r2")).reason,"missing_record")
    def test_future(self): self.assertEqual(self.assess(now=NOW-timedelta(seconds=1)).reason,"future_timestamp")
    def test_stale(self): self.assertEqual(self.assess(now=NOW+timedelta(seconds=31)).reason,"stale_input")
    def test_low_proposal_score(self): self.assertEqual(self.assess(replace(self.p,score=.2)).status,"abstain")
    def test_low_observation_score(self):
        g=RecordGraph("p1");g.add(record(score=.2))
        self.assertEqual(ProposalGate(g).assess(self.p,now=NOW).status,"abstain")
    def test_proposal_before_observation(self):
        self.assertEqual(self.assess(replace(self.p,created_at=NOW-timedelta(seconds=1))).reason,"proposal_precedes_record")
    def test_freshness_bound(self): self.assertEqual(self.assess(now=NOW+timedelta(seconds=30)).status,"recommendation")
    def test_bad_gate_settings(self):
        for value in (0,-1,math.nan,math.inf,True,"1"):
            with self.subTest(value=value),self.assertRaises(ValueError): ProposalGate(self.g,max_age_seconds=value)
    def test_verdict_direct_reconstruction_fails_closed(self):
        verdict=self.assess()
        for changes in (
            {"execute":True},
            {"authorized":True},
            {"external_actions":1},
            {"version":"2"},
            {"status":"unknown"},
            {"status":"abstain"},
            {"reason":"missing_record"},
            {"proposal_id":"bad id"},
        ):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(verdict,**changes)
        safe=replace(verdict,status="abstain",reason="insufficient_score")
        self.assertFalse(safe.execute);self.assertFalse(safe.authorized);self.assertEqual(safe.external_actions,0)
    def test_digest(self):
        v=self.assess();a=audit_digest(v)
        self.assertEqual(a,audit_digest(v));self.assertNotEqual(a,audit_digest(v,a))
        changed=replace(v,status="abstain",reason="insufficient_score")
        self.assertNotEqual(a,audit_digest(changed))
    def test_digest_validation(self):
        with self.assertRaises(ValueError): audit_digest(self.assess(),"bad")
