"""
Тесты математического анализа (PR-2 фазы 3d): diff/integrate/limit/series.

Все операции — headless через sympy; полный граф с производной в FormulaBlock —
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
    DiffNode, ExprConstNode, IntegrateNode, LimitNode, SeriesNode, SymbolNode,
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


def _e(expr, vars=("x",)):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars)}).compute({}, _ctx())["out"]


def _x(name="x"):
    return SymbolNode("s", {"name": name}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_calculus_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("diff", "integrate", "limit", "series"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class DiffTests(unittest.TestCase):
    def test_first_order(self):
        out = DiffNode("d", {}).compute({"in": _e("x^3"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "3 x^{2}")

    def test_third_order(self):
        out = DiffNode("d", {"order": 3}).compute({"in": _e("exp(x)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "e^{x}")

    def test_product_rule(self):
        out = DiffNode("d", {}).compute({"in": _e("sin(x)*x^2"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out),
                         r"x^{2} \cos{\left(x \right)} + 2 x \sin{\left(x \right)}")

    def test_negative_order_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            DiffNode("d", {"order": -1})


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class IntegrateTests(unittest.TestCase):
    def test_indefinite(self):
        out = IntegrateNode("i", {}).compute({"in": _e("x*cos(x)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out),
                         r"x \sin{\left(x \right)} + \cos{\left(x \right)}")

    def test_definite(self):
        out = IntegrateNode("i", {"lower": "0", "upper": "1"}).compute(
            {"in": _e("x^2"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{1}{3}")

    def test_definite_infinite(self):
        out = IntegrateNode("i", {"lower": "0", "upper": "oo"}).compute(
            {"in": _e("exp(-x)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "1")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class LimitTests(unittest.TestCase):
    def test_classic(self):
        out = LimitNode("l", {"point": "0"}).compute(
            {"in": _e("sin(x)/x"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "1")

    def test_one_sided(self):
        out = LimitNode("l", {"point": "0", "dir": "+"}).compute(
            {"in": _e("1/x"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\infty")

    def test_at_infinity(self):
        out = LimitNode("l", {"point": "oo"}).compute(
            {"in": _e("(1+1/x)^x"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "e")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SeriesTests(unittest.TestCase):
    def test_maclaurin_exp(self):
        out = SeriesNode("t", {"point": "0", "order": 5}).compute(
            {"in": _e("exp(x)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(
            to_latex(out),
            r"\frac{x^{4}}{24} + \frac{x^{3}}{6} + \frac{x^{2}}{2} + x + 1")

    def test_sin_series(self):
        out = SeriesNode("t", {"point": "0", "order": 6}).compute(
            {"in": _e("sin(x)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{x^{5}}{120} - \frac{x^{3}}{6} + x")

    def test_bad_order_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            SeriesNode("t", {"order": 0})


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class FullGraphTests(unittest.TestCase):
    def test_derivative_to_task(self):
        # symbol x, expr x^3*sin(x) -> diff -> expr_block(prefix f'(x)) -> task
        graph = {
            "nodes": [
                {"id": "x", "type": "symbol", "params": {"name": "x"}},
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "x^3*sin(x)", "vars": ["x"]}},
                {"id": "d", "type": "diff", "params": {"order": 1}},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "f'(x)"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "d:in"},
                {"from": "x:out", "to": "d:var"},
                {"from": "d:out", "to": "blk:in"},
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
            r"$f'(x) = x^{3} \cos{\left(x \right)} + 3 x^{2} \sin{\left(x \right)}$")


if __name__ == "__main__":
    unittest.main()
