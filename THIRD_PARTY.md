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
- owlrl: https://github.com/RDFLib/OWL-RL
- html5rdf: https://github.com/RDFLib/html5rdf
- prettytable: https://github.com/prettytable/prettytable
- packaging: https://github.com/pypa/packaging
- wcwidth: https://github.com/jquast/wcwidth
- OR-Tools: https://github.com/google/or-tools
- River: https://github.com/online-ml/river
- Gymnasium: https://github.com/Farama-Foundation/Gymnasium/blob/main/LICENSE
- Stable-Baselines3: https://github.com/DLR-RM/stable-baselines3
- Ray: https://github.com/ray-project/ray
- Open Policy Agent: https://github.com/open-policy-agent/opa/blob/main/LICENSE

## S1 validation chain

The graph-validation candidate pins pySHACL 0.40.1 and its Python runtime chain.
pySHACL is Apache-2.0. owlrl 7.6.2 is published under the W3C Software Notice and
License. RDFLib is BSD-3-Clause, html5rdf and wcwidth are MIT, prettytable is
BSD-3-Clause, and packaging is dual Apache-2.0/BSD-2-Clause. Exact PyPI wheel
hashes reviewed for this candidate are recorded in `docs/S1_GRAPH_VALIDATION.md`
and `provenance/components.json`. Optional donor extras are not enabled.

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
