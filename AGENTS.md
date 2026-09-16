# Working rules

## Scope and authority

This repository contains only generic experiment infrastructure and synthetic
fixtures. Do not identify downstream products, customers, deployments, business
use cases, protected vocabulary, or private repository names anywhere in public
source, issues, PRs, commits, logs, branches, discussions, or artifacts.

No private checkout, secret, endpoint, trained artifact, media, production event,
real topology, policy bundle, reward design, or protected adapter may enter this
workspace. An ignored path is not a confidentiality boundary. Automated
checks are only defense in depth, not a secrecy guarantee. Do not publish
protected vocabulary or hashes of protected vocabulary.

Only the repository owner may authorize changes to visibility, licensing,
permissions, external integrations, production authority, or protected material.
Do not modify other repositories or merge into their default branches.

## Donor first

Before implementing an algorithm, document the strongest fitting maintained
permissive donor and a measured baseline. Prefer imports/adapters to forks or
copied internals. Check exact code, dependency graph, wheel-native libraries,
model weights, training data, and any use restrictions independently.

MIT, BSD, and Apache are preferred starting points, not blanket release
approval. Unknown/no-license, noncommercial, research-only, or incompatible
reciprocal obligations fail closed. Runtime exceptions require explicit review.
Record versions, source references, artifact hashes, notices, evaluation
receipts, known vulnerabilities, and distribution approval separately.

Never load an untrusted pickle/model or execute remote model code. Do not fetch
pretrained weights automatically. No public-web accessibility implies data-use
permission. Use synthetic data here.

## Sprint discipline

Work one accepted task at a time on one branch. Start with a failing regression
or explicit acceptance test. Do not begin downstream work while the precursor
is red. No retries without a diagnosis and bounded retry budget (one retry for
confirmed infrastructure faults only). Stop scope expansion on regression.

Every change needs public-boundary review, negative-path tests, deterministic
replay, dependency impact, resource limits, and exact result reporting.
Do not claim training, integration, CI success, or deployment from file presence.
No automatic default-branch merges, issue bulk closure, or protection changes.

## Bounded experiments

Use synthetic fixtures, fixed seeds, immutable evaluation splits, baseline
comparisons, runtime budgets, and aggregate-only output. Select a model using
validation, not the final test split. Report failures and abstentions as well
as successful predictions. Outputs are scores until calibration is established.

Proposals never grant execution authority. Keep deterministic constraints
separate from learned scores. Unknown, stale, cross-partition, nonfinite,
unsupported-version, or untraceable inputs must fail closed. No live exploration.

## CI

Public checks use disposable hosted runners, read-only repository permissions,
no secrets, and no private downloads. Never use a privileged pull-request
trigger or a self-hosted runner for untrusted public code. Never upload training
artifacts. Run `python tools/check_public.py` before staging and publishing.

This file is an operating contract, not a running agent or scheduler. Report an
agent as active only after an actual execution system and run are verified.
