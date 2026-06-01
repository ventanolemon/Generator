"""
Тесты: краткие описания узлов и случайная инициализация новых типов.

Описания — headless; подстановка случайных значений в matrix/expr/ode_const и
полный граф генерации — под Qt (matrix_block тянет блоки).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.symbolic import substitute_values, to_latex

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


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


# ---------------- Описания ----------------

class DescriptionTests(unittest.TestCase):
    def test_every_node_has_description(self):
        missing = [e["type_id"] for e in DEFAULT_REGISTRY.palette()
                   if not e["description"]]
        self.assertEqual(missing, [], f"без описания: {missing}")

    def test_description_in_palette_entry(self):
        e = next(x for x in DEFAULT_REGISTRY.palette() if x["type_id"] == "formula")
        self.assertIn("формул", e["description"].lower())

    def test_class_description_takes_priority(self):
        # matrix_const задаёт description в самом классе — он не должен
        # перетираться словарём.
        from core.graph.nodes.linalg import MatrixConstNode
        self.assertIn("values", MatrixConstNode.description)


# ---------------- Случайная инициализация ----------------

@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SubstituteValuesHelperTests(unittest.TestCase):
    def test_substitute_into_matrix(self):
        from core.graph.symbolic import parse_matrix
        M = parse_matrix("a,1;0,b")
        out = substitute_values(M, {"a": 5, "b": -2})
        import sympy as sp
        self.assertEqual(out, sp.Matrix([[5, 1], [0, -2]]))

    def test_no_values_unchanged(self):
        from core.graph.symbolic import parse_matrix
        M = parse_matrix("a,1;0,b")
        self.assertEqual(substitute_values(M, None), M)
        self.assertEqual(substitute_values(M, {}), M)

    def test_partial_substitution_keeps_symbols(self):
        from core.graph.symbolic import parse_expr
        e = parse_expr("a*x + b", {})
        out = substitute_values(e, {"a": 3})
        # b остаётся символом, a заменён на 3 (порядок слагаемых — на усмотрение sympy)
        self.assertEqual(to_latex(out), "b + 3 x")

    def test_integer_stays_integer(self):
        from core.graph.symbolic import parse_expr
        out = substitute_values(parse_expr("a", {}), {"a": 7})
        import sympy as sp
        self.assertIs(out, sp.Integer(7))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ConstNodeValuesPortTests(unittest.TestCase):
    def test_const_nodes_have_optional_values_input(self):
        for tid in ("matrix_const", "expr_const", "ode_const"):
            e = next(x for x in DEFAULT_REGISTRY.palette() if x["type_id"] == tid)
            names = [n for n, _t in e["inputs"]]
            self.assertIn("values", names, tid)

    def test_matrix_const_substitutes(self):
        from core.graph.nodes.linalg import MatrixConstNode
        out = MatrixConstNode("m", {"data": "a,1;0,b"}).compute(
            {"values": {"a": 4, "b": 9}}, _ctx())["out"]
        import sympy as sp
        self.assertEqual(out, sp.Matrix([[4, 1], [0, 9]]))

    def test_matrix_const_literal_without_values(self):
        from core.graph.nodes.linalg import MatrixConstNode
        out = MatrixConstNode("m", {"data": "1,2;3,4"}).compute({}, _ctx())["out"]
        import sympy as sp
        self.assertEqual(out, sp.Matrix([[1, 2], [3, 4]]))

    def test_expr_const_substitutes(self):
        from core.graph.nodes.symbolic import ExprConstNode
        out = ExprConstNode("e", {"expr": "a*x^2+b", "vars": ["a", "b", "x"]}).compute(
            {"values": {"a": 2, "b": -3}}, _ctx())["out"]
        self.assertEqual(to_latex(out), "2 x^{2} - 3")

    def test_ode_const_substitutes(self):
        from core.graph.nodes.ode import OdeConstNode
        out = OdeConstNode("o", {"equation": "y'' + k*y = 0"}).compute(
            {"values": {"k": 4}}, _ctx())["out"]
        self.assertIn("4", to_latex(out))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RandomPolynomialTests(unittest.TestCase):
    def test_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("random_polynomial"))

    def test_degree_exact(self):
        import sympy as sp
        from core.graph.nodes.symbolic import RandomPolynomialNode
        x = sp.Symbol("x")
        out = RandomPolynomialNode("p", {"var": "x", "degree": 3, "min": -3, "max": 3}).compute(
            {}, _ctx(1))["out"]
        self.assertEqual(sp.degree(out, x), 3)

    def test_reproducible(self):
        from core.graph.nodes.symbolic import RandomPolynomialNode
        a = RandomPolynomialNode("p", {"degree": 2}).compute({}, _ctx(5))["out"]
        b = RandomPolynomialNode("p", {"degree": 2}).compute({}, _ctx(5))["out"]
        self.assertEqual(a, b)


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class GenerationPipelineTests(unittest.TestCase):
    def test_random_matrix_via_var_dict(self):
        # random_natural ×3 -> var_dict -> matrix_const 'a,b;c,1' -> block -> task
        graph = {
            "nodes": [
                {"id": "ra", "type": "random_natural", "params": {"min": 1, "max": 9}},
                {"id": "rb", "type": "random_natural", "params": {"min": 1, "max": 9}},
                {"id": "rc", "type": "random_natural", "params": {"min": 1, "max": 9}},
                {"id": "vd", "type": "var_dict", "params": {"names": ["a", "b", "c"]}},
                {"id": "mc", "type": "matrix_const", "params": {"data": "a,b;c,1"}},
                {"id": "blk", "type": "matrix_block", "params": {"prefix": "A"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "abl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "ra:out", "to": "vd:a"},
                {"from": "rb:out", "to": "vd:b"},
                {"from": "rc:out", "to": "vd:c"},
                {"from": "vd:out", "to": "mc:values"},
                {"from": "mc:out", "to": "blk:in"},
                {"from": "blk:out", "to": "sbl:in0"},
                {"from": "sbl:out", "to": "st:statement"},
                {"from": "az:out", "to": "avd:z"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "abl:in0"},
                {"from": "abl:out", "to": "st:answer"},
            ],
            "meta": {"seed": 7},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        # все элементы — числа из [1;9], '1' в правом нижнем углу
        plain = task.statement[0].render_plain()
        self.assertTrue(plain.startswith(r"$A = \begin{pmatrix}"))

    def test_two_seeds_differ(self):
        # Разные seed дают разные матрицы (с подавляющей вероятностью).
        def gen(seed):
            graph = {
                "nodes": [
                    {"id": "ra", "type": "random_natural", "params": {"min": 1, "max": 50}},
                    {"id": "vd", "type": "var_dict", "params": {"names": ["a"]}},
                    {"id": "mc", "type": "matrix_const", "params": {"data": "a,0;0,a"}},
                    {"id": "blk", "type": "matrix_block", "params": {}},
                    {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                    {"id": "st", "type": "static_task"},
                    {"id": "az", "type": "constant_number", "params": {"value": 1}},
                    {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                    {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                    {"id": "atb", "type": "text_block"},
                    {"id": "abl", "type": "block_list", "params": {"count": 1}},
                ],
                "edges": [
                    {"from": "ra:out", "to": "vd:a"},
                    {"from": "vd:out", "to": "mc:values"},
                    {"from": "mc:out", "to": "blk:in"},
                    {"from": "blk:out", "to": "sbl:in0"},
                    {"from": "sbl:out", "to": "st:statement"},
                    {"from": "az:out", "to": "avd:z"},
                    {"from": "avd:out", "to": "atpl:vars"},
                    {"from": "atpl:out", "to": "atb:text"},
                    {"from": "atb:out", "to": "abl:in0"},
                    {"from": "abl:out", "to": "st:answer"},
                ],
                "meta": {"seed": seed},
            }
            return GraphExecutor(GraphSpec.parse(graph)).run().statement[0].render_plain()

        results = {gen(s) for s in range(6)}
        self.assertGreater(len(results), 1)


if __name__ == "__main__":
    unittest.main()
