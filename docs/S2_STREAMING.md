# S2 streaming-learning candidate

Status: evaluation candidate only. This stage does not approve commercial distribution or production use.

## Selected donor

River 0.26.1 is the first incremental-learning donor evaluated for S2. The upstream tag `0.26.1` resolves to commit `64285b9dd6c606804753235fe992bcf25b9856ee`. Upstream metadata declares BSD-3-Clause and Python >=3.11. Its core dependency constraints are SciPy >=1.14.1,<2, NumPy >=2.2.5,<3, and Narwhals >=2.0.0. The package is built with Maturin and includes a Rust extension; therefore source-license review is not binary-bundle approval.

The candidate pins River 0.26.1 and Narwhals 2.26.0 alongside the already pinned NumPy/SciPy runtime. Narwhals is MIT.

Hosted Linux CI selects `river-0.26.1-cp313-cp313-manylinux_2_28_x86_64.whl`. Its PyPI SHA-256 is `7d8e6aa749f06e6bd71835ef722c14627bbb049f6929f5bc0d8a65dcd813ad4b`; PyPI Trusted Publishing provenance identifies upstream tag `0.26.1` at commit `64285b9dd6c606804753235fe992bcf25b9856ee`. The selected Narwhals wheel SHA-256 is also recorded in `provenance/s2-streaming.json`. Digest/provenance capture does not approve the embedded native bundle for distribution; native-library inventory, notices, SBOM, vulnerability and platform review remain separate release controls.

## Adapter boundary

`RiverBinaryAdapter` exposes one fixed binary incremental learner and ADWIN error-stream drift detector. It accepts only bounded immutable numeric feature tuples, one opaque partition, ordered source timestamps, and boolean training labels. It rejects cross-partition input, invalid/oversized features, source growth beyond the fixed budget, out-of-order updates, and update-budget exhaustion.

Prediction receipts explicitly carry `authorized=false`. Learned scores are not described as calibrated probabilities. Unlabeled inputs can be scored but cannot update model or temporal state. The public adapter exposes no model/plugin selector, remote resource, execution endpoint, or external action.

## Checkpoint boundary

`stream_checkpoint` adds a project-owned, version-pinned checkpoint codec without filesystem access or pickle. It serializes the fixed scaler/logistic state, temporal source ordering, optimizer iteration, and River ADWIN native helper state into bounded canonical JSON bytes. Restore requires the exact model id and installed River version, validates all feature/state bounds, verifies the native-state digest before handing bytes to the pinned Rust helper, restores the drift flag, and requires the wrapper state receipt to match before returning an adapter.

The envelope SHA-256 is an accidental-corruption check, not authentication. A downstream private integration must authenticate checkpoint storage or transport at its own trust boundary. Checkpoints from untrusted writers are not accepted as authenticated merely because their digest is internally consistent. The codec never grants execution authority and does not contain product-specific policy or data.

The River 0.26.1 source explicitly exposes `StandardScaler` running state and the Rust `AdaptiveWindowing` `__getstate__`/`__setstate__` bytes used by this exact-version codec. The logistic learner restore path is deliberately tied to the reviewed fixed pipeline and is covered by round-trip/continuation regressions. A River upgrade requires a new checkpoint-version review rather than silently reusing this format.

## Synthetic evaluation

The stage adds an in-memory drift fixture and prequential benchmark. A River learner is compared with a frozen scikit-learn logistic baseline trained only on an early stationary window. Reported evidence includes post-drift balanced accuracy, mean squared score error, abstention rate, drift-detection indexes, p50/p95 per-update latency, bounded source/update counts, exact installed package versions, and a wrapper-state receipt.

A separate multi-seed acceptance sweep fixes the abstention margin at 0.04 and evaluates five independent synthetic seeds rather than selecting a favorable seed. The initial regression envelope requires at least 75% answered coverage, at most 25% answered false-positive and false-negative rates, and at most 0.20 selective mean-squared score error for every included seed. These are S2 synthetic regression floors, not production accuracy targets.

The fixture is synthetic and generic. It is not evidence of real-world sensor intelligence, calibration, safety, or production quality. No production weights or input records are saved.

## Robustness observations

S2 now includes deterministic synthetic prior-label corruption, rare-tail observations, missing-feature rejection, and non-finite-feature rejection. For seed 31, 22 training labels were flipped before the held-out evaluation window and then clean supervision resumed. The clean held-out stream answered 94.67% with balanced accuracy 95.79%, while the prior-poisoned history answered 94.22% with balanced accuracy 95.32%. The rare-tail slice contained 14 observations; its clean error rate was 21.43% and the prior-poisoned-history error rate was 35.71%.

These figures are observations, not a robustness certification or a product threshold. In particular, the rare-tail result is retained as an explicit limitation rather than hidden behind aggregate accuracy. Missing-length and NaN/inf feature inputs fail closed before model update, and the robustness harness exposes no external action path.

## Hosted Linux native/runtime evidence

Exact-head CI inventories installed native files for the pinned River/Narwhals/NumPy/SciPy runtime, hashes every native file, records a deterministic manifest digest, inspects Linux dynamic dependencies, and fails closed on unresolved external SONAMEs. A bundled dependency is accepted as wheel-local only when the exact missing SONAME basename is itself present in the same installed distribution; unknown missing libraries remain fatal.

On CPython 3.13.15 / Ubuntu 24.04 x86_64, River 0.26.1 contains one native extension, `river/_river_rust.cpython-313-x86_64-linux-gnu.so`, SHA-256 `ec674139a52d24c18bb395e4a6cf12909f0b1e5ae42c55f927947538c7944d55`. Narwhals 2.26.0 contains no native files. NumPy 2.3.5 contains 22 native files with manifest SHA-256 `9d5d7cfd6f7662443b052628b7d490cc59181ed102982b9bd0dc3c443930bf64`; SciPy 1.17.0 contains 114 native files with manifest SHA-256 `a60e7dc681ddde428b7f4b1d98bb6e740786de783db002e716ea6b8ae5fda17e`. The hosted Linux audit reports no unresolved dynamic dependencies.

A post-warmup RSS smoke exercises five fixed synthetic seeds (19/31/43/59/71), 600 samples each. On the latest exact-head run baseline RSS was 168124 KiB and each measured run was 168128 KiB, for 4 KiB maximum observed growth. This is only a bounded hosted-Linux synthetic leak smoke. It is not a production memory envelope, heap/native-allocation attribution, long-duration soak, or cross-platform qualification.

The first native-audit CI attempt exposed an audit defect: directly running `ldd` on a SciPy-bundled shared library misclassified a wheel-local `libquadmath` as externally unresolved. That deterministic implementation failure was not rerun unchanged. The audit was corrected to distinguish exact wheel-local basenames from truly unresolved external dependencies, a regression was added, and the corrected exact head passed the complete CI set.

## Gate boundary

S2 is an experiment/evaluation gate, not a release gate. Its exit evidence is the bounded streaming adapter, failure-path coverage, drift and multi-seed held-out evaluation, abstention/error measurements, checkpoint/reload handling, robustness observations, native-inclusive bounded-memory smoke, provenance, and exact-head CI. Commercial distribution remains false.

Release-level SBOM generation/review, required notices, known-vulnerability review, and target-platform/release-bundle review remain mandatory before GTM approval and are owned by the packaging/release gate in `docs/SPRINTS.md`. Native inventory outside the hosted Linux runtime is not claimed complete.
