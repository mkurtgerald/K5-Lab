# Verification receipt

Local verification date: 2026-09-16.

- Python 3.13.5 on Linux.
- 53 automated tests passed across contracts, graph/provenance isolation,
  proposal-gate negative paths, synthetic ML, publication scanning, and the
  deliberately blocked release-review state.
- Two synthetic runs (seeds 17 and 29) each compared logistic regression,
  histogram gradient boosting, and a PyTorch CPU multilayer perceptron.
- Each run used 2,400 synthetic rows: 1,440 train, 480 validation, 480 test.
  Models were selected by validation log loss before test metrics were computed.
- Neither run saved weights, input records, or other training artifacts.
- The public-boundary heuristic scan passed. Human review remains necessary.
- This receipt describes local execution only. Remote CI must be verified on
  the exact published commit; no remote pass is asserted by this document.
- No branch protections, scheduled workers, or production integrations are
  established by these source files.
- Candidate donor integrations in S1-S4 were NOT executed. No pretrained models
  were downloaded; no production/data rights or shipping approval is asserted.
- Commercial-distribution release check remains deliberately blocked until exact
  artifacts, transitive dependencies, native libraries, notices, and security
  reviews are completed.

This is a generic synthetic scaffold receipt, not product capability validation.
