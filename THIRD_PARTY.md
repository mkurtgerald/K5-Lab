# Third-party provenance

Dependencies are referenced, not vendored. Their original terms remain in force.
Original glue code's notice does not override a donor license. Upstream labels
are preliminary screening only; review exact distribution contents independently.

## Upstream references (checked 2026-09-16)

- RDFLib: https://github.com/RDFLib/rdflib/blob/main/LICENSE
- scikit-learn: https://github.com/scikit-learn/scikit-learn/blob/main/COPYING
- PyTorch: https://github.com/pytorch/pytorch/blob/main/LICENSE
- PyTorch packaged license expression: https://github.com/pytorch/pytorch/blob/main/pyproject.toml
- pySHACL: https://github.com/RDFLib/pySHACL
- OR-Tools: https://github.com/google/or-tools
- River: https://github.com/online-ml/river
- Gymnasium: https://github.com/Farama-Foundation/Gymnasium/blob/main/LICENSE
- Stable-Baselines3: https://github.com/DLR-RM/stable-baselines3
- Ray: https://github.com/ray-project/ray
- Open Policy Agent: https://github.com/open-policy-agent/opa/blob/main/LICENSE

## Required release review

`provenance/components.json` separates installed version evidence, candidate
selection, and commercial-distribution approval. Exact requirements are not
cryptographic locks. Downloaded wheel/source archives need SHA-256, provenance,
reviewed notices, dependency SBOM, native-library inventory, known-vulnerability
review, and platform-specific tests before distribution.

A metadata hash is only evidence of inspected installed metadata, not an
upstream artifact hash, authenticity proof, or a reviewed wheel. Do not replace
a missing release artifact digest with it. No release is approved here.

NumPy/SciPy/PyTorch binaries may contain libraries with terms beyond their
project-level license. Preserve notices and assess any exception/redistribution
conditions for the actual build. No blanket approval of binary contents.

Weights, datasets, hosted APIs, and model-code execution require separate
rights/security reviews even when a framework's source license is permissive.
