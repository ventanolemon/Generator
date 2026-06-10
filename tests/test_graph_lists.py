"""
Тесты операций со списками (list_*) и вывода значений из цикла (reg_-выходы
repeat). Накопление в list-регистр и финальное значение — ключевые сценарии.

Список-узлы — headless; накопление с рендером блоков — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, PortType
from core.graph.nodes.lists import (
    ListAppendNode, ListGetNode, ListJoinNode, ListLengthNode, ListNewNode,
)
from core.graph.nodes.loop import RepeatNode

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


class RegistryTests(unittest.TestCase):
    def test_list_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("list_new", "list_append", "list_length", "list_get",
                    "list_join"):
            self.assertIn(tid, ids)

    def test_list_category(self):
        cats = {e["category"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("list", cats)


class ListOpsTests(unittest.TestCase):
    def test_new_from_items(self):
        out = ListNewNode("n", {"items": ["1", "2", "x"]}).compute({}, _ctx())["out"]
        self.assertEqual(out, [1, 2, "x"])

    def test_new_from_inputs(self):
        n = ListNewNode("n", {"count": 2, "elem_type": "number"})
        # динамические входы in0/in1
        names = [p.name for p in n.input_ports()]
        self.assertEqual(names, ["in0", "in1"])
        out = n.compute({"in0": 5, "in1": 7}, _ctx())["out"]
        self.assertEqual(out, [5, 7])

    def test_append_returns_new_list(self):
        base = [1, 2]
        out = ListAppendNode("a", {}).compute({"list": base, "item": 3}, _ctx())["out"]
        self.assertEqual(out, [1, 2, 3])
        self.assertEqual(base, [1, 2])      # исходный не мутирован

    def test_append_to_empty(self):
        out = ListAppendNode("a", {}).compute({"item": 9}, _ctx())["out"]
        self.assertEqual(out, [9])

    def test_length(self):
        self.assertEqual(
            ListLengthNode("l", {}).compute({"in": [1, 2, 3]}, _ctx())["out"], 3.0)

    def test_get_positive_and_negative(self):
        self.assertEqual(
            ListGetNode("g", {"index": 0}).compute({"list": [10, 20, 30]}, _ctx())["out"], 10)
        self.assertEqual(
            ListGetNode("g", {"index": -1}).compute({"list": [10, 20, 30]}, _ctx())["out"], 30)

    def test_get_index_from_input(self):
        out = ListGetNode("g", {}).compute({"list": [4, 5, 6], "index": 1}, _ctx())["out"]
        self.assertEqual(out, 5)

    def test_get_out_of_range_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            ListGetNode("g", {"index": 9}).compute({"list": [1]}, _ctx())

    def test_join(self):
        out = ListJoinNode("j", {"sep": "-"}).compute({"in": [1, 2, 3]}, _ctx())["out"]
        self.assertEqual(out, "1-2-3")

    def test_join_formats_integers(self):
        # float-целые без .0
        out = ListJoinNode("j", {"sep": ","}).compute({"in": [1.0, 2.0]}, _ctx())["out"]
        self.assertEqual(out, "1,2")

    def test_get_typed_output(self):
        n = ListGetNode("g", {"elem_type": "string"})
        self.assertEqual(n.output_ports()[0].type, PortType.STRING)


class RepeatRegisterOutputTests(unittest.TestCase):
    def test_repeat_exposes_register_outputs(self):
        n = RepeatNode("r", {"registers": ["acc:list", "s:number:0"]})
        names = {p.name: p.type for p in n.output_ports()}
        self.assertEqual(names["out"], PortType.BLOCK_LIST)
        self.assertEqual(names["reg_acc"], PortType.LIST)
        self.assertEqual(names["reg_s"], PortType.NUMBER)

    def test_no_registers_only_out(self):
        n = RepeatNode("r", {})
        self.assertEqual([p.name for p in n.output_ports()], ["out"])


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class AccumulationTests(unittest.TestCase):
    def test_accumulate_into_list(self):
        # квадраты индексов 0..4 копятся в list-регистр
        body = {
            "nodes": [
                {"id": "sg", "type": "shift_get", "params": {"name": "acc", "type": "list"}},
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "f", "type": "formula", "params": {"expr": "i*i"}},
                {"id": "ap", "type": "list_append", "params": {"elem_type": "number"}},
                {"id": "ss", "type": "shift_set", "params": {"name": "acc", "type": "list"}},
            ],
            "edges": [
                {"from": "sg:out", "to": "ap:list"},
                {"from": "li:out", "to": "vd:i"}, {"from": "vd:out", "to": "f:vars"},
                {"from": "f:out", "to": "ap:item"}, {"from": "ap:out", "to": "ss:value"},
            ],
        }
        n = RepeatNode("r", {"count": 5, "registers": ["acc:list"], "body": body})
        out = n.compute({}, _ctx())
        self.assertEqual(out["reg_acc"], [0.0, 1.0, 4.0, 9.0, 16.0])

    def test_last_value_via_number_register(self):
        # сумма 0..4 = 10 через number-регистр (последнее значение)
        body = {
            "nodes": [
                {"id": "sg", "type": "shift_get", "params": {"name": "s", "type": "number"}},
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["s", "i"]}},
                {"id": "f", "type": "formula", "params": {"expr": "s+i"}},
                {"id": "ss", "type": "shift_set", "params": {"name": "s", "type": "number"}},
            ],
            "edges": [
                {"from": "sg:out", "to": "vd:s"}, {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "f:vars"}, {"from": "f:out", "to": "ss:value"},
            ],
        }
        n = RepeatNode("r", {"count": 5, "registers": ["s:number:0"], "body": body})
        out = n.compute({}, _ctx())
        self.assertEqual(out["reg_s"], 10.0)


if __name__ == "__main__":
    unittest.main()
