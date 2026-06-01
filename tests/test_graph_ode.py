"""
Тесты ОДУ (Фаза 3f): ode_const / ode_solve / ode_classify / ode_check.

Разбор и решение — headless через sympy; classify (BLOCK) и полный граф — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec
from core.graph.symbolic import parse_ode, to_latex
from core.graph.nodes.ode import (
    OdeCheckNode, OdeConstNode, OdeSolveNode,
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


def _ode(eq):
    return OdeConstNode("o", {"equation": eq}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ParseTests(unittest.TestCase):
    def test_prime_notation(self):
        eq, f, v = parse_ode("y' = y")
        self.assertEqual(to_latex(eq),
                         r"\frac{d}{d x} y{\left(x \right)} = y{\left(x \right)}")

    def test_second_order(self):
        eq, f, v = parse_ode("y'' + y = 0")
        self.assertIn(r"\frac{d^{2}}{d x^{2}}", to_latex(eq))

    def test_no_equals_means_zero(self):
        eq, f, v = parse_ode("y' - y")
        import sympy as sp
        self.assertEqual(eq.rhs, sp.Integer(0))

    def test_custom_func_var(self):
        eq, f, v = parse_ode("x' = x", func="x", var="t")
        self.assertEqual(str(v), "t")

    def test_empty_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            parse_ode("")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_ode_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("ode_const", "ode_solve", "ode_classify", "ode_check"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SolveTests(unittest.TestCase):
    def test_exponential(self):
        out = OdeSolveNode("s", {}).compute({"in": _ode("y' = y")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"y{\left(x \right)} = C_{1} e^{x}")

    def test_harmonic(self):
        out = OdeSolveNode("s", {}).compute({"in": _ode("y'' + y = 0")}, _ctx())["out"]
        self.assertEqual(
            to_latex(out),
            r"y{\left(x \right)} = C_{1} \sin{\left(x \right)} + C_{2} \cos{\left(x \right)}")

    def test_linear_first_order(self):
        out = OdeSolveNode("s", {}).compute({"in": _ode("y' + 2*y = x")}, _ctx())["out"]
        self.assertIn(r"e^{- 2 x}", to_latex(out))

    def test_ivp_cauchy(self):
        # y'' + y = 0, y(0)=1, y'(0)=0 -> cos(x)
        out = OdeSolveNode("s", {"ics": ["y(0)=1", "y'(0)=0"]}).compute(
            {"in": _ode("y'' + y = 0")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"y{\left(x \right)} = \cos{\left(x \right)}")

    def test_ivp_first_order(self):
        # y' = y, y(0)=2 -> 2 e^x
        out = OdeSolveNode("s", {"ics": ["y(0)=2"]}).compute(
            {"in": _ode("y' = y")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"y{\left(x \right)} = 2 e^{x}")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class CheckTests(unittest.TestCase):
    def test_correct_solution(self):
        sol = OdeSolveNode("s", {}).compute({"in": _ode("y' = y")}, _ctx())["out"]
        ok = OdeCheckNode("k", {}).compute(
            {"equation": _ode("y' = y"), "solution": sol}, _ctx())["out"]
        self.assertIs(ok, True)

    def test_wrong_solution(self):
        import sympy as sp
        x = sp.Symbol("x"); y = sp.Function("y")
        wrong = sp.Eq(y(x), x**2)  # не решение y'=y
        ok = OdeCheckNode("k", {}).compute(
            {"equation": _ode("y' = y"), "solution": wrong}, _ctx())["out"]
        self.assertIs(ok, False)


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class ClassifyAndGraphTests(unittest.TestCase):
    def test_classify_separable(self):
        from core.graph.nodes.ode import OdeClassifyNode
        out = OdeClassifyNode("c", {}).compute({"in": _ode("y' = x*y")}, _ctx())["out"]
        self.assertEqual(out.render_plain(), "separable")

    def test_full_graph_ivp_to_task(self):
        # ode_const -> ode_solve(ics) -> expr_block -> task
        graph = {
            "nodes": [
                {"id": "ode", "type": "ode_const",
                 "params": {"equation": "y'' + y = 0"}},
                {"id": "sol", "type": "ode_solve",
                 "params": {"ics": ["y(0)=1", "y'(0)=0"]}},
                {"id": "blk", "type": "expr_block", "params": {"prefix": ""}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "ode:out", "to": "sol:in"},
                {"from": "sol:out", "to": "blk:in"},
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
                         r"$y{\left(x \right)} = \cos{\left(x \right)}$")


if __name__ == "__main__":
    unittest.main()
