"""Bounded in-memory SHACL validation for generic record graphs.

The adapter deliberately accepts RDFLib Graph objects only. It never parses a path,
URL, SPARQL endpoint, ontology import, JavaScript rule, or remote graph.
"""
from __future__ import annotations

from dataclasses import dataclass

from rdflib import BNode, Graph, Literal, Namespace, RDF, URIRef, XSD
from pyshacl import validate

from .contracts import token
from .graph import RecordGraph, VOCAB

SH = Namespace("http://www.w3.org/ns/shacl#")
HARD_MAX_TRIPLES = 50_000
_ALLOWED_PREDICATES = frozenset(
    {RDF.type, VOCAB.kind, VOCAB.source, VOCAB.time, VOCAB.score, VOCAB.derivedFrom}
)


@dataclass(frozen=True)
class ValidationReceipt:
    conforms: bool
    violations: int
    checked_triples: int
    validator: str = "pyshacl-0.40.1"


def _record_shapes() -> Graph:
    graph = Graph()
    shape = URIRef("urn:mosaic:shape:record-v1")
    graph.add((shape, RDF.type, SH.NodeShape))
    graph.add((shape, SH.targetClass, VOCAB.Record))
    for predicate in (VOCAB.kind, VOCAB.source, VOCAB.time, VOCAB.score, VOCAB.derivedFrom):
        graph.add((shape, SH.targetSubjectsOf, predicate))

    def prop(path: URIRef, *, min_count: int | None = None, max_count: int | None = None,
             datatype: URIRef | None = None, has_value: URIRef | None = None,
             node_kind: URIRef | None = None, minimum: float | None = None,
             maximum: float | None = None) -> None:
        node = BNode()
        graph.add((shape, SH.property, node))
        graph.add((node, SH.path, path))
        if min_count is not None:
            graph.add((node, SH.minCount, Literal(min_count)))
        if max_count is not None:
            graph.add((node, SH.maxCount, Literal(max_count)))
        if datatype is not None:
            graph.add((node, SH.datatype, datatype))
        if has_value is not None:
            graph.add((node, SH.hasValue, has_value))
        if node_kind is not None:
            graph.add((node, SH.nodeKind, node_kind))
        if minimum is not None:
            graph.add((node, SH.minInclusive, Literal(minimum, datatype=XSD.double)))
        if maximum is not None:
            graph.add((node, SH.maxInclusive, Literal(maximum, datatype=XSD.double)))

    prop(RDF.type, min_count=1, max_count=1, has_value=VOCAB.Record)
    prop(VOCAB.kind, min_count=1, max_count=1)
    prop(VOCAB.source, min_count=1, max_count=1)
    prop(VOCAB.time, min_count=1, max_count=1, datatype=XSD.dateTime)
    prop(VOCAB.score, min_count=1, max_count=1, datatype=XSD.double, minimum=0.0, maximum=1.0)
    prop(VOCAB.derivedFrom, node_kind=SH.IRI)
    return graph


_SHAPES = _record_shapes()


def _bounded_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("max_triples must be a positive integer")
    if value > HARD_MAX_TRIPLES:
        raise ValueError("max_triples exceeds hard limit")
    return value


def _copy_and_check(graph: Graph, partition: str, max_triples: int) -> Graph:
    if not isinstance(graph, Graph):
        raise TypeError("an in-memory RDFLib Graph is required")
    partition = token(partition)
    max_triples = _bounded_limit(max_triples)
    if len(graph) > max_triples:
        raise ValueError("graph exceeds validation limit")

    prefix = f"urn:mosaic:{partition}:"
    local_subjects: set[URIRef] = set()
    copied = Graph()
    for subject, predicate, obj in graph:
        if isinstance(subject, BNode) or not isinstance(subject, URIRef) or not str(subject).startswith(prefix):
            raise ValueError("subject outside partition boundary")
        if predicate not in _ALLOWED_PREDICATES:
            raise ValueError("unsupported predicate")
        if isinstance(obj, BNode):
            raise ValueError("blank nodes are not accepted in data graphs")
        if isinstance(obj, URIRef):
            if predicate == RDF.type:
                if obj != VOCAB.Record:
                    raise ValueError("unsupported record type")
            elif predicate == VOCAB.derivedFrom:
                if not str(obj).startswith(prefix):
                    raise ValueError("reference outside partition boundary")
            else:
                raise ValueError("unexpected IRI object")
        local_subjects.add(subject)
        copied.add((subject, predicate, obj))

    for obj in copied.objects(None, VOCAB.derivedFrom):
        if obj not in local_subjects:
            raise ValueError("unresolved reference")
    return copied


def validate_graph(graph: Graph, *, partition: str, max_triples: int = HARD_MAX_TRIPLES) -> ValidationReceipt:
    """Validate one bounded in-memory graph without enabling remote or active features."""
    safe_graph = _copy_and_check(graph, partition, max_triples)
    conforms, result_graph, _ = validate(
        data_graph=safe_graph,
        shacl_graph=_SHAPES,
        ont_graph=None,
        inference="none",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
        meta_shacl=False,
        advanced=False,
        js=False,
        debug=False,
        do_owl_imports=False,
    )
    if not isinstance(result_graph, Graph):
        raise RuntimeError("validator did not return a report graph")
    violations = len(set(result_graph.subjects(RDF.type, SH.ValidationResult)))
    return ValidationReceipt(bool(conforms), violations, len(safe_graph))


def validate_record_graph(record_graph: RecordGraph, *, max_triples: int = HARD_MAX_TRIPLES) -> ValidationReceipt:
    """Validate a RecordGraph snapshot; the donor never receives the mutable store."""
    if not isinstance(record_graph, RecordGraph):
        raise TypeError("RecordGraph required")
    snapshot = Graph()
    for triple in record_graph.triples():
        snapshot.add(triple)
    return validate_graph(snapshot, partition=record_graph.partition, max_triples=max_triples)
