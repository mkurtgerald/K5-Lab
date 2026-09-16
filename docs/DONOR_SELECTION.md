# Donor selection

Review date: 2026-09-16. "Candidate" is not installed, integrated, or approved for
commercial distribution. Actual local results are provided separately.

| Donor | Role | Upstream code license | Initial disposition |
|---|---|---|---|
| RDFLib | Generic RDF graph representation | BSD-3-Clause | Implemented adapter |
| scikit-learn | Reproducible ordinary ML baselines and metrics | BSD-3-Clause | Implemented benchmark |
| PyTorch | Optional small neural baseline | BSD-style project; binary distribution includes other terms | Implemented optional benchmark |
| pySHACL | Validate RDF shape constraints | Apache-2.0 | S1 candidate |
| Google OR-Tools | Bounded constraint optimization | Apache-2.0 | S1 candidate; use CP-SAT, not unreviewed external solvers |
| River | Incremental/streaming learning and drift | BSD-3-Clause | S2 candidate |
| Gymnasium | Standard simulation interface | MIT | S3 candidate |
| Stable-Baselines3 | Reproducible RL algorithms over PyTorch | MIT | S3 candidate |
| Ray/RLlib | Distributed or multi-agent training | Apache-2.0 | Deferred until profiling justifies it |
| Open Policy Agent | External deterministic policy enforcement | Apache-2.0 | Deferred; no implementation or policy supplied |

This ordering favors measurable capability with low integration burden, not a
claim that one model is universally best. Neural complexity must beat an
ordinary/constrained baseline under the same test conditions.

Representation and validation remain independent from learning. Learned scores
must not silently rewrite facts, schemas, authorization, or protected rules.

Only upstream APIs are used. No donor algorithm source, pretrained model,
external training data, or private implementation is vendored in this package.
References and release-review requirements are in `THIRD_PARTY.md`.
