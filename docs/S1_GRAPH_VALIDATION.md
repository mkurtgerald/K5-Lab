# S1 graph-validation receipt

Review date: 2026-09-16.

This stage evaluates a narrow in-memory SHACL validator behind a project-owned
adapter. The adapter accepts only RDFLib `Graph` objects or snapshots from the
local generic record store. Paths, URLs, remote stores, SPARQL endpoints,
ontology imports, JavaScript, advanced SHACL features, and inference are not
accepted or enabled.

## Candidate dependency set

- pySHACL 0.40.1 — Apache-2.0; PyPI wheel SHA-256
  `27dd58c8ddfa103303b4a8c40b2c666332ffc912dbcd3137f7adc7b7bc5e6bda`.
- owlrl 7.6.2 — W3C Software Notice and License; PyPI wheel SHA-256
  `83347bf7f133979e87b2b18695d51d25510b99cec3f6919b5df05d4fbf058ae0`.
- RDFLib 7.6.0 — BSD-3-Clause; PyPI wheel SHA-256
  `30c0a3ebf4c0e09215f066be7246794b6492e054e782d7ac2a34c9f70a15e0dd`.
- packaging 26.3 — Apache-2.0 OR BSD-2-Clause; PyPI wheel SHA-256
  `d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c`.
- prettytable 3.18.0 — BSD-3-Clause; PyPI wheel SHA-256
  `b3346e0e6f79180833aebaac088ae926340586cf6d7d991b9eb125b65f72313a`.
- wcwidth 0.8.3 — MIT; PyPI wheel SHA-256
  `d5b73dba6158a595ec9370350e7f2637bcac8d6c5e4fde34f30fcffb6103a5e4`.
- html5rdf 1.2.1 — MIT; PyPI wheel SHA-256
  `1f519121bc366af3e485310dc8041d2e86e5173c1a320fac3dc9d2604069b83e`.

Only runtime dependencies needed by the selected Python path are pinned. Optional
HTTP, JavaScript, Oxigraph, server, testing, and documentation extras are excluded.
The upstream validator can accept paths and web URLs and can operate in a remote
mode; those capabilities are intentionally outside this adapter.

## Boundary and failure behavior

The adapter caps each validation at 50,000 triples, copies the accepted graph,
rejects blank-node data, rejects unknown predicates, rejects cross-partition IRIs,
checks that provenance references resolve locally, and passes only the copied
in-memory graph to the donor. SHACL validation runs with inference, imports,
advanced features, and JavaScript disabled. Non-conformance is returned as an
aggregate receipt; donor failures are not converted into successful validation.

Tests cover missing required values, missing type, invalid score, unresolved
references, partition escape, URL/path input, HTTP subjects, unknown predicates,
blank nodes, resource limits, deterministic replay, and resolved provenance.

## Approval state

This is experiment acceptance evidence, not commercial-distribution approval.
The exact dependency tree, notices, source/binary contents, vulnerabilities, and
platform behavior remain release-review gates. In particular, owlrl's W3C license
must be preserved and reviewed with the actual distribution bundle.
