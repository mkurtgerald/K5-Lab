# S5 confidence, abstention and explainable evidence

Status: public S5 candidate. Synthetic and domain-neutral only.

This stage keeps raw model scores explicitly separate from calibrated probability. `ConfidenceObservation` accepts only bounded opaque identifiers, a timezone-aware observation time, a finite unit-interval raw score, explicit prediction/label/abstention/drift flags and bounded opaque provenance references. The public contract does not expose product feature meanings, response policy, private ontology or platform integration.

`calibration_report` is a bounded empirical diagnostic over one partition and one model version. It reports answered coverage, abstention, balanced accuracy when both answered classes are present, false-positive/false-negative rates when defined, raw-score Brier error, answered-only Brier error and bounded-bin expected calibration error. Duplicate samples, partition mixing and model-version mixing fail closed. Evidence sufficiency requires a configurable minimum sample count, both label classes and at least one answered observation.

Passing those diagnostics does **not** convert a raw score into a probability. The report deliberately retains `score_semantics=uncalibrated_score` and `calibrated_probability_established=false`; a future separately reviewed calibration stage would be required to claim probability semantics.

`evidence_receipt` creates a deterministic canonical digest over the opaque decision evidence: partition, sample/model identity, raw score, prediction, abstention, drift state, rule identifier and bounded provenance references. Receipts expose no hidden chain-of-thought or private feature semantics, remain permanently non-authorizing and record zero external actions.

The initial focused tests cover malformed/non-finite score rejection, duplicate provenance, insufficient evidence, single-class windows, all-abstained windows, partition/model/sample mixing, canonical deterministic receipts and evidence changes when decision state changes. Multi-seed stationary/shifted holdout benchmarking, latency/resource measurements, tamper checks and broader integration with S4 provenance remain required before S5 exit.

Private K5/EdgeVMS ontology extensions, feature semantics, response policies, real sensor data/topology, credentials, production weights and platform adapters remain outside this repository. Commercial distribution remains subject to later release gates and explicit owner approval.
