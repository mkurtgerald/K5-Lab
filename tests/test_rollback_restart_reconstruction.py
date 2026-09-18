from datetime import datetime, timedelta, timezone
from mosaic_lab.audit import AuditBuffer, AuditEvent
from mosaic_lab.rollback import RollbackCapabilityBinding, RollbackResultBinding, assess_rollback
from mosaic_lab.rollback_audit import AuditedRollbackSimulation, rollback_capability_digest
NOW=datetime(2026,9,18,7,0,tzinfo=timezone.utc); P='a'*64; S='b'*64; E='c'*64

def capability():
    return RollbackCapabilityBinding('rb1','sess1','step1','delivery1','part1','principal1',P,'policy1',S,E,NOW,NOW+timedelta(minutes=3))
def assessment(item):
    return assess_rollback(item,session_id='sess1',step_id='step1',delivery_id='delivery1',partition='part1',principal_ref='principal1',proposal_digest=P,current_policy_revision='policy1',current_state_digest=S,current_profile='delegated_simulation',terminal_status='verified_complete',terminal_effect_digest=E,now=NOW+timedelta(seconds=1))
def attempt_event(item,event_id='audit1',request_id='req1',at=None):
    at=at or NOW+timedelta(seconds=2)
    return AuditEvent(event_id,request_id,'part1','principal1','delegated_simulation','policy1','m1','t1',('rb1',),'attempted','rollback_attempted','attempted',at,evidence_digests=(rollback_capability_digest(item),))
def result(outcome='verified_rolled_back',ref='res1',ch='d',observed=None):
    return RollbackResultBinding('rb1','sess1','step1','delivery1',ref,ch*64,outcome,observed or NOW+timedelta(seconds=3))
def result_event(item,r,event_id='audit2',at=None):
    at=at or NOW+timedelta(seconds=4); om={'verified_rolled_back':'verified_complete','rollback_failed':'failed','rollback_unknown':'outcome_unknown'}[r.outcome]
    return AuditEvent(event_id,'req1','part1','principal1','delegated_simulation','policy1','m1','t1',('rb1',r.result_ref),'returned','rollback_reconciled',om,at,evidence_digests=(rollback_capability_digest(item),r.result_digest))
def do_attempt(sim,item,req='req1',eid='audit1',at=None):
    at=at or NOW+timedelta(seconds=2)
    return sim.attempt(request_id=req,now=at,current_policy_revision='policy1',current_state_digest=S,current_profile='delegated_simulation',authority_available=True,cancelled=False,capability_revoked=False,audit_event=attempt_event(item,eid,req,at))

def test_direct_reconcile_after_restart():
    item=capability(); sink=AuditBuffer(max_entries=16); first=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    assert do_attempt(first,item).mocked_rollbacks==1
    restarted=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    r=result(); got=restarted.reconcile(r,request_id='req1',now=NOW+timedelta(seconds=4),audit_event=result_event(item,r))
    assert got.status=='verified_rolled_back' and got.mocked_rollbacks==0 and len(sink.snapshot())==2

def test_terminal_and_unknown_ledger_recovered():
    item=capability(); sink=AuditBuffer(max_entries=16); first=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink,max_unknown_results=2)
    do_attempt(first,item)
    u1=result('rollback_unknown','u1','d',NOW+timedelta(seconds=3)); first.reconcile(u1,request_id='req1',now=NOW+timedelta(seconds=4),audit_event=result_event(item,u1,'au1',NOW+timedelta(seconds=4)))
    u2=result('rollback_unknown','u2','e',NOW+timedelta(seconds=5)); first.reconcile(u2,request_id='req1',now=NOW+timedelta(seconds=6),audit_event=result_event(item,u2,'au2',NOW+timedelta(seconds=6)))
    restarted=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink,max_unknown_results=2)
    u3=result('rollback_unknown','u3','f',NOW+timedelta(seconds=7)); blocked=restarted.reconcile(u3,request_id='req1',now=NOW+timedelta(seconds=8),audit_event=result_event(item,u3,'au3',NOW+timedelta(seconds=8)))
    assert blocked.reason=='rollback_result_ledger_capacity' and len(sink.snapshot())==3
    final=result('verified_rolled_back','final','9',NOW+timedelta(seconds=9)); done=restarted.reconcile(final,request_id='req1',now=NOW+timedelta(seconds=10),audit_event=result_event(item,final,'af',NOW+timedelta(seconds=10)))
    assert done.status=='verified_rolled_back' and len(sink.snapshot())==4
    again=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink,max_unknown_results=2)
    assert do_attempt(again,item,req='req1',eid='ignored',at=NOW+timedelta(seconds=11)).status=='verified_rolled_back'
    replay=again.reconcile(final,request_id='req1',now=NOW+timedelta(seconds=12),audit_event=result_event(item,final,'ignored2',NOW+timedelta(seconds=12)))
    assert replay.result_ref=='final' and len(sink.snapshot())==4

def test_conflicting_recovered_result_fails_closed():
    item=capability(); sink=AuditBuffer(max_entries=16); first=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    do_attempt(first,item); r=result(); first.reconcile(r,request_id='req1',now=NOW+timedelta(seconds=4),audit_event=result_event(item,r))
    restarted=AuditedRollbackSimulation(item,assessment=assessment(item),audit_sink=sink)
    mutated=result('rollback_failed','res1','e',NOW+timedelta(seconds=3))
    got=restarted.reconcile(mutated,request_id='req1',now=NOW+timedelta(seconds=5),audit_event=result_event(item,mutated,'x',NOW+timedelta(seconds=5)))
    assert got.reason=='rollback_result_identity_collision' and len(sink.snapshot())==2
