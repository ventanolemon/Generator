"""
Тесты рядов (PR-3 фазы 3d): summation / sum_display / is_convergent.

Операции — headless через sympy; полный граф «знак суммы → FormulaBlock» —
под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec,
)
from core.graph.symbolic import to_latex
from core.graph.nodes.symbolic import (
    ExprConstNode, IsConvergentNode, SumDisplayNode, SummationNode, SymbolNode,
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


def _e(expr, vars):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars)}).compute({}, _ctx())["out"]


def _x(name):
    return SymbolNode("s", {"name": name}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_series_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("summation", "sum_display", "is_convergent"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SummationTests(unittest.TestCase):
    def test_basel(self):
        out = SummationNode("s", {"lower": "1", "upper": "oo"}).compute(
            {"term": _e("1/n^2", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{\pi^{2}}{6}")

    def test_finite(self):
        out = SummationNode("s", {"lower": "1", "upper": "10"}).compute(
            {"term": _e("n", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "55")

    def test_geometric(self):
        out = SummationNode("s", {"lower": "0", "upper": "oo"}).compute(
            {"term": _e("(1/2)^n", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "2")

    def test_symbolic_upper(self):
        # Σ_{n=1}^{k} n = k(k+1)/2
        out = SummationNode("s", {"lower": "1", "upper": "k"}).compute(
            {"term": _e("n", ["n", "k"]), "index": _x("n")}, _ctx())["out"]
        # sympy выдаёт k^2/2 + k/2
        self.assertEqual(to_latex(out), r"\frac{k^{2}}{2} + \frac{k}{2}")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SumDisplayTests(unittest.TestCase):
    def test_unevaluated(self):
        out = SumDisplayNode("d", {"lower": "0", "upper": "oo"}).compute(
            {"term": _e("1/factorial(n)", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\sum_{n=0}^{\infty} \frac{1}{n!}")

    def test_not_collapsed(self):
        # Невычисленная сумма не должна сворачиваться в значение.
        out = SumDisplayNode("d", {"lower": "1", "upper": "oo"}).compute(
            {"term": _e("1/n^2", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertIn(r"\sum", to_latex(out))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ConvergenceTests(unittest.TestCase):
    def test_convergent(self):
        out = IsConvergentNode("c", {"lower": "1"}).compute(
            {"term": _e("1/n^2", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertIs(out, True)

    def test_divergent_harmonic(self):
        out = IsConvergentNode("c", {"lower": "1"}).compute(
            {"term": _e("1/n", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertIs(out, False)

    def test_factorial_convergent(self):
        out = IsConvergentNode("c", {"lower": "0"}).compute(
            {"term": _e("1/factorial(n)", ["n"]), "index": _x("n")}, _ctx())["out"]
        self.assertIs(out, True)


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class FullGraphTests(unittest.TestCase):
    def test_sum_display_to_task(self):
        # sum_display ∑1/n² + symbol n -> expr_block(prefix S) -> task
        graph = {
            "nodes": [
                {"id": "n", "type": "symbol", "params": {"name": "n"}},
                {"id": "t", "type": "expr_const",
                 "params": {"expr": "1/n^2", "vars": ["n"]}},
                {"id": "sd", "type": "sum_display",
                 "params": {"lower": "1", "upper": "oo"}},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "S"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "t:out", "to": "sd:term"},
                {"from": "n:out", "to": "sd:index"},
                {"from": "sd:out", "to": "blk:in"},
                {"from": "blk:out", "to": "sbl:in0"},
                {"from": "sbl:out", "to": "st:statement"},
                {"from": "az:out", "to": "avd:z"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "st:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual(
            task.statement[0].render_plain(),
            r"$S = \sum_{n=1}^{\infty} \frac{1}{n^{2}}$")


if __name__ == "__main__":
    unittest.main()
