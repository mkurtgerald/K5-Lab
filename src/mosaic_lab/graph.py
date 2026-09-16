"""Partition-isolated RDFLib adapter; no file, URL, SPARQL, or remote parsing."""
from datetime import datetime
from rdflib import Graph, Literal, Namespace, RDF, URIRef, XSD
from .contracts import Record, token, utc

VOCAB = Namespace("urn:mosaic:generic:")


class RecordGraph:
    def __init__(self, partition: str, *, capacity: int = 10000):
        token(partition)
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        self.partition = partition
        self.capacity = capacity
        self._records: dict[str, Record] = {}
        self._graph = Graph()

    def _uri(self, value: str) -> URIRef:
        return URIRef(f"urn:mosaic:{self.partition}:{token(value)}")

    def add(self, record: Record) -> bool:
        if record.partition != self.partition:
            raise ValueError("partition mismatch")
        prior = self._records.get(record.record_id)
        if prior is not None:
            if prior != record:
                raise ValueError("conflicting replay")
            return False
        if len(self._records) >= self.capacity:
            raise ValueError("capacity reached")
        for parent_id in record.parents:
            parent = self._records.get(parent_id)
            if parent is None:
                raise ValueError("unresolved provenance")
            if utc(parent.observed_at) > utc(record.observed_at):
                raise ValueError("provenance occurs after inference")
        subject = self._uri(record.record_id)
        self._graph.add((subject, RDF.type, VOCAB.Record))
        self._graph.add((subject, VOCAB.kind, Literal(record.kind)))
        self._graph.add((subject, VOCAB.source, Literal(record.source_id)))
        self._graph.add((subject, VOCAB.time, Literal(utc(record.observed_at), datatype=XSD.dateTime)))
        self._graph.add((subject, VOCAB.score, Literal(float(record.score), datatype=XSD.double)))
        for parent in record.parents:
            self._graph.add((subject, VOCAB.derivedFrom, self._uri(parent)))
        self._records[record.record_id] = record
        return True

    def get(self, record_id: str) -> Record | None:
        return self._records.get(token(record_id))

    def triples(self) -> tuple:
        return tuple(self._graph)

    def __len__(self) -> int:
        return len(self._records)
