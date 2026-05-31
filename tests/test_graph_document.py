"""
Тесты GraphDocument — редактируемой модели холста (headless, без Qt).

Покрывают мутации (узлы/рёбра), правила «один провод на вход», обрезку
висячих рёбер при изменении динамических портов, round-trip через GraphSpec
(включая сохранение позиций в meta.layout) и совместимость с движком.
"""

from __future__ import annotations
import unittest

from core.graph import GraphDocument, GraphExecutor, GraphValidationError
from exercises.graph.generators import EXAMPLE_GRAPH


class NodeMutationTests(unittest.TestCase):
    def test_add_and_unique_ids(self):
        doc = GraphDocument()
        a = doc.add_node("random_natural", {"min": 1, "max": 5}, 10, 20)
        b = doc.add_node("random_natural", {"min": 1, "max": 5})
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(a.x, 10)
        self.assertEqual(len(doc.nodes), 2)

    def test_unknown_type_rejected(self):
        doc = GraphDocument()
        with self.assertRaises(GraphValidationError):
            doc.add_node("nope")

    def test_remove_node_drops_its_edges(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="c")
        doc.add_node("var_dict", {"names": ["x"]}, node_id="vd")
        doc.add_edge("c", "out", "vd", "x")
        doc.remove_node("c")
        self.assertEqual(doc.edges, [])
        self.assertNotIn("c", doc.nodes)


class EdgeMutationTests(unittest.TestCase):
    def test_one_wire_per_input(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="a")
        doc.add_node("constant_number", {"value": 2}, node_id="b")
        doc.add_node("var_dict", {"names": ["x"]}, node_id="vd")
        doc.add_edge("a", "out", "vd", "x")
        doc.add_edge("b", "out", "vd", "x")   # должен вытеснить первый
        self.assertEqual(len(doc.edges), 1)
        self.assertEqual(doc.edges[0].from_node, "b")

    def test_prune_invalid_after_param_change(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 1}, node_id="a")
        doc.add_node("var_dict", {"names": ["x", "y"]}, node_id="vd")
        doc.add_edge("a", "out", "vd", "y")
        # Убираем порт y из var_dict — ребро становится висячим.
        doc.set_params("vd", {"names": ["x"]})
        doc.prune_invalid_edges()
        self.assertEqual(doc.edges, [])

    def test_dynamic_ports_reflect_params(self):
        doc = GraphDocument()
        doc.add_node("var_dict", {"names": ["a", "b", "c"]}, node_id="vd")
        ins, outs = doc.ports("vd")
        self.assertEqual([p.name for p in ins], ["a", "b", "c"])
        self.assertEqual([p.name for p in outs], ["out"])


class RoundTripTests(unittest.TestCase):
    def test_layout_survives_roundtrip(self):
        doc = GraphDocument()
        doc.add_node("constant_number", {"value": 7}, x=123, y=456, node_id="c")
        data = doc.to_spec_dict()
        self.assertEqual(data["meta"]["layout"]["c"], [123, 456])

        doc2 = GraphDocument.from_spec_dict(data)
        self.assertEqual(doc2.nodes["c"].x, 123)
        self.assertEqual(doc2.nodes["c"].y, 456)
        self.assertEqual(doc2.nodes["c"].params["value"], 7)

    def test_import_example_graph_assigns_positions(self):
        # EXAMPLE_GRAPH не содержит layout — позиции должны проставиться сеткой.
        doc = GraphDocument.from_spec_dict(EXAMPLE_GRAPH)
        self.assertEqual(len(doc.nodes), len(EXAMPLE_GRAPH["nodes"]))
        self.assertEqual(len(doc.edges), len(EXAMPLE_GRAPH["edges"]))
        # координаты не все нулевые
        self.assertTrue(any(n.x or n.y for n in doc.nodes.values()))

    def test_document_spec_executes(self):
        doc = GraphDocument.from_spec_dict(EXAMPLE_GRAPH)
        # Граф из документа должен собираться движком без ошибок.
        GraphExecutor(doc.to_spec())
        self.assertTrue(doc.has_task_sink())

    def test_meta_layout_ignored_by_engine(self):
        # Наличие layout в meta не мешает исполнению. Граф без узлов-блоков,
        # чтобы тест оставался headless (text_block тянет Qt при compute).
        doc = GraphDocument()
        doc.add_node("random_natural", {"min": 1, "max": 5}, x=10, y=10, node_id="v")
        doc.add_node("var_dict", {"names": ["v"]}, x=200, y=10, node_id="vd")
        doc.add_node("formula", {"expr": "v * 2"}, x=400, y=10, node_id="f")
        doc.add_edge("v", "out", "vd", "v")
        doc.add_edge("vd", "out", "f", "vars")
        self.assertIn("layout", doc.to_spec_dict()["meta"])
        out = GraphExecutor(doc.to_spec()).run_full()
        self.assertEqual(out["f"]["out"], out["vd"]["out"]["v"] * 2)


if __name__ == "__main__":
    unittest.main()
