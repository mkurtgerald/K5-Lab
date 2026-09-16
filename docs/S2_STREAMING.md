# S2 streaming-learning candidate

Status: evaluation candidate only. This stage does not approve commercial distribution or production use.

## Selected donor

River 0.26.1 is the first incremental-learning donor evaluated for S2. The upstream tag `0.26.1` resolves to commit `64285b9dd6c606804753235fe992bcf25b9856ee`. Upstream metadata declares BSD-3-Clause and Python >=3.11. Its core dependency constraints are SciPy >=1.14.1,<2, NumPy >=2.2.5,<3, and Narwhals >=2.0.0. The package is built with Maturin and includes a Rust extension; therefore source-license review is not binary-bundle approval.

The candidate pins River 0.26.1 and Narwhals 2.26.0 alongside the already pinned NumPy/SciPy runtime. Narwhals is MIT. Exact downloaded River wheel/native-library inventory and distribution notices remain release-review work.

## Adapter boundary

`RiverBinaryAdapter` exposes one fixed binary incremental learner and ADWIN error-stream drift detector. It accepts only bounded immutable numeric feature tuples, one opaque partition, ordered source timestamps, and boolean training labels. It rejects cross-partition input, invalid/oversized features, source growth beyond the fixed budget, out-of-order updates, and update-budget exhaustion.

Prediction receipts explicitly carry `authorized=false`. Learned scores are not described as calibrated probabilities. Unlabeled inputs can be scored but cannot update model or temporal state. The public adapter exposes no model/plugin selector, remote resource, execution endpoint, or external action.

## Checkpoint boundary

`stream_checkpoint` adds a project-owned, version-pinned checkpoint codec without filesystem access or pickle. It serializes the fixed scaler/logistic state, temporal source ordering, optimizer iteration, and River ADWIN native helper state into bounded canonical JSON bytes. Restore requires the exact model id and installed River version, validates all feature/state bounds, verifies the native-state digest before handing bytes to the pinned Rust helper, restores the drift flag, and requires the wrapper state receipt to match before returning an adapter.

The envelope SHA-256 is an accidental-corruption check, not authentication. A downstream private integration must authenticate checkpoint storage or transport at its own trust boundary. Checkpoints from untrusted writers are not accepted as authenticated merely because their digest is internally consistent. The codec never grants execution authority and does not contain product-specific policy or data.

The River 0.26.1 source explicitly exposes `StandardScaler` running state and the Rust `AdaptiveWindowing` `__getstate__`/`__setstate__` bytes used by this exact-version codec. The logistic learner restore path is deliberately tied to the reviewed fixed pipeline and is covered by round-trip/continuation regressions. A River upgrade requires a new checkpoint-version review rather than silently reusing this format.

## Synthetic evaluation

The stage adds an in-memory drift fixture and prequential benchmark. A River learner is compared with a frozen scikit-learn logistic baseline trained only on an early stationary window. Reported evidence includes post-drift balanced accuracy, mean squared score error, abstention rate, drift-detection indexes, p50/p95 per-update latency, bounded source/update counts, exact installed package versions, and a wrapper-state receipt.

The fixture is synthetic and generic. It is not evidence of real-world sensor intelligence, calibration, safety, or production quality. No production weights or input records are saved.

## Remaining S2 exit work

Before S2 can close, the candidate still requires exact hosted artifact/native-library capture, stronger multi-seed held-out drift assertions, explicit memory-growth/native-allocation review, and exact-head CI on the complete S2 acceptance set. Commercial distribution remains false until SBOM/notices/vulnerability/platform review is complete.
