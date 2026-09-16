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
- Narwhals: https://github.com/narwhals-dev/narwhals
- Gymnasium: https://github.com/Farama-Foundation/Gymnasium/blob/main/LICENSE
- cloudpickle: https://github.com/cloudpipe/cloudpickle
- Farama-Notifications: https://github.com/Farama-Foundation/Farama-Notifications
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

## S1 allocation chain

The constrained-allocation candidate pins OR-Tools 9.15.6755 and its Python
runtime dependency chain. Project-level terms reviewed for the pinned chain are:
OR-Tools Apache-2.0; absl-py Apache-2.0; immutabledict MIT; pandas BSD-3-Clause;
protobuf BSD-3-Clause; typing-extensions PSF-2.0; python-dateutil BSD/Apache;
pytz MIT; tzdata Apache-2.0; and six MIT. Exact versions and selected wheel
digests are recorded in `docs/S1_ALLOCATION.md` and `provenance/s1-allocation.json`.
The OR-Tools and pandas wheels contain native code. Project-level terms do not
replace actual bundle/native-library review. Only the CP-SAT Python API is called;
no external solver selection is exposed.

## S2 streaming chain

The streaming-learning candidate pins River 0.26.1 and Narwhals 2.26.0. River's
tagged project metadata declares BSD-3-Clause and core dependencies on SciPy,
NumPy, and Narwhals. Narwhals is MIT. River is built with Maturin and includes a
Rust extension, so project-level license screening is not a native bundle review.
The public adapter exposes only a fixed learner/detector boundary and synthetic
fixtures. Exact downloaded artifact digest, native-library inventory, notices,
SBOM, vulnerability review, and platform evidence remain required before any
commercial redistribution approval.

## S3 simulation and learned-proposal chain

The simulation layer pins Gymnasium 1.3.0 (MIT), cloudpickle 3.1.2
(BSD-3-Clause), and Farama-Notifications 0.0.6 (MIT), while reusing the existing
NumPy and typing-extensions pins. No optional Gymnasium extras are enabled.
Cloudpickle is an upstream base dependency but project code does not call its
serialization/loading APIs.

The isolated learned-proposal candidate pins Stable-Baselines3 2.9.0 (MIT) and
PyTorch 2.14.0+cpu. Exact runtime evidence uses the CPython 3.13 Linux CPU wheel
`torch-2.14.0+cpu-cp313-cp313-manylinux_2_28_x86_64.whl`, SHA-256
`160e1bc46aeded3111d2801f8ae10dc9a1b946843a7e126b4dbf5e19c5706e95`.
The observed CPU runtime transitives are filelock 3.32.3 (MIT), fsspec 2026.7.0
(BSD-3-Clause), Jinja2 3.1.6 (BSD-3-Clause), MarkupSafe 3.0.3 (BSD-3-Clause),
mpmath 1.3.0 (New BSD/BSD), NetworkX 3.6.1 (BSD-3-Clause), setuptools 78.1.0
(MIT), SymPy 1.14.0 (BSD), and the existing typing-extensions 4.16.0 pin.

PyTorch's installed metadata declares the composite expression
`Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause AND BSL-1.0 AND MIT`.
The S3 exact-head audit enumerates and hashes the 12 native objects in the
installed Torch package; the detailed inventory is in `provenance/s3-rl-review.json`.
This is candidate provenance evidence only. It does not replace review of bundled
notices, third-party native terms, vulnerabilities, or target-platform packages.

## Required release review

`provenance/components.json` and the stage-specific ledgers separate candidate
selection from commercial-distribution approval. Exact requirements are not
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
