"""Bounded, non-executing delegated-simulation contracts.

The module models synthetic effect attempts only. It has no transport, executor,
network access, persistence, or external authority. Trusted state is supplied by
callers and rechecked at every mocked effect boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from math import isfinite
from threading import Lock

from .audit import AuditBuffer, AuditEvent
from .contracts import token, utc

_MAX_STEPS = 64
_MAX_DURATION_SECONDS = 300.0
_MAX_RATE_PER_MINUTE = 120
_MAX_TRACKED_DELIVERIES = 4096
_ALLOWED_OUTCOMES = frozenset({"verified_complete", "failed", "outcome_unknown"})


def _digest(value: str, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{field} must be a lowercase sha256 digest")
    return value


@dataclass(frozen=True)
class DelegationGrant:
    grant_id: str; principal_ref: str; partition: str; proposal_digest: str; policy_revision: str; state_digest: str
    allowed_actions: tuple[str, ...]; allowed_targets: tuple[str, ...]; granted_at: datetime; expires_at: datetime
    max_steps: int; max_duration_seconds: float; max_actions_per_minute: int; revoked: bool = False
    profile: str = "delegated_simulation"; version: str = "1"
    def __post_init__(self) -> None:
        if self.version != "1" or self.profile != "delegated_simulation": raise ValueError("unsupported delegation")
        for v in (self.grant_id,self.principal_ref,self.partition,self.policy_revision): token(v)
        _digest(self.proposal_digest,field="proposal_digest"); _digest(self.state_digest,field="state_digest")
        for vals,field in ((self.allowed_actions,"allowed_actions"),(self.allowed_targets,"allowed_targets")):
            if not isinstance(vals,tuple) or not vals or len(vals)>64 or len(set(vals))!=len(vals): raise ValueError(f"invalid {field}")
            for v in vals: token(v)
        if utc(self.expires_at)<=utc(self.granted_at): raise ValueError("delegation expiry must follow grant time")
        if not isinstance(self.revoked,bool): raise ValueError("revoked must be boolean")
        if isinstance(self.max_steps,bool) or not isinstance(self.max_steps,int) or not 1<=self.max_steps<=_MAX_STEPS: raise ValueError("max_steps outside bounded limit")
        if isinstance(self.max_duration_seconds,bool) or not isinstance(self.max_duration_seconds,(int,float)) or not isfinite(self.max_duration_seconds) or not 0<float(self.max_duration_seconds)<=_MAX_DURATION_SECONDS: raise ValueError("max_duration_seconds outside bounded limit")
        if isinstance(self.max_actions_per_minute,bool) or not isinstance(self.max_actions_per_minute,int) or not 1<=self.max_actions_per_minute<=_MAX_RATE_PER_MINUTE: raise ValueError("max_actions_per_minute outside bounded limit")


@dataclass(frozen=True)
class SimulationStep:
    step_id: str; delivery_id: str; action_ref: str; target_ref: str; version: str = "1"
    def __post_init__(self) -> None:
        if self.version!="1": raise ValueError("unsupported step version")
        for v in (self.step_id,self.delivery_id,self.action_ref,self.target_ref): token(v)


@dataclass(frozen=True)
class SimulationReceipt:
    status: str; reason: str; session_id: str; step_id: str; delivery_id: str; step_index: int; mocked_effects: int
    completed_steps: int; failed_steps: int; unknown_steps: int; rollback_available: bool
    authorized: bool=False; execute: bool=False; external_actions: int=0; version: str="1"
    def __post_init__(self)->None:
        if self.status not in {"denied","cancelled","budget_exhausted","rate_limited","reconciliation_required","verified_complete","failed","outcome_unknown"}: raise ValueError("unsupported simulation status")
        for v in (self.reason,self.session_id,self.step_id,self.delivery_id): token(v)
        for v in (self.step_index,self.mocked_effects,self.completed_steps,self.failed_steps,self.unknown_steps,self.external_actions):
            if isinstance(v,bool) or not isinstance(v,int) or v<0: raise ValueError("receipt counters must be non-negative integers")
        if self.mocked_effects not in {0,1}: raise ValueError("receipt may record at most one mocked effect")
        if self.authorized is not False or self.execute is not False or self.external_actions!=0: raise ValueError("public simulation receipts cannot grant execution authority")
        if not isinstance(self.rollback_available,bool) or self.version!="1": raise ValueError("invalid simulation receipt")


class DelegatedSimulation:
    def __init__(self,grant:DelegationGrant,*,session_id:str,started_at:datetime,max_tracked_deliveries:int=256)->None:
        if not isinstance(grant,DelegationGrant): raise ValueError("trusted delegation grant required")
        token(session_id); started=utc(started_at)
        if started<utc(grant.granted_at) or started>=utc(grant.expires_at): raise ValueError("session start outside delegation lifetime")
        if isinstance(max_tracked_deliveries,bool) or not isinstance(max_tracked_deliveries,int) or not 1<=max_tracked_deliveries<=_MAX_TRACKED_DELIVERIES: raise ValueError("max_tracked_deliveries outside bounded limit")
        self._grant=grant; self._session_id=session_id; self._started_at=started; self._max_tracked_deliveries=max_tracked_deliveries
        self._receipts={}; self._step_receipts={}; self._effect_times=[]; self._lock=Lock()
    def _counts(self):
        vals=self._step_receipts.values(); return (sum(x.status=="verified_complete" for x in vals),sum(x.status=="failed" for x in vals),sum(x.status=="outcome_unknown" for x in vals))
    def _receipt(self,*,status,reason,step,step_index,mocked_effects=0,rollback_available=False):
        c,f,u=self._counts(); return SimulationReceipt(status,reason,self._session_id,step.step_id,step.delivery_id,step_index,mocked_effects,c,f,u,rollback_available)
    def attempt_step(self,step:SimulationStep,*,now:datetime,current_policy_revision:str,current_state_digest:str,current_profile:str,authority_available:bool,cancelled:bool,grant_revoked:bool,mocked_outcome:str,reversible:bool)->SimulationReceipt:
        if not isinstance(step,SimulationStep): raise ValueError("trusted simulation step required")
        now=utc(now); token(current_policy_revision); _digest(current_state_digest,field="current_state_digest")
        if current_profile not in {"read_only","recommend","approval_required","delegated_simulation"}: raise ValueError("unsupported current profile")
        if not all(isinstance(v,bool) for v in (authority_available,cancelled,grant_revoked,reversible)): raise ValueError("boolean flags required")
        if mocked_outcome not in _ALLOWED_OUTCOMES: raise ValueError("unsupported mocked outcome")
        with self._lock:
            existing=self._receipts.get(step.delivery_id)
            if existing is not None:return existing
            prior=self._step_receipts.get(step.step_id); idx=len(self._step_receipts)+1
            if prior is not None:
                if prior.status=="outcome_unknown": return self._receipt(status="reconciliation_required",reason="ambiguous_prior_outcome",step=step,step_index=prior.step_index)
                return self._receipt(status="denied",reason="duplicate_step",step=step,step_index=prior.step_index)
            checks=[(len(self._receipts)>=self._max_tracked_deliveries,"denied","replay_ledger_capacity"),(not authority_available,"denied","authority_unavailable"),(cancelled,"cancelled","session_cancelled"),(self._grant.revoked or grant_revoked,"denied","grant_revoked"),(current_profile!=self._grant.profile,"denied","profile_changed"),(current_policy_revision!=self._grant.policy_revision,"denied","policy_changed"),(current_state_digest!=self._grant.state_digest,"denied","state_changed"),(now>=utc(self._grant.expires_at),"denied","grant_expired")]
            for cond,status,reason in checks:
                if cond:return self._receipt(status=status,reason=reason,step=step,step_index=idx)
            elapsed=(now-self._started_at).total_seconds()
            if elapsed<0:return self._receipt(status="denied",reason="time_reversal",step=step,step_index=idx)
            if elapsed>float(self._grant.max_duration_seconds):return self._receipt(status="budget_exhausted",reason="time_budget",step=step,step_index=idx)
            if len(self._step_receipts)>=self._grant.max_steps:return self._receipt(status="budget_exhausted",reason="step_budget",step=step,step_index=idx)
            if step.action_ref not in self._grant.allowed_actions:return self._receipt(status="denied",reason="action_out_of_scope",step=step,step_index=idx)
            if step.target_ref not in self._grant.allowed_targets:return self._receipt(status="denied",reason="target_out_of_scope",step=step,step_index=idx)
            cutoff=now-timedelta(seconds=60); self._effect_times=[x for x in self._effect_times if x>cutoff]
            if len(self._effect_times)>=self._grant.max_actions_per_minute:return self._receipt(status="rate_limited",reason="rate_budget",step=step,step_index=idx)
            self._effect_times.append(now); receipt=self._receipt(status=mocked_outcome,reason="mocked_effect_recorded",step=step,step_index=idx,mocked_effects=1,rollback_available=reversible and mocked_outcome=="verified_complete")
            self._step_receipts[step.step_id]=receipt; c,f,u=self._counts(); receipt=replace(receipt,completed_steps=c,failed_steps=f,unknown_steps=u); self._step_receipts[step.step_id]=receipt; self._receipts[step.delivery_id]=receipt; return receipt
    def reconcile(self,step_id:str,*,authoritative_outcome:str,reversible:bool)->SimulationReceipt:
        token(step_id)
        if authoritative_outcome not in {"verified_complete","failed"} or not isinstance(reversible,bool): raise ValueError("invalid reconciliation")
        with self._lock:
            prior=self._step_receipts.get(step_id)
            if prior is None: raise ValueError("cannot reconcile an unknown step")
            if prior.status!="outcome_unknown":return prior
            resolved=replace(prior,status=authoritative_outcome,reason="reconciled",mocked_effects=0,rollback_available=reversible and authoritative_outcome=="verified_complete"); self._step_receipts[step_id]=resolved
            c,f,u=self._counts(); resolved=replace(resolved,completed_steps=c,failed_steps=f,unknown_steps=u); self._step_receipts[step_id]=resolved; self._receipts[resolved.delivery_id]=resolved; return resolved


class AuditedDelegatedSimulation(DelegatedSimulation):
    """Synthetic delegation that requires audit admission before any mocked effect.

    Audit admission is not claimed to be durable/tamper-evident here; a private
    production adapter must provide that property. Absence or failure fails closed.
    """
    def __init__(self,grant:DelegationGrant,*,session_id:str,started_at:datetime,audit_sink:AuditBuffer|None,max_tracked_deliveries:int=256)->None:
        super().__init__(grant,session_id=session_id,started_at=started_at,max_tracked_deliveries=max_tracked_deliveries)
        self._audit_sink=audit_sink
        self._audit_gate=Lock()
    def attempt_step(self,step:SimulationStep,*,audit_event:AuditEvent|None,**kwargs)->SimulationReceipt:
        if not isinstance(step,SimulationStep): raise ValueError("trusted simulation step required")
        with self._audit_gate:
            with self._lock:
                existing=self._receipts.get(step.delivery_id)
                if existing is not None:return existing
                idx=len(self._step_receipts)+1
                if self._audit_sink is None:return self._receipt(status="denied",reason="audit_unavailable",step=step,step_index=idx)
                if not isinstance(audit_event,AuditEvent):return self._receipt(status="denied",reason="audit_unavailable",step=step,step_index=idx)
                try:audit_now=utc(kwargs["now"])
                except (KeyError,TypeError,ValueError):return self._receipt(status="denied",reason="audit_binding_mismatch",step=step,step_index=idx)
                if audit_event.request_id!=step.step_id or audit_event.partition!=self._grant.partition or audit_event.principal_ref!=self._grant.principal_ref or audit_event.policy_revision!=self._grant.policy_revision or audit_event.profile!=self._grant.profile or audit_event.grant_ref!=self._grant.grant_id or audit_event.decision!="attempted" or audit_event.outcome!="attempted" or utc(audit_event.recorded_at)!=audit_now:
                    return self._receipt(status="denied",reason="audit_binding_mismatch",step=step,step_index=idx)
                try:self._audit_sink.append(audit_event)
                except Exception:return self._receipt(status="denied",reason="audit_admission_failed",step=step,step_index=idx)
            return super().attempt_step(step,**kwargs)
