from datetime import datetime, timezone
import unittest

from rdflib import BNode, Graph, Literal, RDF, URIRef, XSD

from mosaic_lab.contracts import Record
from mosaic_lab.graph import RecordGraph, VOCAB
from mosaic_lab.shape_validation import HARD_MAX_TRIPLES, validate_graph, validate_record_graph

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def record(record_id="r1", *, kind="observed", parents=()):
    return Record("p1", record_id, "s1", NOW, 0.9, kind=kind, parents=parents)


def graph_with_one() -> tuple[RecordGraph, Graph]:
    records = RecordGraph("p1")
    records.add(record())
    graph = Graph()
    for triple in records.triples():
        graph.add(triple)
    return records, graph


class ShapeValidationTests(unittest.TestCase):
    def test_valid_record_graph_conforms(self):
        records, _ = graph_with_one()
        receipt = validate_record_graph(records)
        self.assertTrue(receipt.conforms)
        self.assertEqual(receipt.violations, 0)
        self.assertEqual(receipt.checked_triples, 5)

    def test_missing_required_property_is_reported(self):
        _, graph = graph_with_one()
        subject = next(graph.subjects(RDF.type, VOCAB.Record))
        graph.remove((subject, VOCAB.source, None))
        receipt = validate_graph(graph, partition="p1")
        self.assertFalse(receipt.conforms)
        self.assertGreaterEqual(receipt.violations, 1)

    def test_missing_type_is_reported(self):
        _, graph = graph_with_one()
        subject = next(graph.subjects(RDF.type, VOCAB.Record))
        graph.remove((subject, RDF.type, VOCAB.Record))
        receipt = validate_graph(graph, partition="p1")
        self.assertFalse(receipt.conforms)

    def test_invalid_score_is_reported(self):
        _, graph = graph_with_one()
        subject = next(graph.subjects(RDF.type, VOCAB.Record))
        graph.set((subject, VOCAB.score, Literal(2.0, datatype=XSD.double)))
        receipt = validate_graph(graph, partition="p1")
        self.assertFalse(receipt.conforms)

    def test_unresolved_reference_fails_before_donor(self):
        _, graph = graph_with_one()
        subject = next(graph.subjects(RDF.type, VOCAB.Record))
        graph.add((subject, VOCAB.derivedFrom, URIRef("urn:mosaic:p1:missing")))
        with self.assertRaisesRegex(ValueError, "unresolved reference"):
            validate_graph(graph, partition="p1")

    def test_partition_escape_is_rejected(self):
        graph = Graph()
        subject = URIRef("urn:mosaic:p2:r1")
        graph.add((subject, RDF.type, VOCAB.Record))
        with self.assertRaisesRegex(ValueError, "partition"):
            validate_graph(graph, partition="p1")

    def test_remote_or_path_input_is_never_parsed(self):
        for value in ("https://example.invalid/data.ttl", "file:///tmp/data.ttl", "data.ttl"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                validate_graph(value, partition="p1")

    def test_http_subject_is_rejected_without_network_access(self):
        graph = Graph()
        graph.add((URIRef("https://example.invalid/r1"), RDF.type, VOCAB.Record))
        with self.assertRaisesRegex(ValueError, "partition"):
            validate_graph(graph, partition="p1")

    def test_unknown_predicate_is_rejected(self):
        _, graph = graph_with_one()
        subject = next(graph.subjects(RDF.type, VOCAB.Record))
        graph.add((subject, URIRef("urn:mosaic:generic:unknown"), Literal("x")))
        with self.assertRaisesRegex(ValueError, "predicate"):
            validate_graph(graph, partition="p1")

    def test_blank_node_data_is_rejected(self):
        graph = Graph()
        graph.add((BNode(), RDF.type, VOCAB.Record))
        with self.assertRaisesRegex(ValueError, "subject"):
            validate_graph(graph, partition="p1")

    def test_graph_limit_is_enforced(self):
        _, graph = graph_with_one()
        with self.assertRaisesRegex(ValueError, "exceeds validation limit"):
            validate_graph(graph, partition="p1", max_triples=4)
        with self.assertRaisesRegex(ValueError, "hard limit"):
            validate_graph(graph, partition="p1", max_triples=HARD_MAX_TRIPLES + 1)

    def test_invalid_limits_fail_closed(self):
        _, graph = graph_with_one()
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_graph(graph, partition="p1", max_triples=value)

    def test_deterministic_replay(self):
        records, _ = graph_with_one()
        self.assertEqual(validate_record_graph(records), validate_record_graph(records))

    def test_provenance_reference_conforms_when_resolved(self):
        records = RecordGraph("p1")
        records.add(record())
        records.add(record("r2", kind="inferred", parents=("r1",)))
        self.assertTrue(validate_record_graph(records).conforms)


if __name__ == "__main__":
    unittest.main()
