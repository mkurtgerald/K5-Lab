# S4 bounded memory and generic correlation

Status: public S4 candidate. Synthetic and domain-neutral only.

`BoundedEventMemory` is a project-owned, standard-library in-memory baseline. No database, vector store, graph store, remote service, filesystem persistence, model runtime, or new donor dependency is introduced. A third-party storage donor will be considered only if measured requirements justify the additional dependency/native/license surface.

The event contract uses only opaque bounded tokens plus timezone-aware timestamps, confidence/abstention state, and explicit parent event identifiers. Events are immutable. Reusing an event identifier with different content fails closed. Parent references must be resident in the same partition when a derived event is appended.

Memory is isolated by partition and bounded by partition count, per-partition event count, and event-time age. A per-partition high-water mark makes time eviction deterministic even when events arrive out of order. An event older than the active retention boundary is rejected before mutation. A late event that would immediately fall outside the configured count bound is also rejected rather than being accepted and silently discarded.

Eviction preserves resident provenance integrity: when an event is removed by age or count, any resident descendants whose explicit parent chain depends on it are removed deterministically as well. A new derived event is rejected before mutation when the configured count boundary would immediately evict one of its required parents. This avoids leaving resident derived events with dangling parent references.

Queries are explicitly time-bounded, count-bounded, and optionally filtered by opaque entity/type keys. Generic correlation accepts only an explicit bounded tuple of resident event IDs, requires a shared opaque grouping key and bounded event-time span, and returns a deterministic provenance receipt. Correlation attempts involving an expired/evicted event fail closed. Correlation receipts are permanently non-authorizing and record zero external actions. No downstream feature semantics, ontology extension, operational policy, or response logic exists in this public layer.

The synthetic benchmark reports insert/query/correlation p50/p95 latency plus Python-side peak allocation. It also reports Python allocation observations at multiple configured event-count bounds so resource growth remains visible rather than inferred from a single fixture. These measurements are regression evidence only; `tracemalloc` does not establish native/process memory qualification and the fixture is not a production-scale claim.

Private K5/EdgeVMS ontology extensions, feature/correlation semantics, response policy, real sensor data/topology, credentials, production weights and platform adapters remain outside this repository. Commercial distribution remains subject to later release gates and explicit owner approval.
