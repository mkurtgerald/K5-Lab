# S5 confidence, abstention and explainable evidence

Status: public S5 candidate. Synthetic and domain-neutral only.

This stage keeps raw model scores explicitly separate from calibrated probability. `ConfidenceObservation` accepts only bounded opaque identifiers, a timezone-aware observation time, a finite unit-interval raw score, explicit prediction/label/abstention/drift flags and bounded opaque provenance references. The public contract does not expose product feature meanings, response policy, private ontology or platform integration.

`calibration_report` is a bounded empirical diagnostic over one partition and one model version. It reports answered coverage, abstention, balanced accuracy when both answered classes are present, false-positive/false-negative rates when defined, raw-score Brier error, answered-only Brier error and bounded-bin expected calibration error. Duplicate samples, partition mixing and model-version mixing fail closed. Evidence sufficiency requires the configured minimum number of **answered** samples with both answered label classes represented; broad abstention cannot manufacture sufficient evidence.

Passing those diagnostics does **not** convert a raw score into a probability. The report deliberately retains `score_semantics=uncalibrated_score` and `calibrated_probability_established=false`; a future separately reviewed calibration stage would be required to claim probability semantics. Report objects validate their own bounded counts/rates and coverage/abstention consistency so malformed or reconstructed state fails closed.

`evidence_receipt` creates a deterministic canonical digest over the opaque decision evidence: partition, sample/model identity, raw score, prediction, abstention, drift state, rule identifier and bounded provenance references. When event provenance is supplied, every referenced event must be resident in the same S4 `BoundedEventMemory` partition before a receipt can be issued. Receipt objects recompute their own digest on construction, so tampered or reconstructed receipts fail closed. Receipts expose no hidden chain-of-thought or private feature semantics, remain permanently non-authorizing and record zero external actions.

The synthetic S5 quality harness evaluates fixed seeds across stationary and shifted streams using the existing reviewed River adapter. It reports the same bounded confidence diagnostics plus deterministic receipt digests, diagnostic/receipt p50/p95 latency observations and Python-side peak allocation. The thresholds are deliberately conservative regression guards, not production performance claims. Raw scores remain explicitly uncalibrated in every scenario and production qualification remains false.

Focused negative tests cover malformed/non-finite scores, unsupported versions, duplicate provenance, insufficient or one-class answered evidence, all-abstained windows, partition/model/sample mixing, missing and cross-partition resident provenance, canonical deterministic receipts, decision-state changes and receipt/report tampering. All S0-S4 checks remain required.

Private K5/EdgeVMS ontology extensions, feature semantics, response policies, real sensor data/topology, credentials, production weights and platform adapters remain outside this repository. Commercial distribution remains subject to later release gates and explicit owner approval.
