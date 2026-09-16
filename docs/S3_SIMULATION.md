# S3 generic simulation and learned-proposal candidate

Status: synthetic evaluation candidate only. No production policy, external action, deployment authority, or commercial-distribution approval is created by this stage.

## Environment boundary

Gymnasium 1.3.0 is the selected environment-interface donor. Upstream tag `v1.3.0` resolves to commit `53bf3e9a884783eb72ad3fc8b15780914c97c3e1`. The tagged project metadata declares MIT, Python >=3.10, and base dependencies on NumPy, cloudpickle, typing-extensions, and Farama-Notifications. No optional environment families or Torch extras are enabled.

The reviewed PyPI wheel is `gymnasium-1.3.0-py3-none-any.whl`, SHA-256 `6b8c159a8540dcbcb221722d7efda24d78ebbcbc3bd2ea1c2611aa2a34471fc2`. The dependency candidate pins cloudpickle 3.1.2 (BSD-3-Clause; wheel SHA-256 `9acb47f6afd73f60dc1df93bb801b472f05ff42fa6c84167d25cb206be1fbf4a`) and Farama-Notifications 0.0.6 (MIT; wheel SHA-256 `f84839188efa1ce5bb361c2a84881b2dc2c0d0d7fb661ff00421820170930935`). Existing NumPy 2.3.5 and typing-extensions 4.16.0 pins satisfy the other base requirements.

Cloudpickle is present only because Gymnasium requires it. This project does not call cloudpickle/pickle serialization or load serialized Python objects in the S3 environment path.

## Environment contract

`BoundedProposalEnv` exposes a fixed five-value float observation and three discrete proposals. The two utility values and two permission flags are opaque synthetic quantities; the fifth value is bounded episode phase. Action 0 is a safe no-op. Proposals 1 and 2 may be prohibited by the current synthetic permission flags. Project-owned filtering converts a prohibited proposal to no-op, records a constraint violation, returns a synthetic penalty, and never marks the proposal authorized.

Invalid action encodings, malformed/non-finite observations, unsupported versions, unsupported reset options, out-of-range horizons, and post-truncation stepping fail closed. Reset with a fixed seed is reproducible. The environment exposes no network/resource locator, plugin/model selector, credential, platform adapter, or external executor.

## Baselines and learned candidate

The S3 baseline set contains no-op, a deterministic heuristic, and a bounded single-worker CP-SAT selector. CP-SAT uses the already accepted OR-Tools donor and can select only currently permitted actions.

After the environment and baselines were green, S3 evaluated Stable-Baselines3 2.9.0 with PyTorch 2.14.0+cpu in a separate CPU-only lane. PPO was rejected after green bring-up because held-out utility was noncompetitive. DQN was then evaluated using training seed 41, 8,192 bounded timesteps, and unseen acceptance seeds 101/103/107/109/113. On that fixed synthetic set, DQN mean reward was 12.972, deterministic heuristic mean reward was 12.56, and CP-SAT mean reward was 12.972. The learned candidate produced zero constraint violations, zero authorization, zero external actions, and zero saved policy. These results are reproducible engineering regression evidence on the public synthetic fixture, not production-performance or general-intelligence claims.

The learned-proposal adapter remains project-owned and fail-closed: predictor exceptions, malformed outputs, and prohibited proposals fall back to no-op. Learned output is a recommendation only and cannot grant authorization.

## Exact CPU runtime evidence

Exact-head runtime audit run `35163099959` downloaded `torch-2.14.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl` from the official PyTorch CPU index and measured SHA-256 `160e1bc46aeded3111d2801f8ae10dc9a1b946843a7e126b4dbf5e19c5706e95`, size 196,253,940 bytes. `pip check` reported no broken requirements.

The isolated transitive set is pinned in `requirements-s3-runtime.txt`. The audit enumerated 12 native objects inside the installed Torch package and recorded each path, size, and SHA-256 in `provenance/s3-rl-review.json`. CUDA remained unavailable. This completes the S3 candidate artifact/runtime inventory, not release-native-bundle approval.

## Execution-quality note

The first runtime-provenance increment failed publication screening because the new root-level requirements manifest had not been added to the scanner's explicit root allowlist. The failure was deterministic and was not rerun unchanged. The scanner was corrected narrowly, with regressions proving the reviewed manifest is allowed while unknown root files remain blocked. The corrected exact head passed publication screening and all three applicable workflows.

## Release boundary

All state, rewards, actions, seeds, and evaluation fixtures in this repository are synthetic and generic. Product-specific reward design, policies, real topology/data, trained production weights, credentials, and platform integration adapters remain outside this repository.

Release-level native-bundle notices, full dependency SBOM, vulnerability review, target-platform evidence, rollback/fail-safe integration evidence, and owner release approval remain separate gates. Commercial distribution remains false.
