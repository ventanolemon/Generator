"""
Тесты узла guard (rejection sampling) и полировки prefix (_join_prefix).

guard: по ложному условию бросает RetryGeneration → весь граф пересобирается;
value проходит насквозь. Позволяет «генерируй, пока не выполнено условие».
_join_prefix: связка префикса с телом без навязанного/дублирующегося '='.

guard и _join_prefix — headless; рендер блоков (expr_block/to_block) — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphError, GraphExecutor, GraphSpec, PortType,
)
from core.graph.errors import RetryGeneration
from core.graph.nodes.control import GuardNode
from core.graph.nodes.compute import _join_prefix

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False

try:
    import sympy  # noqa: F401
    HAS_SYMPY = True
except Exception:
    HAS_SYMPY = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


class GuardNodeTests(unittest.TestCase):
    def test_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("guard"))

    def test_ports(self):
        g = GuardNode("g", {})
        ins = {p.name: p.type for p in g.input_ports()}
        self.assertEqual(ins["cond"], PortType.BOOL)
        self.assertEqual(ins["value"], PortType.ANY)
        self.assertEqual(g.output_ports()[0].type, PortType.ANY)

    def test_require_true_passes_value_when_true(self):
        out = GuardNode("g", {}).compute({"cond": True, "value": 42}, _ctx())
        self.assertEqual(out["out"], 42)

    def test_require_true_retries_when_false(self):
        with self.assertRaises(RetryGeneration):
            GuardNode("g", {}).compute({"cond": False, "value": 1}, _ctx())

    def test_require_false_inverts(self):
        g = GuardNode("g", {"mode": "require_false"})
        self.assertEqual(g.compute({"cond": False, "value": 7}, _ctx())["out"], 7)
        with self.assertRaises(RetryGeneration):
            g.compute({"cond": True, "value": 7}, _ctx())

    def test_value_optional_passthrough_none(self):
        out = GuardNode("g", {}).compute({"cond": True}, _ctx())
        self.assertIsNone(out["out"])


class GuardRejectionSamplingTests(unittest.TestCase):
    def _perfect_square_graph(self, attempts=300):
        return {
            "nodes": [
                {"id": "x", "type": "random_natural", "params": {"min": 2, "max": 50}},
                {"id": "r", "type": "formula", "params": {"expr": "sqrt(x)"}},
                {"id": "chk", "type": "number_check", "params": {"check": "integer"}},
                {"id": "g", "type": "guard", "params": {"mode": "require_true"}},
            ],
            "edges": [
                {"from": "x:out", "to": "r:x"},
                {"from": "r:out", "to": "chk:in"},
                {"from": "chk:out", "to": "g:cond"},
                {"from": "x:out", "to": "g:value"},
            ],
            "meta": {"max_attempts": attempts},
        }

    def test_guard_keeps_only_valid_candidates(self):
        # Многократно прогоняем: x всегда оказывается полным квадратом.
        import math
        for seed in range(8):
            spec = self._perfect_square_graph()
            spec["meta"]["seed"] = seed
            outs = GraphExecutor(GraphSpec.parse(spec)).run_full()
            x = outs["x"]["out"]
            root = math.isqrt(int(round(x)))
            self.assertEqual(root * root, int(round(x)),
                             f"x={x} не полный квадрат (seed={seed})")

    def test_impossible_condition_exhausts_attempts(self):
        # Требуем, чтобы число было и чётным, и нечётным — никогда.
        spec = {
            "nodes": [
                {"id": "n", "type": "random_natural", "params": {"min": 1, "max": 9}},
                {"id": "chk", "type": "number_check", "params": {"check": "even"}},
                {"id": "chk2", "type": "number_check", "params": {"check": "odd"}},
                {"id": "g", "type": "guard"},
                {"id": "g2", "type": "guard"},
            ],
            "edges": [
                {"from": "n:out", "to": "chk:in"},
                {"from": "n:out", "to": "chk2:in"},
                {"from": "chk:out", "to": "g:cond"},
                {"from": "chk2:out", "to": "g2:cond"},
            ],
            "meta": {"max_attempts": 20},
        }
        with self.assertRaises(GraphError):
            GraphExecutor(GraphSpec.parse(spec)).run_full()


class JoinPrefixTests(unittest.TestCase):
    def test_no_prefix_returns_body(self):
        self.assertEqual(_join_prefix("", "x^2"), "x^2")

    def test_default_adds_equals(self):
        self.assertEqual(_join_prefix("A", "M"), "A = M")
        self.assertEqual(_join_prefix("f(x)", "x+1"), "f(x) = x+1")

    def test_no_double_equals(self):
        self.assertEqual(_join_prefix("y' =", "2x"), "y' = 2x")
        self.assertEqual(_join_prefix("=", "4"), "= 4")

    def test_colon_prefix_not_given_equals(self):
        self.assertEqual(_join_prefix("Ответ:", "5"), "Ответ: 5")

    def test_empty_relation_is_prose(self):
        self.assertEqual(_join_prefix("Получили число", "7", ""), "Получили число 7")

    def test_custom_relation(self):
        self.assertEqual(_join_prefix("x", "0", "≈"), "x ≈ 0")


@unittest.skipUnless(HAS_QT and HAS_SYMPY, "нужны PyQt6 и sympy")
class PrefixRenderTests(unittest.TestCase):
    def _expr_block(self, params):
        from core.graph.nodes.symbolic import ExprBlockNode
        import sympy as sp
        return ExprBlockNode("b", params).compute({"in": sp.Symbol("x") + 1},
                                                  _ctx())["out"]

    def test_expr_block_no_double_equals(self):
        self.assertNotIn("= =", self._expr_block({"prefix": "y' ="}).latex)

    def test_expr_block_default_equals(self):
        self.assertIn("f(x) =", self._expr_block({"prefix": "f(x)"}).latex)

    def test_to_block_prose_relation_empty(self):
        from core.graph.nodes.content import ToBlockNode
        b = ToBlockNode("b", {"prefix": "Получили", "relation": ""}).compute(
            {"in": 7}, _ctx())["out"]
        self.assertEqual(b.render_plain(), "Получили 7")

    def test_to_block_number_default_equals(self):
        from core.graph.nodes.content import ToBlockNode
        b = ToBlockNode("b", {"prefix": "S"}).compute({"in": 5}, _ctx())["out"]
        self.assertEqual(b.render_plain(), "S = 5")


if __name__ == "__main__":
    unittest.main()
