# S6 robustness and failure-boundary qualification

Status: exit-candidate public qualification stage. Synthetic and domain-neutral only. Commercial distribution and production qualification remain false.

## Safety boundary

All public decision/proposal receipts exercised by S6 remain non-authorizing and self-validating. Direct reconstruction or tampering cannot manufacture authority, external effects, invalid versions, inconsistent accepted/fallback state, or malformed bounded actions. Learned recommendations are always filtered through caller-supplied hard constraints; predictor exceptions, malformed outputs, and prohibited proposals fall back safely. No S6 path performs physical actuation or external actions.

## Learned-policy stress

The isolated CPU-only lane pins Stable-Baselines3 `2.9.0` and PyTorch `2.14.0+cpu`, disables CUDA, uses deterministic algorithms, trains only in synthetic memory, and saves no policy. The current candidate is DQN with 8,192 bounded training timesteps.

Held-out acceptance uses seeds `101,103,107,109,113` at horizon 64. Separate stress uses seeds `127,131,137,139,149,151,157,163` at horizon 128. Boundary observations, action scarcity, predictor exceptions, boolean/array/nonfinite malformed outputs, deterministic replay, and hard-constraint enforcement are exercised in the same lane.

Evidence from exact source head `c0ff1e0b9d9ca00789250daa29cedf5b024a561d`, isolated run `35176622689`:
- training wall time: `12.967708 s`;
- observed process max-RSS delta: `16,312 KiB`;
- maximum observed learned p95 inference latency: `0.225043 ms` against a `5 ms` gate;
- acceptance mean reward: learned `12.972`, heuristic `12.56`, CP-SAT `12.972`;
- long-horizon stress mean reward: learned `26.0425`, heuristic `25.19625`, CP-SAT `26.0425`;
- stress learned/heuristic ratio `1.033586`; learned/CP-SAT ratio `1.0`;
- constraint violations `0`, authorization `false`, external actions `0`, saved policy `false`.

These are hosted synthetic regression results, not production performance claims. The learned component remains optional: CP-SAT is the simpler constrained reference and the learned candidate must continue earning its place.

## Streaming robustness

The fixed five-seed streaming acceptance set remains `7,19,31,43,59`. Current fail-closed robustness covers stationary and shifted evaluation, missing/nonfinite inputs, bounded pre-evaluation label poisoning, rare-tail observations, cold start, abstention, and checkpoint/restore corruption paths.

Evidence from Generic checks run `35176622703`:
- minimum poisoned-history balanced accuracy `0.913272`;
- minimum poisoned-history answered rate `0.933333`;
- maximum poisoned answered FPR `0.147368`;
- maximum poisoned answered FNR `0.092593`;
- maximum poisoned selective MSE `0.074836`;
- minimum cold-start balanced accuracy `0.920186`;
- 74 rare-tail samples, weighted rare error `0.148649` after poisoned history versus `0.121622` clean;
- score semantics remain explicitly `uncalibrated_score`; production qualification remains false.

Representative stream update latency at seed 31 was `0.0327 ms` p50 / `0.0401 ms` p95. The hosted Linux native-RSS smoke observed a maximum `4 KiB` post-warmup growth across its fixed seed set; that smoke is not a production memory qualification.

## Memory, correlation, confidence, and cross-stage failures

Memory is bounded, partition-isolated, deterministic, and non-executing. The stress fixture keeps at most 32 resident events across 320 sequential inserts, validates count- and age-based dependent eviction, rejects too-late input without state mutation, and preserves partition isolation.

At 512 synthetic events, the current hosted measurement recorded:
- insert `0.814217 ms` p50 / `1.528697 ms` p95;
- query `0.264796 ms` p50 / `0.29855 ms` p95;
- correlation `0.016551 ms` p50 / `0.030958 ms` p95;
- Python tracemalloc peak `315.266 KiB`.

Confidence/evidence diagnostics recorded `1.017709 ms` p50 / `1.277335 ms` p95, evidence receipt construction `0.127418 ms` p50 / `0.153026 ms` p95, and maximum Python tracemalloc peak `26.514 KiB`. Raw scores are explicitly uncalibrated and receipts remain non-authorizing.

The cross-stage qualification added at this head proves:
- provenance eviction makes new correlation and evidence issuance fail closed;
- the supported 32-event correlation fan-in is deterministic and a 33-event request is rejected;
- evidence at score edges `0.0` and `1.0` remains explicitly uncalibrated and non-authorizing;
- prohibited learned proposals, predictor exceptions, and malformed learned outputs all return safe fallback receipts;
- every tested path keeps `authorized=false`, `external_actions=0`, and `production_qualified=false`.

## Runtime and publication boundary

Generic CI runs on CPython `3.13.15` / hosted Ubuntu 24.04 x86-64 with exact core dependency pins. Native inventory currently records River `0.26.1`, NumPy `2.3.5`, and SciPy `1.17.0` native surfaces and unresolved dynamic dependency count `0` for the inspected hosted environment. The isolated learned lane verifies Stable-Baselines3 `2.9.0`, PyTorch `2.14.0+cpu`, and CUDA unavailable. Existing donor/license review and artifact provenance remain release prerequisites; none of this evidence grants commercial distribution approval.

The publication boundary runs before dependency installation and passed for the exact source head. Public fixtures remain synthetic/opaque; no credentials, real sensor data/topology, private adapters, proprietary ontology extensions, response policy, private training objectives/rewards, or learned weights are part of this public qualification.

## Reliability and exit discipline

Generic checks run `35176622703` passed on the first attempt with `161/161` tests plus all benchmark/failure-path gates. Isolated learned-policy run `35176622689` also passed on its first attempt. No unchanged retry was used for this increment. The mature `<5%` first-attempt target is not claimed from an insufficient sample; raw historical failures remain visible in CI/PR history and are not excluded or rerun away.

S6 may merge only from an exact green revision with the base unchanged. Completing S6 does not make K5-Lab GTM-ready. Packaging, SBOM/notices/vulnerability review, versioned private-adapter contracts, security/privacy review, rollback/fail-safe integration behavior, integration documentation, and explicit owner release approval remain later release gates.
