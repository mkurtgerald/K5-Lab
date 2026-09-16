# S3 generic simulation candidate

Status: environment/baseline evaluation only. No learned policy, external action, deployment authority, or commercial-distribution approval is created by this stage.

## First donor boundary

Gymnasium 1.3.0 is the selected environment-interface donor for the first S3 increment. Upstream tag `v1.3.0` resolves to commit `53bf3e9a884783eb72ad3fc8b15780914c97c3e1`. The tagged project metadata declares MIT, Python >=3.10, and base dependencies on NumPy, cloudpickle, typing-extensions, and Farama-Notifications. No optional environment families or Torch extras are enabled.

The reviewed PyPI wheel is `gymnasium-1.3.0-py3-none-any.whl`, SHA-256 `6b8c159a8540dcbcb221722d7efda24d78ebbcbc3bd2ea1c2611aa2a34471fc2`. PyPI records that artifact as uploaded on 2026-04-22 without Trusted Publishing. The dependency candidate pins cloudpickle 3.1.2 (BSD-3-Clause; wheel SHA-256 `9acb47f6afd73f60dc1df93bb801b472f05ff42fa6c84167d25cb206be1fbf4a`) and Farama-Notifications 0.0.6 (MIT; wheel SHA-256 `f84839188efa1ce5bb361c2a84881b2dc2c0d0d7fb661ff00421820170930935`). Existing NumPy 2.3.5 and typing-extensions 4.16.0 pins satisfy the other base requirements.

Cloudpickle is present only because Gymnasium requires it. This project does not call cloudpickle/pickle serialization or load serialized Python objects in the S3 environment path.

## Environment contract

`BoundedProposalEnv` exposes a fixed five-value float observation and three discrete proposals. The two utility values and two permission flags are opaque synthetic quantities; the fifth value is bounded episode phase. Action 0 is a safe no-op. Proposals 1 and 2 may be prohibited by the current synthetic permission flags. Project-owned filtering converts a prohibited proposal to no-op, records a constraint violation, returns a synthetic penalty, and never marks the proposal authorized.

Invalid action encodings, malformed/non-finite observations, unsupported versions, unsupported reset options, out-of-range horizons, and post-truncation stepping fail closed. Reset with a fixed seed is reproducible. The environment exposes no network/resource locator, plugin/model selector, credential, platform adapter, or external executor.

## Baselines before learning

The first increment contains three fixed baselines only: no-op, a deterministic heuristic, and a bounded single-worker CP-SAT proposal selector. CP-SAT uses the already accepted OR-Tools donor and can select only currently permitted actions. Fixed-seed aggregate evidence reports reward/utility, constraint violations and decision latency. The benchmark performs no training and saves no policy.

Stable-Baselines3 2.9.0 is deliberately deferred until this environment and baseline precursor is green. Its MIT source license is permissive, but its PyTorch dependency materially expands binary, supply-chain, memory and compute review. S3 will evaluate an isolated CPU-only SB3/PyTorch lane only after exact artifact/native/license review and a bounded training plan. No GPU or paid compute is authorized by this stage.

## Release boundary

These synthetic results are engineering evidence only. The generic public reward/constraint fixture is not a downstream deployment objective. Product-specific reward design, policy, real topology/data, trained production weights, and integration adapters remain outside this repository. Release-level SBOM/notices/vulnerability/platform/release-bundle review remains separate and commercial distribution remains false.
