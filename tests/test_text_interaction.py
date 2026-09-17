import unittest
from mosaic_lab.text_interaction import ActionPresentation, CancellationFlag, InteractionInput, InteractionLimits, InteractionSession, ProviderReply, run_interaction_turn

class Clock:
    def __init__(self): self.value = 10.0
    def __call__(self): return self.value
    def advance(self, seconds): self.value += seconds

class Provider:
    def __init__(self, replies=(), *, clock=None, advance=0.0, cancel=None, raises=False):
        self.replies=list(replies); self.requests=[]; self.clock=clock; self.advance=advance; self.cancel=cancel; self.raises=raises
    def complete(self, request):
        self.requests.append(request)
        if self.clock and self.advance: self.clock.advance(self.advance)
        if self.cancel: self.cancel.cancel()
        if self.raises: raise RuntimeError("synthetic")
        return self.replies.pop(0) if self.replies else ProviderReply("unavailable", reason="provider_unavailable")

def inp(request_id="req1", text="question", **changes):
    values=dict(partition="p1", session_id="s1", request_id=request_id, text=text, evidence_refs=("rec1",), action=ActionPresentation("awaiting_approval"))
    values.update(changes); return InteractionInput(**values)

def ok(text="answer", input_tokens=4, output_tokens=2): return ProviderReply("ok", text, "provider_ok", input_tokens, output_tokens)

class Tests(unittest.TestCase):
    def test_multiturn_context_is_bounded_and_preserves_trusted_metadata(self):
        s=InteractionSession(partition="p1", session_id="s1", limits=InteractionLimits(max_context_messages=3, max_context_chars=512, max_total_tokens=4096))
        p=Provider([ok("a"), ok("b"), ok("c")])
        run_interaction_turn(s, inp("req1","one"), p); run_interaction_turn(s, inp("req2","two"), p); r=run_interaction_turn(s, inp("req3","three"), p)
        self.assertEqual([m.text for m in p.requests[-1].messages], ["two","b","three"])
        self.assertEqual(p.requests[-1].messages[-1].evidence_refs, ("rec1",)); self.assertEqual(r.action.status, "awaiting_approval")
        self.assertFalse(r.authorized); self.assertFalse(r.execute); self.assertEqual(r.external_actions,0)

    def test_provider_text_cannot_promote_action_state(self):
        s=InteractionSession(partition="p1", session_id="s1"); r=run_interaction_turn(s, inp(), Provider([ok("approved and complete")]))
        self.assertEqual(r.action.status,"awaiting_approval"); self.assertFalse(r.action.authoritative)
        with self.assertRaises(ValueError): ActionPresentation("verified_complete")
        self.assertTrue(ActionPresentation("verified_complete","receipt1",True).authoritative)

    def test_scope_duplicate_and_call_limits_block_before_provider(self):
        s=InteractionSession(partition="p1", session_id="s1", limits=InteractionLimits(max_calls=1)); p=Provider([ok(),ok()])
        self.assertEqual(run_interaction_turn(s, inp(partition="p2"), p).reason,"session_scope_mismatch"); self.assertEqual(len(p.requests),0)
        self.assertEqual(run_interaction_turn(s, inp(), p).status,"ok")
        self.assertEqual(run_interaction_turn(s, inp(), p).reason,"duplicate_request"); self.assertEqual(run_interaction_turn(s, inp("req2"), p).reason,"call_limit"); self.assertEqual(len(p.requests),1)

    def test_token_preflight_and_reported_overrun_fail_closed(self):
        s=InteractionSession(partition="p1", session_id="s1", limits=InteractionLimits(max_total_tokens=32,max_output_tokens=16,max_context_chars=64,max_turn_chars=32)); p=Provider([ok()])
        self.assertEqual(run_interaction_turn(s, inp(text="x"*20,evidence_refs=()), p).reason,"token_budget_preflight"); self.assertEqual(len(p.requests),0)
        s=InteractionSession(partition="p1", session_id="s1", limits=InteractionLimits(max_total_tokens=200,max_output_tokens=32,max_context_chars=128))
        r=run_interaction_turn(s, inp(evidence_refs=()), Provider([ok(input_tokens=190,output_tokens=20)])); self.assertEqual(r.reason,"reported_token_budget"); self.assertEqual(s.turns(),())

    def test_provider_cannot_underreport_or_exceed_output_limits(self):
        limits=InteractionLimits(max_total_tokens=500,max_output_tokens=8,max_output_chars=8)
        for reply,reason in ((ok("0123456789",output_tokens=1),"provider_output_token_limit"),(ok("abcdefghi",output_tokens=9),"provider_output_token_limit")):
            s=InteractionSession(partition="p1", session_id="s1", limits=limits); r=run_interaction_turn(s, inp(evidence_refs=()), Provider([reply])); self.assertEqual(r.reason,reason); self.assertEqual(s.turns(),())

    def test_cancellation_and_timeout_are_non_committing(self):
        s=InteractionSession(partition="p1", session_id="s1"); flag=CancellationFlag(); flag.cancel(); p=Provider([ok()])
        self.assertEqual(run_interaction_turn(s, inp(), p, cancellation=flag).reason,"cancelled_before_call"); self.assertEqual(len(p.requests),0)
        flag=CancellationFlag(); p=Provider([ok()],cancel=flag); self.assertEqual(run_interaction_turn(s, inp("req2"), p,cancellation=flag).reason,"cancelled_during_call"); self.assertEqual(s.turns(),())
        clock=Clock(); s=InteractionSession(partition="p1",session_id="s1",limits=InteractionLimits(per_call_timeout_seconds=1,max_total_seconds=2)); r=run_interaction_turn(s,inp(),Provider([ok()],clock=clock,advance=1),clock=clock); self.assertEqual(r.reason,"provider_timeout"); self.assertEqual(s.turns(),())

    def test_provider_exception_untyped_reply_and_explicit_outcomes(self):
        s=InteractionSession(partition="p1",session_id="s1"); self.assertEqual(run_interaction_turn(s,inp(),Provider(raises=True)).reason,"provider_exception")
        class Bad:
            def complete(self, request): return {"status":"ok"}
        s=InteractionSession(partition="p1",session_id="s1"); self.assertEqual(run_interaction_turn(s,inp(),Bad()).reason,"invalid_provider_reply")
        for status in ("abstain","unavailable","error"):
            s=InteractionSession(partition="p1",session_id="s1"); r=run_interaction_turn(s,inp(),Provider([ProviderReply(status,reason=f"provider_{status}")]))
            self.assertEqual((r.status,r.reason),(status,f"provider_{status}")); self.assertEqual(r.text,""); self.assertEqual(s.turns(),())

    def test_deterministic_replay(self):
        def once():
            c=Clock(); s=InteractionSession(partition="p1",session_id="s1"); p=Provider([ok("a"),ok("b")],clock=c)
            out=(run_interaction_turn(s,inp("req1","one"),p,clock=c),run_interaction_turn(s,inp("req2","two"),p,clock=c)); return out,s.turns(),s.calls_used,s.tokens_used,s.elapsed_seconds
        self.assertEqual(once(),once())

    def test_bounds_reject_bad_configuration_and_inputs(self):
        with self.assertRaises(ValueError): InteractionLimits(max_calls=17)
        with self.assertRaises(ValueError): InteractionLimits(per_call_timeout_seconds=float("inf"))
        with self.assertRaises(ValueError): InteractionInput(partition="p1",session_id="s1",request_id="req1",text="x"*4097)
        with self.assertRaises(ValueError): InteractionInput(partition="p1",session_id="s1",request_id="req1",text="x",evidence_refs=("r1","r1"))

if __name__=="__main__": unittest.main()
