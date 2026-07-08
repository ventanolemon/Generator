"""
Тесты полиморфной подстановки (expr_subs) и символьных функций
(expr_lambda / expr_call). Headless через sympy + сборка полного графа
исполнителем.

Новое:
  * expr_subs теперь принимает не только числа (values: NUMBER_DICT), но и
    выражения — через именованные входы по списку `vars`. Так одно выражение
    подставляется в другое «в качестве переменной».
  * FUNC-порт: expr_lambda упаковывает тело+параметры в функцию, expr_call
    подставляет аргументы (число ИЛИ выражение). Одну функцию можно вызвать
    несколько раз (переиспользование).
"""

from __future__ import annotations
import random
import unittest

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.symbolic import GraphFunction, parse_expr
from core.graph.nodes.symbolic import (
    ExprCallNode, ExprConstNode, ExprLambdaNode, SubstituteNode,
)

try:
    import sympy  # noqa: F401
    HAS_SYMPY = True
except Exception:
    HAS_SYMPY = False


def _ctx():
    return ExecContext(rng=random.Random(0))


def _e(expr, vars):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars)}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class PolymorphicSubsTests(unittest.TestCase):
    def test_func_and_type_registered(self):
        self.assertEqual(PortType.FUNC.value, "func")
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        self.assertLessEqual({"expr_subs", "expr_lambda", "expr_call"}, ids)

    def test_named_input_ports_track_vars(self):
        node = SubstituteNode("s", {"vars": ["u", "w"]})
        names = [p.name for p in node.input_ports()]
        self.assertEqual(names, ["in", "u", "w", "values"])
        # у именованных входов тип ANY (принимают число или выражение)
        kinds = {p.name: p.type for p in node.input_ports()}
        self.assertIs(kinds["u"], PortType.ANY)
        self.assertIs(kinds["in"], PortType.EXPR)

    def test_substitute_expression_for_variable(self):
        # sin(u), u := x**2 + 1  →  sin(x**2 + 1)
        node = SubstituteNode("s", {"vars": ["u"]})
        out = node.compute({"in": _e("sin(u)", ["u"]),
                            "u": _e("x**2+1", ["x"])}, _ctx())["out"]
        self.assertEqual(str(out), "sin(x**2 + 1)")

    def test_mixed_number_and_expression(self):
        # a*x + b, a := 3 (число), b := x - 1 (выражение) → 4*x - 1
        node = SubstituteNode("s", {"vars": ["a", "b"]})
        out = node.compute({"in": _e("a*x+b", ["a", "b", "x"]),
                            "a": 3, "b": _e("x-1", ["x"])}, _ctx())["out"]
        self.assertEqual(sympy.simplify(out - (4 * sympy.Symbol("x") - 1)), 0)

    def test_named_input_overrides_values_bundle(self):
        # values даёт a=1; именованный вход a=9 приоритетнее.
        node = SubstituteNode("s", {"vars": ["a"]})
        out = node.compute({"in": _e("a", ["a"]), "a": 9,
                            "values": {"a": 1}}, _ctx())["out"]
        self.assertEqual(int(out), 9)

    def test_legacy_values_only_still_numeric(self):
        # Без vars — прежнее поведение: подстановка чисел из values.
        node = SubstituteNode("s", {})
        out = node.compute({"in": _e("a*x+b", ["a", "b", "x"]),
                            "values": {"a": 2, "b": 5}}, _ctx())["out"]
        self.assertEqual(str(out), "2*x + 5")

    def test_integer_number_stays_exact(self):
        # 2.0 из NUMBER-провода не должно «плыть» — a=2 (Integer), не 2.0.
        node = SubstituteNode("s", {"vars": ["a"]})
        out = node.compute({"in": _e("a/2", ["a"]), "a": 4.0}, _ctx())["out"]
        self.assertEqual(out, 2)
        self.assertTrue(getattr(out, "is_integer", False))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class FunctionNodeTests(unittest.TestCase):
    def test_lambda_requires_params(self):
        from core.graph.errors import GraphValidationError
        with self.assertRaises(GraphValidationError):
            ExprLambdaNode("f", {"params": []}).validate_params()

    def test_lambda_produces_function(self):
        f = ExprLambdaNode("f", {"params": ["t"]}).compute(
            {"body": _e("t**2 + 1", ["t"])}, _ctx())["out"]
        self.assertIsInstance(f, GraphFunction)
        self.assertEqual(f.params, ("t",))

    def test_call_substitutes_expression_argument(self):
        f = GraphFunction(params=("t",), body=_e("t**2 + 1", ["t"]))
        out = ExprCallNode("c", {"args": ["t"]}).compute(
            {"func": f, "t": _e("sin(x)", ["x"])}, _ctx())["out"]
        self.assertEqual(sympy.simplify(out - (sympy.sin(sympy.Symbol("x"))**2 + 1)), 0)

    def test_call_rejects_non_function(self):
        from core.graph.errors import RetryGeneration
        with self.assertRaises(RetryGeneration):
            ExprCallNode("c", {"args": ["t"]}).compute({"func": 42}, _ctx())

    def test_reuse_same_function_two_calls(self):
        # f(t)=t+1; вызвать f(x) и f(10) от ОДНОГО определения (переиспользование).
        graph = {
            "version": 1,
            "nodes": [
                {"id": "body", "type": "expr_const",
                 "params": {"expr": "t + 1", "vars": ["t"]}},
                {"id": "f", "type": "expr_lambda", "params": {"params": ["t"]}},
                {"id": "gx", "type": "expr_const",
                 "params": {"expr": "x", "vars": ["x"]}},
                {"id": "n", "type": "constant_number", "params": {"value": 10}},
                {"id": "c1", "type": "expr_call", "params": {"args": ["t"]}},
                {"id": "c2", "type": "expr_call", "params": {"args": ["t"]}},
            ],
            "edges": [
                {"from": "body:out", "to": "f:body"},
                {"from": "f:out", "to": "c1:func"},
                {"from": "gx:out", "to": "c1:t"},
                {"from": "f:out", "to": "c2:func"},
                {"from": "n:out", "to": "c2:t"},
            ],
            "meta": {},
        }
        out = GraphExecutor(GraphSpec.parse(graph)).run_full()
        self.assertEqual(str(out["c1"]["out"]), "x + 1")
        self.assertEqual(int(out["c2"]["out"]), 11)

    def test_call_port_names_track_args(self):
        node = ExprCallNode("c", {"args": ["a", "b"]})
        names = [p.name for p in node.input_ports()]
        self.assertEqual(names, ["func", "a", "b"])
        self.assertIs(node.input_ports()[0].type, PortType.FUNC)


if __name__ == "__main__":
    unittest.main()
