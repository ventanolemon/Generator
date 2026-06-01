"""
Тесты интегральных преобразований (Фаза 3g): Лаплас/Фурье и обратные.

Все операции — headless через sympy; полный граф «Лаплас → FormulaBlock» — под Qt.
Источник переменной — expr_const (предположение positive для аккуратных образов).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec
from core.graph.symbolic import to_latex
from core.graph.nodes.symbolic import (
    ExprConstNode, FourierNode, InverseLaplaceNode, LaplaceNode,
)

try:
    import sympy  # noqa: F401
    HAS_SYMPY = True
except Exception:
    HAS_SYMPY = False

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx():
    return ExecContext(rng=random.Random(0))


def _e(expr, vars, assumptions="positive"):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars),
                               "assumptions": assumptions}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_transform_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("laplace", "inverse_laplace", "fourier", "inverse_fourier"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class LaplaceTests(unittest.TestCase):
    def test_unit(self):
        out = LaplaceNode("l", {}).compute({"in": _e("1", ["t"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{1}{s}")

    def test_t(self):
        out = LaplaceNode("l", {}).compute({"in": _e("t", ["t"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{1}{s^{2}}")

    def test_exp(self):
        out = LaplaceNode("l", {}).compute({"in": _e("exp(2*t)", ["t"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{1}{s - 2}")

    def test_sin(self):
        out = LaplaceNode("l", {}).compute({"in": _e("sin(3*t)", ["t"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{3}{s^{2} + 9}")

    def test_custom_vars(self):
        # f(x) -> F(p)
        out = LaplaceNode("l", {"from_var": "x", "to_var": "p"}).compute(
            {"in": _e("x", ["x"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{1}{p^{2}}")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class InverseLaplaceTests(unittest.TestCase):
    def test_inverse_t(self):
        # 1/s^2 -> t (с множителем Хевисайда θ(t) для каузальности)
        out = InverseLaplaceNode("i", {}).compute({"in": _e("1/s^2", ["s"])}, _ctx())["out"]
        self.assertIn("t", to_latex(out))

    def test_inverse_exp(self):
        out = InverseLaplaceNode("i", {}).compute({"in": _e("1/(s-2)", ["s"])}, _ctx())["out"]
        self.assertIn(r"e^{2 t}", to_latex(out))

    def test_roundtrip_sin(self):
        # L[sin(3t)] = 3/(s^2+9); обратное возвращает sin(3t)·θ(t)
        out = InverseLaplaceNode("i", {}).compute({"in": _e("3/(s^2+9)", ["s"])}, _ctx())["out"]
        self.assertIn(r"\sin{\left(3 t \right)}", to_latex(out))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class FourierTests(unittest.TestCase):
    def test_gaussian(self):
        out = FourierNode("f", {}).compute({"in": _e("exp(-x^2)", ["x"])}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\sqrt{\pi} e^{- \pi^{2} \omega^{2}}")


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class FullGraphTests(unittest.TestCase):
    def test_laplace_to_task(self):
        # expr_const sin(3t) -> laplace -> expr_block(prefix F(s)) -> task
        graph = {
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "sin(3*t)", "vars": ["t"], "assumptions": "positive"}},
                {"id": "lap", "type": "laplace"},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "F(s)"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "lap:in"},
                {"from": "lap:out", "to": "blk:in"},
                {"from": "blk:out", "to": "sbl:in0"},
                {"from": "sbl:out", "to": "st:statement"},
                {"from": "az:out", "to": "avd:w"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "st:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual(task.statement[0].render_plain(),
                         r"$F(s) = \frac{3}{s^{2} + 9}$")


if __name__ == "__main__":
    unittest.main()
