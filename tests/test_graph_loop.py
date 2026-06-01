"""
Тесты узлов цикла (repeat + loop_index).

Механика (счётчик, потолок, индекс итерации, поиск свободного выхода тела)
проверяется headless. Полный сбор BLOCK-результатов — под skipUnless(Qt),
т.к. узлы-блоки тянут PyQt6.
"""

from __future__ import annotations
import random
import unittest

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.nodes.loop import LOOP_INDEX_KEY, LoopIndexNode, RepeatNode

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(**extra):
    return ExecContext(rng=random.Random(0), extra=extra)


class RegistryTests(unittest.TestCase):
    def test_loop_nodes_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("repeat"))
        self.assertTrue(DEFAULT_REGISTRY.has("loop_index"))


class LoopIndexTests(unittest.TestCase):
    def test_reads_index_from_context(self):
        n = LoopIndexNode("li", {})
        self.assertEqual(n.compute({}, _ctx(**{LOOP_INDEX_KEY: 4}))["out"], 4.0)

    def test_defaults_to_zero(self):
        self.assertEqual(LoopIndexNode("li", {}).compute({}, _ctx())["out"], 0.0)


class RepeatMechanicsTests(unittest.TestCase):
    def test_count_clamped_to_max_iterations(self):
        n = RepeatNode("r", {"count": 10_000, "max_iterations": 5, "body": {}})
        self.assertEqual(n._count({}), 5)

    def test_count_from_input_overrides_param(self):
        n = RepeatNode("r", {"count": 3, "body": {}})
        self.assertEqual(n._count({"count": 7}), 7)

    def test_negative_count_becomes_zero(self):
        n = RepeatNode("r", {"count": -4, "body": {}})
        self.assertEqual(n._count({}), 0)

    def test_empty_body_yields_empty_list(self):
        # Тело без свободного BLOCK-выхода → итерации идут, но собирать нечего.
        n = RepeatNode("r", {"count": 3, "body": {"nodes": [], "edges": [], "meta": {}}})
        out = n.compute({}, _ctx())
        self.assertEqual(out["out"], [])

    def test_bad_body_type_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            RepeatNode("r", {"body": 123})


class FreeOutputTests(unittest.TestCase):
    def test_free_block_output_detected(self):
        # Тело: loop_index -> var_dict(i) -> formula -> (свободный NUMBER, не BLOCK)
        # Проверяем именно поиск свободного выхода нужного типа.
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "f", "type": "formula", "params": {"expr": "i + 1"}},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "f:vars"},
            ],
        }
        ex = GraphExecutor(GraphSpec.parse(body))
        # свободного BLOCK нет
        self.assertIsNone(ex.free_output_of_type(PortType.BLOCK))
        # свободный NUMBER есть — это f:out
        self.assertEqual(ex.free_output_of_type(PortType.NUMBER), ("f", "out"))

    def test_loop_index_drives_body_values(self):
        # Тело считает i+1; прогоняем вручную с разными индексами.
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "f", "type": "formula", "params": {"expr": "i * 10"}},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "f:vars"},
            ],
        }
        spec = GraphSpec.parse(body)
        vals = []
        for i in range(4):
            out = GraphExecutor(spec).run_full(extra={LOOP_INDEX_KEY: i})
            vals.append(out["f"]["out"])
        self.assertEqual(vals, [0.0, 10.0, 20.0, 30.0])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — пропуск сбора блоков")
class RepeatBlockCollectionTests(unittest.TestCase):
    def test_repeat_collects_n_text_blocks(self):
        # Тело: loop_index -> var_dict(i) -> template -> text_block(BLOCK).
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "Строка #i#"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        n = RepeatNode("r", {"count": 3, "body": body})
        blocks = n.compute({}, _ctx())["out"]
        self.assertEqual(len(blocks), 3)
        texts = [b.render_plain() for b in blocks]
        self.assertEqual(texts, ["Строка 0", "Строка 1", "Строка 2"])

    def test_repeat_output_feeds_static_task(self):
        # repeat:out (BLOCK_LIST) подключается напрямую к static_task:statement.
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "Пункт #i#"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        graph = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 2}},
                {"id": "rep", "type": "repeat", "params": {"count": 2, "body": body}},
                {"id": "ans", "type": "block_list", "params": {"count": 1}},
                {"id": "tba", "type": "text_block"},
                {"id": "tpl2", "type": "template", "params": {"text": "ответ"}},
                {"id": "vd2", "type": "var_dict", "params": {"names": ["x"]}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "n:out", "to": "rep:count"},
                {"from": "rep:out", "to": "task:statement"},
                {"from": "vd2:out", "to": "tpl2:vars"},
                {"from": "tpl2:out", "to": "tba:text"},
                {"from": "tba:out", "to": "ans:in0"},
                {"from": "ans:out", "to": "task:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        # vd2 has a required input 'x' unconnected -> add a const
        graph["nodes"].append({"id": "cx", "type": "constant_number", "params": {"value": 1}})
        graph["edges"].append({"from": "cx:out", "to": "vd2:x"})
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual(len(task.statement), 2)
        self.assertEqual([b.render_plain() for b in task.statement],
                         ["Пункт 0", "Пункт 1"])


if __name__ == "__main__":
    unittest.main()
