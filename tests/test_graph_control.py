"""
Тесты узлов управления (категория control), headless.

constant_bool / compare / number_check производят BOOL; select по условию
выбирает одну из двух ветвей. Проверяется, что булева подсистема замкнута и
что ветвление работает end-to-end через исполнитель.
"""

from __future__ import annotations
import random
import unittest

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec,
    GraphValidationError, PortType,
)
from core.graph.nodes.control import (
    CompareNode, NumberCheckNode, SelectNode,
)
from core.graph.nodes.sources import ConstantBoolNode


def _ctx():
    return ExecContext(rng=random.Random(0))


class RegistryTests(unittest.TestCase):
    def test_control_nodes_registered(self):
        for tid in ["constant_bool", "compare", "number_check", "select"]:
            self.assertTrue(DEFAULT_REGISTRY.has(tid), tid)

    def test_control_category_in_palette(self):
        cats = {e["category"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("control", cats)


class BoolProducerTests(unittest.TestCase):
    def test_constant_bool(self):
        self.assertIs(ConstantBoolNode("b", {"value": "true"}).compute({}, _ctx())["out"], True)
        self.assertIs(ConstantBoolNode("b", {"value": "false"}).compute({}, _ctx())["out"], False)

    def test_compare_ops(self):
        self.assertTrue(CompareNode("c", {"op": ">"}).compute({"a": 5, "b": 3}, _ctx())["out"])
        self.assertFalse(CompareNode("c", {"op": "<"}).compute({"a": 5, "b": 3}, _ctx())["out"])
        self.assertTrue(CompareNode("c", {"op": "=="}).compute({"a": 2, "b": 2}, _ctx())["out"])

    def test_compare_bad_op_rejected(self):
        with self.assertRaises(GraphValidationError):
            CompareNode("c", {"op": "≈"})

    def test_number_check_even_odd(self):
        self.assertTrue(NumberCheckNode("n", {"check": "even"}).compute({"in": 4}, _ctx())["out"])
        self.assertFalse(NumberCheckNode("n", {"check": "even"}).compute({"in": 5}, _ctx())["out"])
        self.assertTrue(NumberCheckNode("n", {"check": "odd"}).compute({"in": 5}, _ctx())["out"])

    def test_number_check_divisible(self):
        n = NumberCheckNode("n", {"check": "divisible_by", "divisor": 3})
        self.assertTrue(n.compute({"in": 9}, _ctx())["out"])
        self.assertFalse(n.compute({"in": 10}, _ctx())["out"])

    def test_number_check_bad_check_rejected(self):
        with self.assertRaises(GraphValidationError):
            NumberCheckNode("n", {"check": "purple"})


class SelectTests(unittest.TestCase):
    def test_select_picks_branch(self):
        s = SelectNode("s", {"value_type": "number"})
        self.assertEqual(s.compute({"cond": True, "on_true": 1, "on_false": 2}, _ctx())["out"], 1)
        self.assertEqual(s.compute({"cond": False, "on_true": 1, "on_false": 2}, _ctx())["out"], 2)

    def test_select_ports_follow_value_type(self):
        s = SelectNode("s", {"value_type": "string"})
        ins = {p.name: p.type for p in s.input_ports()}
        self.assertEqual(ins["cond"], PortType.BOOL)
        self.assertEqual(ins["on_true"], PortType.STRING)
        self.assertEqual(s.output_ports()[0].type, PortType.STRING)

    def test_select_bad_type_rejected(self):
        with self.assertRaises(GraphValidationError):
            SelectNode("s", {"value_type": "banana"})


class BranchingPipelineTests(unittest.TestCase):
    """Жадное ветвление через исполнитель: «если чётное → A, иначе → B»."""

    def _graph(self, value: int) -> dict:
        return {
            "version": 1,
            "nodes": [
                {"id": "x",   "type": "constant_number", "params": {"value": value}},
                {"id": "chk", "type": "number_check",    "params": {"check": "even"}},
                {"id": "a",   "type": "constant_number", "params": {"value": 100}},
                {"id": "b",   "type": "constant_number", "params": {"value": 200}},
                {"id": "sel", "type": "select",          "params": {"value_type": "number"}},
            ],
            "edges": [
                {"from": "x:out",   "to": "chk:in"},
                {"from": "chk:out", "to": "sel:cond"},
                {"from": "a:out",   "to": "sel:on_true"},
                {"from": "b:out",   "to": "sel:on_false"},
            ],
            "meta": {"max_attempts": 1},
        }

    def test_even_takes_true_branch(self):
        ex = GraphExecutor(GraphSpec.parse(self._graph(4)))
        out = ex.run_full()
        self.assertEqual(out["sel"]["out"], 100)

    def test_odd_takes_false_branch(self):
        ex = GraphExecutor(GraphSpec.parse(self._graph(7)))
        out = ex.run_full()
        self.assertEqual(out["sel"]["out"], 200)

    def test_type_safety_bool_into_number_rejected(self):
        # compare:out (BOOL) нельзя завести в formula:vars (NUMBER_DICT) и т.п.;
        # проверяем, что BOOL не подключается к NUMBER-входу select:on_true.
        data = {
            "nodes": [
                {"id": "cb",  "type": "constant_bool", "params": {"value": "true"}},
                {"id": "sel", "type": "select",        "params": {"value_type": "number"}},
            ],
            "edges": [{"from": "cb:out", "to": "sel:on_true"}],   # BOOL -> NUMBER
        }
        with self.assertRaises(GraphValidationError):
            GraphExecutor(GraphSpec.parse(data))


if __name__ == "__main__":
    unittest.main()
