# K5 Lab

Experimental utilities and reproducible benchmarks.

An isolated evaluation scaffold with strict records, graph checks, synthetic
fixtures, baseline training, and non-executing proposal validation. This is not
an integration package or a production runtime.

## Run locally

Python 3.12 or 3.13 is the intended baseline. Use a dedicated virtual environment.

```sh
python -m venv .venv
# Activate .venv using the command appropriate to your operating system.
python -m pip install -r requirements-core.txt
python tools/check_public.py
python tools/run_tests.py
python tools/run_benchmark.py
```

The optional neural comparison requires the separately pinned dependency in
`requirements-neural.txt`. Install an appropriate CPU build from the upstream
project's documented package index before running:

```sh
python tools/run_benchmark.py --neural
```

Benchmarks create synthetic values in memory. They print aggregate JSON only;
no weights, input records, remote resources, or external telemetry are saved.
Scores are demonstrations, not production qualification.

## Boundaries

Only generic, synthetic, publication-approved material belongs here. No external
services are contacted by the library or benchmark. Proposals cannot execute.
Third-party engines remain replaceable behind project-owned interfaces.
See `AGENTS.md`, `docs/PUBLIC_BOUNDARY.md`, and `docs/SPRINTS.md`.

## License

Original material is proprietary and source-visible, not open source. See
`LICENSE`. Third-party components retain their own licenses and notices; see
`THIRD_PARTY.md`. The source-visible notice does not make public material secret.
