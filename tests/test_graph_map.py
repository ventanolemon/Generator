"""
Тесты структурного map и типа LIST (PR-2 фазы 3b-2).

Источники списков и механика map_item — headless; сбор BLOCK по элементам и
подключение к static_task — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType
from core.graph.nodes.loop import LOOP_INDEX_KEY, MAP_ITEM_KEY, MapItemNode, MapNode
from core.graph.nodes.sources import NumberRangeNode, StringListNode

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(**extra):
    return ExecContext(rng=random.Random(0), extra=extra)


class ListPortTypeTests(unittest.TestCase):
    def test_list_type_exists(self):
        self.assertTrue(hasattr(PortType, "LIST"))
        self.assertEqual(PortType.LIST.value, "list")


class StringListTests(unittest.TestCase):
    def test_items_to_list(self):
        n = StringListNode("s", {"items": ["раз", "два", "три"]})
        self.assertEqual(n.compute({}, _ctx())["out"], ["раз", "два", "три"])

    def test_empty_default(self):
        self.assertEqual(StringListNode("s", {}).compute({}, _ctx())["out"], [])

    def test_outputs_list_type(self):
        self.assertEqual(StringListNode("s", {}).output_ports()[0].type, PortType.LIST)


class NumberRangeTests(unittest.TestCase):
    def test_inclusive_range(self):
        n = NumberRangeNode("r", {"start": 1, "stop": 5, "step": 1})
        self.assertEqual(n.compute({}, _ctx())["out"], [1, 2, 3, 4, 5])

    def test_step_two(self):
        n = NumberRangeNode("r", {"start": 0, "stop": 6, "step": 2})
        self.assertEqual(n.compute({}, _ctx())["out"], [0, 2, 4, 6])

    def test_descending(self):
        n = NumberRangeNode("r", {"start": 3, "stop": 1, "step": -1})
        self.assertEqual(n.compute({}, _ctx())["out"], [3, 2, 1])

    def test_zero_step_safe(self):
        n = NumberRangeNode("r", {"start": 1, "stop": 3, "step": 0})
        self.assertEqual(n.compute({}, _ctx())["out"], [1, 2, 3])


class MapItemTests(unittest.TestCase):
    def test_string_element(self):
        n = MapItemNode("m", {"type": "string"})
        self.assertEqual(n.compute({}, _ctx(**{MAP_ITEM_KEY: "кот"}))["out"], "кот")
        self.assertEqual(n.output_ports()[0].type, PortType.STRING)

    def test_number_element(self):
        n = MapItemNode("m", {"type": "number"})
        self.assertEqual(n.compute({}, _ctx(**{MAP_ITEM_KEY: 7}))["out"], 7.0)
        self.assertEqual(n.output_ports()[0].type, PortType.NUMBER)

    def test_bad_type_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            MapItemNode("m", {"type": "weird"})


class MapMechanicsTests(unittest.TestCase):
    def test_empty_items_empty_result(self):
        n = MapNode("m", {"body": {"nodes": [], "edges": [], "meta": {}}})
        self.assertEqual(n.compute({"items": []}, _ctx())["out"], [])

    def test_non_list_input_retries(self):
        from core.graph import RetryGeneration
        n = MapNode("m", {"body": {}})
        with self.assertRaises(RetryGeneration):
            n.compute({"items": 5}, _ctx())

    def test_map_item_drives_body(self):
        # Тело: map_item(number) -> var_dict(x) -> formula(x*x). Свободный NUMBER.
        body = {
            "nodes": [
                {"id": "mi", "type": "map_item", "params": {"type": "number"}},
                {"id": "vd", "type": "var_dict", "params": {"names": ["x"]}},
                {"id": "f", "type": "formula", "params": {"expr": "x * x"}},
            ],
            "edges": [
                {"from": "mi:out", "to": "vd:x"},
                {"from": "vd:out", "to": "f:vars"},
            ],
        }
        spec = GraphSpec.parse(body)
        vals = []
        for el in [2, 3, 4]:
            out = GraphExecutor(spec).run_full(extra={MAP_ITEM_KEY: el})
            vals.append(out["f"]["out"])
        self.assertEqual(vals, [4.0, 9.0, 16.0])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class MapBlockCollectionTests(unittest.TestCase):
    def test_map_over_words_to_blocks(self):
        # Слова → блоки: map_item(string) -> text_block напрямую (STRING→STRING).
        body = {
            "nodes": [
                {"id": "mi", "type": "map_item", "params": {"type": "string"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "mi:out", "to": "tb:text"},
            ],
        }
        n = MapNode("m", {"body": body})
        blocks = n.compute({"items": ["кот", "пёс", "ёж"]}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in blocks], ["кот", "пёс", "ёж"])

    def test_map_over_numbers_formatted(self):
        # Числа → форматированные блоки через числовой словарь и шаблон.
        body = {
            "nodes": [
                {"id": "mi", "type": "map_item", "params": {"type": "number"}},
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["x", "i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "#i#) #x# в квадрате"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "mi:out", "to": "vd:x"},
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        n = MapNode("m", {"body": body})
        blocks = n.compute({"items": [2, 5]}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in blocks],
                         ["0) 2 в квадрате", "1) 5 в квадрате"])

    def test_string_list_feeds_map(self):
        # string_list -> map -> static_task.statement (полный граф).
        body = {
            "nodes": [
                {"id": "mi", "type": "map_item", "params": {"type": "string"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "mi:out", "to": "tb:text"},
            ],
        }
        graph = {
            "nodes": [
                {"id": "sl", "type": "string_list", "params": {"items": ["a", "b"]}},
                {"id": "mp", "type": "map", "params": {"body": body}},
                {"id": "cx", "type": "constant_number", "params": {"value": 1}},
                {"id": "vd2", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "tpl2", "type": "template", "params": {"text": "ответ"}},
                {"id": "tba", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "sl:out", "to": "mp:items"},
                {"from": "mp:out", "to": "task:statement"},
                {"from": "cx:out", "to": "vd2:z"},
                {"from": "vd2:out", "to": "tpl2:vars"},
                {"from": "tpl2:out", "to": "tba:text"},
                {"from": "tba:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "task:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual([b.render_plain() for b in task.statement], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
