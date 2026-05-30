"""
Тесты движка графа: реестр, парсинг/валидация спеки, топосортировка,
проверка типов, whole-graph retry. Полностью headless (без PyQt6).
"""

from __future__ import annotations
import unittest

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphError, GraphExecutor,
    GraphSpec, GraphValidationError, NodeRegistry, Port, PortType, RetryGeneration,
)
from core.graph.node import Node
from core.graph.nodes.compute import ConstraintNode, FormulaNode, VarDictNode
import random


def _ctx():
    return ExecContext(rng=random.Random(0))


class RegistryTests(unittest.TestCase):
    def test_default_registry_has_phase0_nodes(self):
        for tid in ["constant_number", "random_natural", "random_real",
                    "var_dict", "formula", "constraint", "template",
                    "text_block", "block_list", "static_task"]:
            self.assertTrue(DEFAULT_REGISTRY.has(tid), tid)

    def test_unknown_type_raises(self):
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.create("does_not_exist", "n", {})

    def test_duplicate_registration_raises(self):
        reg = NodeRegistry()
        reg.register(ConstraintNode)
        with self.assertRaises(ValueError):
            reg.register(ConstraintNode)

    def test_palette_is_serializable_shape(self):
        pal = DEFAULT_REGISTRY.palette()
        self.assertTrue(any(p["type_id"] == "formula" for p in pal))
        entry = next(p for p in pal if p["type_id"] == "formula")
        self.assertEqual(entry["category"], "compute")


class SpecParseTests(unittest.TestCase):
    def test_roundtrip(self):
        data = {
            "version": 1,
            "nodes": [{"id": "c", "type": "constant_number", "params": {"value": 5}}],
            "edges": [],
            "meta": {"max_attempts": 10},
        }
        spec = GraphSpec.parse(data)
        self.assertEqual(spec.to_dict()["nodes"][0]["id"], "c")
        self.assertEqual(spec.meta["max_attempts"], 10)

    def test_bad_endpoint_raises(self):
        with self.assertRaises(GraphValidationError):
            GraphSpec.parse({"nodes": [], "edges": [{"from": "no_colon", "to": "a:b"}]})

    def test_node_missing_type_raises(self):
        with self.assertRaises(GraphValidationError):
            GraphSpec.parse({"nodes": [{"id": "x"}], "edges": []})


class ValidationTests(unittest.TestCase):
    def _exec(self, data):
        return GraphExecutor(GraphSpec.parse(data))

    def test_dangling_edge_unknown_node(self):
        data = {
            "nodes": [{"id": "c", "type": "constant_number", "params": {"value": 1}}],
            "edges": [{"from": "c:out", "to": "ghost:in"}],
        }
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_type_mismatch(self):
        # constant_number (NUMBER) → formula:vars (NUMBER_DICT) — несовместимо.
        data = {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 1}},
                {"id": "f", "type": "formula", "params": {"expr": "x"}},
            ],
            "edges": [{"from": "c:out", "to": "f:vars"}],
        }
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_duplicate_node_id(self):
        data = {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 1}},
                {"id": "c", "type": "constant_number", "params": {"value": 2}},
            ],
            "edges": [],
        }
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_missing_required_input(self):
        # formula требует вход vars, он не подключён.
        data = {"nodes": [{"id": "f", "type": "formula", "params": {"expr": "x"}}],
                "edges": []}
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_double_connected_input(self):
        data = {
            "nodes": [
                {"id": "a", "type": "constant_number", "params": {"value": 1}},
                {"id": "b", "type": "constant_number", "params": {"value": 2}},
                {"id": "vd", "type": "var_dict", "params": {"names": ["x"]}},
            ],
            "edges": [
                {"from": "a:out", "to": "vd:x"},
                {"from": "b:out", "to": "vd:x"},
            ],
        }
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_cycle_detected(self):
        # var_dict x → formula → constraint → var_dict x (искусственный цикл)
        data = {
            "nodes": [
                {"id": "vd", "type": "var_dict", "params": {"names": ["x"]}},
                {"id": "f", "type": "formula", "params": {"expr": "x"}},
                {"id": "ch", "type": "constraint", "params": {"kind": "real"}},
            ],
            "edges": [
                {"from": "vd:out", "to": "f:vars"},
                {"from": "f:out", "to": "ch:in"},
                {"from": "ch:out", "to": "vd:x"},
            ],
        }
        with self.assertRaises(GraphValidationError):
            self._exec(data)

    def test_multiple_task_sinks(self):
        # Два полноценных static_task (входы запитаны пустыми block_list) →
        # два неподключённых выхода TASK → ошибка «должен быть один финал».
        def task_chain(suffix):
            return (
                [
                    {"id": f"lc{suffix}", "type": "block_list", "params": {"count": 1}},
                    {"id": f"la{suffix}", "type": "block_list", "params": {"count": 1}},
                    {"id": f"t{suffix}", "type": "static_task"},
                ],
                [
                    {"from": f"lc{suffix}:out", "to": f"t{suffix}:statement"},
                    {"from": f"la{suffix}:out", "to": f"t{suffix}:answer"},
                ],
            )
        n1, e1 = task_chain(1)
        n2, e2 = task_chain(2)
        data = {"nodes": n1 + n2, "edges": e1 + e2}
        with self.assertRaisesRegex(GraphValidationError, "финал"):
            self._exec(data)


class NodeComputeTests(unittest.TestCase):
    def test_var_dict_collects(self):
        n = VarDictNode("vd", {"names": ["a", "b"]})
        out = n.compute({"a": 2, "b": 3}, _ctx())
        self.assertEqual(out["out"], {"a": 2.0, "b": 3.0})

    def test_formula_evaluates(self):
        n = FormulaNode("f", {"expr": "a * b + 1"})
        out = n.compute({"vars": {"a": 2, "b": 3}}, _ctx())
        self.assertEqual(out["out"], 7.0)

    def test_formula_zero_division_requests_retry(self):
        n = FormulaNode("f", {"expr": "1 / a"})
        with self.assertRaises(RetryGeneration):
            n.compute({"vars": {"a": 0}}, _ctx())

    def test_constraint_passes_and_normalizes(self):
        n = ConstraintNode("c", {"kind": "natural", "min": 1, "max": 10})
        out = n.compute({"in": 5.0}, _ctx())
        self.assertEqual(out["out"], 5.0)

    def test_constraint_rejects_with_retry(self):
        n = ConstraintNode("c", {"kind": "natural", "min": 1, "max": 10})
        with self.assertRaises(RetryGeneration):
            n.compute({"in": 5.5}, _ctx())   # не натуральное
        with self.assertRaises(RetryGeneration):
            n.compute({"in": 100}, _ctx())   # вне диапазона

    def test_bad_formula_param_rejected_at_construction(self):
        with self.assertRaises(GraphValidationError):
            FormulaNode("f", {"expr": "import os"})


class RetryLoopTests(unittest.TestCase):
    def test_exhaustion_raises_graph_error(self):
        # 100 (константа) при constraint max=10 — никогда не пройдёт.
        data = {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 100}},
                {"id": "vd", "type": "var_dict", "params": {"names": ["x"]}},
                {"id": "f", "type": "formula", "params": {"expr": "x"}},
                {"id": "ch", "type": "constraint",
                 "params": {"kind": "natural", "min": 1, "max": 10}},
            ],
            "edges": [
                {"from": "c:out", "to": "vd:x"},
                {"from": "vd:out", "to": "f:vars"},
                {"from": "f:out", "to": "ch:in"},
            ],
            "meta": {"max_attempts": 5},
        }
        ex = GraphExecutor(GraphSpec.parse(data))
        with self.assertRaises(GraphError):
            ex.run_full()

    def test_run_without_task_sink_raises(self):
        data = {
            "nodes": [{"id": "c", "type": "constant_number", "params": {"value": 1}}],
            "edges": [],
        }
        ex = GraphExecutor(GraphSpec.parse(data))
        with self.assertRaises(GraphValidationError):
            ex.run()                       # нет TASK-узла
        # но run_full исполняет граф и отдаёт выходы
        outputs = ex.run_full()
        self.assertEqual(outputs["c"]["out"], 1.0)


if __name__ == "__main__":
    unittest.main()
