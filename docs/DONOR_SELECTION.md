# Donor selection

Review date: 2026-09-16. "Candidate" is not installed, integrated, or approved for
commercial distribution. Actual execution results are recorded separately.

| Donor | Role | Upstream code license | Initial disposition |
|---|---|---|---|
| RDFLib | Generic RDF graph representation | BSD-3-Clause | Implemented adapter; S1 candidate upgrade to 7.6.0 |
| scikit-learn | Reproducible ordinary ML baselines and metrics | BSD-3-Clause | Implemented benchmark |
| PyTorch | Optional small neural baseline | BSD-style project; binary distribution includes other terms | Implemented optional benchmark |
| pySHACL | Validate RDF shape constraints | Apache-2.0 | S1 selected candidate: 0.40.1, bounded in-memory adapter |
| Google OR-Tools | Bounded constraint optimization | Apache-2.0 | S1 allocation candidate; evaluate only after graph-validation precursor is green; use CP-SAT, not unreviewed external solvers |
| River | Incremental/streaming learning and drift | BSD-3-Clause | S2 candidate |
| Gymnasium | Standard simulation interface | MIT | S3 candidate |
| Stable-Baselines3 | Reproducible RL algorithms over PyTorch | MIT | S3 candidate |
| Ray/RLlib | Distributed or multi-agent training | Apache-2.0 | Deferred until profiling justifies it |
| Open Policy Agent | External deterministic policy enforcement | Apache-2.0 | Deferred; no implementation or policy supplied |

pySHACL 0.40.1 requires owlrl 7.6.2, whose published license is the W3C Software
Notice and License, plus RDFLib's HTML extra dependency. Exact pins and artifact
digests for the selected Python runtime chain are recorded in the S1 receipt and
provenance ledger. Optional remote/server/JavaScript/Oxigraph extras are excluded.
Commercial-distribution approval remains false pending bundle-level review.

This ordering favors measurable capability with low integration burden, not a
claim that one model is universally best. Neural complexity must beat an
ordinary/constrained baseline under the same test conditions.

Representation and validation remain independent from learning. Learned scores
must not silently rewrite facts, schemas, authorization, or protected rules.

Only upstream APIs are used. No donor algorithm source, pretrained model,
external training data, or private implementation is vendored in this package.
References and release-review requirements are in `THIRD_PARTY.md`.
