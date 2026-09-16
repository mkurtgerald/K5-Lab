# Delivery sequence

## S0 - Scaffold acceptance

Strict record validation, partition-isolated RDF representation, deterministic
synthetic fixtures, chronological train/validation/test split, ordinary and
optional neural baseline, non-executing proposal gate, negative tests, and
public-boundary scan. A local pass does not equal a remote CI pass.

## S1 - Donor validation

Evaluate pySHACL for generic shape conformance and OR-Tools CP-SAT for a generic
resource-allocation benchmark. Compare against a small deterministic baseline;
measure infeasibility, deadline handling, p95 latency, reproducibility, and
resource usage. Resolve and hash exact artifacts, review native/transitive
licenses and vulnerabilities, and add automated tests before approving use.

## S2 - Learning benchmark

Evaluate River for prequential streaming baselines and drift tests. Compare
against the existing ordinary and neural baselines; include data poisoning,
missing features, distribution shift, rare cases, and abstention. No automatic
online model promotion, real inputs, or external actions.

## S3 - Simulation benchmark

Evaluate Gymnasium plus Stable-Baselines3 in a generic simulated environment.
Compare learned proposals against constrained and deterministic baselines on
unseen seeds. Reward design for protected deployments is out of scope. Require
zero prohibited simulated actions, measured constraint violations, uncertainty,
repeatability, memory/runtime budgets, and documented regression behavior.

## S4 - Packaging

Produce versioned generic interfaces and immutable packages for downstream
owners to evaluate separately. Require license/artifact review, SBOM, known
vulnerability review, publication review, and exact integration receipts.
No downstream source change, dependency insertion, or production promotion is
authorized by completion of a public experiment.

Scale to distributed training only after profiling justifies it. Add an external
policy engine only with an explicit interface, test, and deployment decision.
