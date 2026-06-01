"""
Тесты символьной арифметики (PR-1: ядро + алгебра).

Механика операций — headless через sympy; рендер EXPR→BLOCK (FormulaBlock) и
полный граф со static_task — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.symbolic import parse_expr, to_latex, build_symbols
from core.graph.nodes.symbolic import (
    ApartNode, CancelNode, CollectNode, EvaluateNode, ExpandNode,
    ExprBinaryNode, ExprConstNode, FactorNode, SimplifyNode, SubstituteNode,
    SymbolNode, TogetherNode,
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


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class PortTypeTests(unittest.TestCase):
    def test_expr_type_exists(self):
        self.assertTrue(hasattr(PortType, "EXPR"))
        self.assertEqual(PortType.EXPR.value, "expr")

    def test_all_symbolic_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()
               if e["category"] == "symbolic"}
        # Базовый набор PR-1 (алгебра/арифметика/рендер) должен присутствовать;
        # мат. анализ и прочее добавляются следующими PR — проверяем включение.
        expected = {"symbol", "expr_const", "expand", "factor", "simplify",
                    "together", "cancel", "trigsimp", "collect", "apart",
                    "expr_binop", "expr_subs", "expr_eval", "expr_block"}
        self.assertTrue(expected <= ids, f"не хватает: {expected - ids}")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SourceTests(unittest.TestCase):
    def test_symbol(self):
        out = SymbolNode("s", {"name": "y"}).compute({}, _ctx())["out"]
        self.assertEqual(str(out), "y")

    def test_symbol_real_assumption(self):
        out = SymbolNode("s", {"name": "x", "assumptions": "real"}).compute({}, _ctx())["out"]
        self.assertTrue(out.is_real)

    def test_expr_const_parses(self):
        self.assertEqual(to_latex(_e("x^2 + 2*x + 1")), "x^{2} + 2 x + 1")

    def test_expr_const_implicit_mult(self):
        # '2x' трактуется как 2*x благодаря implicit multiplication.
        self.assertEqual(to_latex(_e("2x")), "2 x")

    def test_bad_expr_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            ExprConstNode("e", {"expr": "x +* ", "vars": ["x"]})


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class AlgebraTests(unittest.TestCase):
    def test_expand(self):
        out = ExpandNode("n", {}).compute({"in": _e("(x+1)^3")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "x^{3} + 3 x^{2} + 3 x + 1")

    def test_factor(self):
        out = FactorNode("n", {}).compute({"in": _e("x^2-1")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\left(x - 1\right) \left(x + 1\right)")

    def test_simplify(self):
        out = SimplifyNode("n", {}).compute({"in": _e("sin(x)^2+cos(x)^2")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "1")

    def test_cancel(self):
        out = CancelNode("n", {}).compute({"in": _e("(x^2-1)/(x-1)")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "x + 1")

    def test_together(self):
        out = TogetherNode("n", {}).compute({"in": _e("1/x+1/y", ("x", "y"))}, _ctx())["out"]
        # x*y в знаменателе, x+y в числителе
        self.assertIn("x + y", to_latex(out))

    def test_collect(self):
        # collect группирует по степеням x: a*x + b*x + c -> (a+b)*x + c.
        expr = _e("a*x + b*x + c", ("a", "b", "c", "x"))
        var = SymbolNode("s", {"name": "x"}).compute({}, _ctx())["out"]
        out = CollectNode("n", {}).compute({"in": expr, "var": var}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"c + x \left(a + b\right)")

    def test_apart(self):
        expr = _e("1/(x^2-1)")
        var = SymbolNode("s", {"name": "x"}).compute({}, _ctx())["out"]
        out = ApartNode("n", {}).compute({"in": expr, "var": var}, _ctx())["out"]
        self.assertIn(r"\frac", to_latex(out))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ArithmeticTests(unittest.TestCase):
    def test_binop_mul(self):
        out = ExprBinaryNode("n", {"op": "mul"}).compute(
            {"a": _e("x+1"), "b": _e("x-1")}, _ctx())["out"]
        expanded = ExpandNode("e", {}).compute({"in": out}, _ctx())["out"]
        self.assertEqual(to_latex(expanded), "x^{2} - 1")

    def test_binop_div(self):
        out = ExprBinaryNode("n", {"op": "div"}).compute(
            {"a": _e("x^2"), "b": _e("x")}, _ctx())["out"]
        simplified = SimplifyNode("s", {}).compute({"in": out}, _ctx())["out"]
        self.assertEqual(to_latex(simplified), "x")

    def test_bad_op_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            ExprBinaryNode("n", {"op": "mod"})

    def test_substitute_and_eval(self):
        expr = _e("a*x+b", ("a", "x", "b"))
        sub = SubstituteNode("s", {}).compute(
            {"in": expr, "values": {"a": 2, "b": 3, "x": 5}}, _ctx())["out"]
        val = EvaluateNode("v", {}).compute({"in": sub}, _ctx())["out"]
        self.assertEqual(val, 13.0)

    def test_eval_symbolic_left_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            EvaluateNode("v", {}).compute({"in": _e("x+1")}, _ctx())


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class RenderTests(unittest.TestCase):
    def test_expr_block(self):
        from core.graph.nodes.symbolic import ExprBlockNode
        from core.blocks import FormulaBlock
        out = ExprBlockNode("b", {}).compute({"in": _e("x^2-1")}, _ctx())["out"]
        self.assertIsInstance(out, FormulaBlock)
        self.assertEqual(out.render_plain(), "$x^{2} - 1$")

    def test_expr_block_prefix(self):
        from core.graph.nodes.symbolic import ExprBlockNode
        out = ExprBlockNode("b", {"prefix": "f(x)"}).compute(
            {"in": _e("x+1")}, _ctx())["out"]
        self.assertEqual(out.render_plain(), "$f(x) = x + 1$")

    def test_full_graph_factor_to_task(self):
        # expr_const (x^2-1) -> factor -> expr_block -> static_task.statement
        graph = {
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "x^2-1", "vars": ["x"]}},
                {"id": "f", "type": "factor"},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "x^2-1"}},
                {"id": "st", "type": "static_task"},
                # answer chain
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "f:in"},
                {"from": "f:out", "to": "blk:in"},
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
            r"$x^2-1 = \left(x - 1\right) \left(x + 1\right)$")


if __name__ == "__main__":
    unittest.main()
