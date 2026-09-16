# S1 constrained-allocation receipt

Review date: 2026-09-16.

This stage evaluates OR-Tools CP-SAT through a narrow project-owned adapter. The
public fixture is synthetic and domain-neutral. It models bounded integer demand,
value, deadline slots, and resource capacity. The adapter exposes no caller-selectable solver, plugin path, arbitrary objective
expression, external command, network call, or effect boundary.

## Selected candidate

- OR-Tools 9.15.6755 — Apache-2.0; CPython 3.13 Linux x86-64 PyPI wheel
  SHA-256 `ebd5aea00374e3aad7a78de59058aca5e871a26a3c385cd0860ef1d685d03c9a`.
- absl-py 2.5.0 — Apache-2.0; wheel SHA-256
  `0f17b89f2a4eaaedc4f28c622998aa690564b3012a396a4ffad0821007fe03ba`.
- immutabledict 4.3.1 — MIT; wheel SHA-256
  `c9facdc0ff30fdb8e35bd16532026cac472a549e182c94fa201b51b25e4bf7bf`.
- pandas 2.3.3 — BSD-3-Clause; CPython 3.13 Linux x86-64 wheel SHA-256
  `318d77e0e42a628c04dc56bcef4b40de67918f7041c2b061af1da41dcff670ac`.
- protobuf 6.33.6 — BSD-3-Clause; pure-Python wheel SHA-256
  `77179e006c476e69bf8e8ce866640091ec42e1beb80b213c3900006ecfba6901`.
- typing-extensions 4.16.0 — PSF-2.0; wheel SHA-256
  `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8`.
- python-dateutil 2.9.0.post0 — BSD-3-Clause / Apache-2.0 contribution mix;
  wheel SHA-256 `a8b2bc7bffae282281c8140a97d3aa9c14da0b136dfe83f850eea9a5f7470427`.
- pytz 2026.3.post1 — MIT; wheel SHA-256
  `dd95840dd199baea12d9cc096a1d452caa6596a1c1e4b5f3dbd1541855d5e815`.
- tzdata 2025.3 — Apache-2.0; wheel SHA-256
  `06a47e5700f3081aab02b2e513160914ff0694bce9947d6b76ebd6bf57cfc5d1`.
- six 1.17.0 — MIT; wheel SHA-256
  `4721f391ed90541fddacab5acf947aa0d3dc7d27b2e1e8eda2be8970586c3274`.

The OR-Tools wheel is a native binary distribution and contains or links project
components beyond the Python CP-SAT API. Exact package versions are pinned here,
but this experiment does not approve the native bundle for redistribution. The
actual release bundle still requires SBOM/native-library inventory, notices,
vulnerability review, and platform-specific verification. No external solver is
selected or invoked by this adapter.

## Determinism and bounds

CP-SAT runs with one search worker, a fixed seed, and a caller limit capped at
five seconds. Public contracts cap a problem at 128 tasks and 32 resources and
restrict numeric fields to bounded non-negative integers. The objective is fixed
to maximizing aggregate integer value. Unknown objectives, malformed fields,
duplicate identifiers, unsupported versions, oversized problems, and invalid
time limits fail closed before solving.

A deterministic greedy baseline is retained for comparison. The synthetic
benchmark repeats the same immutable fixture, reports only aggregate objective
and p95 latency, and verifies assignment/objective replay. Tests cover feasible
and infeasible required work, deadline exclusion, capacity failure, optional
unallocated work, deterministic replay, invalid objective, invalid limits,
duplicate identifiers, and problem-size bounds.

## Approval state

This is donor evaluation and bounded simulation only. It grants no execution
authority, does not establish optimality for arbitrary workloads, and is not
commercial-distribution approval. Measured hosted-CI results must be recorded on
the exact revision before S1 can be accepted.
