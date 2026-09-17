# S6 robustness and failure-boundary qualification

Status: active public qualification stage. Synthetic and domain-neutral only.

The first S6 slice hardens the learned-policy proposal receipt itself. Previously, `evaluate_policy_proposal` enforced hard boundaries, but the frozen receipt data class did not independently validate a directly reconstructed object. A caller could therefore create an internally inconsistent receipt or set authority/effect fields when bypassing the factory. The contract now validates bounded action fields, version, strict boolean acceptance, accepted-versus-fallback state, known fallback reason, permanent `authorized=false`, and exactly zero external actions on every construction path.

This does not make a learned proposal authoritative. It makes the public receipt fail closed even when reconstructed or tampered with outside the normal evaluator. Existing predictor exceptions, malformed outputs and prohibited proposals still fall back to a caller-permitted action; invalid caller configuration still fails before the predictor executes.

The focused local preflight for this slice passed all eight policy-adapter tests, including direct reconstruction/tamper cases and inconsistent fallback states. Because `src/mosaic_lab/policy_adapter.py` is part of the isolated S3 learned-policy workflow trigger, remote acceptance must pass both the complete Generic checks and the CPU-only Stable-Baselines3/PyTorch learned-policy workflow for the exact head before this slice can be accepted.

S6 remains broader than this hardening increment. Fixed stress scenarios, learned-versus-deterministic quality floors, longer rollouts, boundary/extreme observations, action scarcity, cross-stage drift/failure degradation, latency/resource envelopes and packaging-facing qualification evidence remain required. Production qualification and commercial distribution remain false until later release gates and explicit owner approval.
