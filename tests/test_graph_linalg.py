"""
Тесты линейной алгебры (PR-1 фазы 3e): матрицы — источники, алгебра, рендер.

Операции — headless через sympy; рендер MATRIX→BLOCK (pmatrix) и полный граф —
под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.port_types import is_compatible
from core.graph.symbolic import to_latex
from core.graph.nodes.linalg import (
    DeterminantNode, IdentityNode, InverseNode, MatrixAddNode, MatrixConstNode,
    MatrixMultiplyNode, MatrixPowerNode, RandomMatrixNode, RankNode,
    ScalarMultiplyNode, TraceNode, TransposeNode,
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


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


def _m(data):
    return MatrixConstNode("m", {"data": data}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class PortTypeTests(unittest.TestCase):
    def test_matrix_type_exists(self):
        self.assertTrue(hasattr(PortType, "MATRIX"))
        self.assertEqual(PortType.MATRIX.value, "matrix")

    def test_matrix_not_compatible_with_expr(self):
        # Матрица и скалярное выражение — разные типы, провод недопустим.
        self.assertFalse(is_compatible(PortType.MATRIX, PortType.EXPR))
        self.assertTrue(is_compatible(PortType.MATRIX, PortType.MATRIX))

    def test_linalg_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()
               if e["category"] == "linalg"}
        for tid in ("matrix_const", "random_matrix", "identity", "matrix_det",
                    "matrix_inv", "matrix_transpose", "matrix_rank",
                    "matrix_trace", "matrix_scalar", "matrix_power",
                    "matrix_mul", "matrix_add", "matrix_block"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class SourceTests(unittest.TestCase):
    def test_const_parse(self):
        self.assertEqual(_m("1,2;3,4").shape, (2, 2))

    def test_column_vector(self):
        self.assertEqual(_m("1;2;3").shape, (3, 1))

    def test_ragged_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            MatrixConstNode("m", {"data": "1,2;3"})

    def test_identity(self):
        out = IdentityNode("i", {"size": 3}).compute({}, _ctx())["out"]
        self.assertEqual(out, __import__("sympy").eye(3))

    def test_random_shape(self):
        out = RandomMatrixNode("r", {"rows": 2, "cols": 4}).compute({}, _ctx())["out"]
        self.assertEqual(out.shape, (2, 4))

    def test_random_invertible(self):
        out = RandomMatrixNode("r", {"rows": 3, "cols": 3, "invertible": "yes"}).compute(
            {}, _ctx(5))["out"]
        self.assertNotEqual(out.det(), 0)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class UnaryOpTests(unittest.TestCase):
    def test_determinant(self):
        self.assertEqual(to_latex(DeterminantNode("d", {}).compute({"in": _m("2,1;1,3")}, _ctx())["out"]), "5")

    def test_det_non_square_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            DeterminantNode("d", {}).compute({"in": _m("1,2,3;4,5,6")}, _ctx())

    def test_inverse(self):
        import sympy as sp
        out = InverseNode("i", {}).compute({"in": _m("2,1;1,3")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[sp.Rational(3, 5), sp.Rational(-1, 5)],
                                         [sp.Rational(-1, 5), sp.Rational(2, 5)]]))

    def test_inverse_singular_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            InverseNode("i", {}).compute({"in": _m("1,2;2,4")}, _ctx())

    def test_transpose(self):
        out = TransposeNode("t", {}).compute({"in": _m("1,2,3;4,5,6")}, _ctx())["out"]
        self.assertEqual(out.shape, (3, 2))

    def test_rank(self):
        self.assertEqual(RankNode("r", {}).compute({"in": _m("1,2;2,4")}, _ctx())["out"], 1.0)

    def test_trace(self):
        self.assertEqual(to_latex(TraceNode("t", {}).compute({"in": _m("2,1;1,3")}, _ctx())["out"]), "5")

    def test_power(self):
        import sympy as sp
        out = MatrixPowerNode("p", {"exponent": 2}).compute({"in": _m("1,1;0,1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[1, 2], [0, 1]]))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class BinaryOpTests(unittest.TestCase):
    def test_multiply(self):
        import sympy as sp
        out = MatrixMultiplyNode("m", {}).compute({"a": _m("1,2;3,4"), "b": _m("1;1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[3], [7]]))

    def test_multiply_mismatch_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            MatrixMultiplyNode("m", {}).compute({"a": _m("1,2;3,4"), "b": _m("1,2,3")}, _ctx())

    def test_add(self):
        import sympy as sp
        out = MatrixAddNode("a", {}).compute({"a": _m("1,2;3,4"), "b": _m("1,0;0,1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[2, 2], [3, 5]]))

    def test_subtract(self):
        import sympy as sp
        out = MatrixAddNode("a", {"op": "sub"}).compute({"a": _m("1,2;3,4"), "b": _m("1,1;1,1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[0, 1], [2, 3]]))

    def test_scalar(self):
        import sympy as sp
        out = ScalarMultiplyNode("s", {}).compute({"in": _m("1,2;3,4"), "k": 3}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[3, 6], [9, 12]]))


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class RenderTests(unittest.TestCase):
    def test_matrix_block_pmatrix(self):
        from core.graph.nodes.linalg import MatrixBlockNode
        out = MatrixBlockNode("b", {"prefix": "A"}).compute({"in": _m("1,2;3,4")}, _ctx())["out"]
        self.assertEqual(out.render_plain(),
                         r"$A = \begin{pmatrix}1 & 2\\3 & 4\end{pmatrix}$")

    def test_full_graph_inverse_to_task(self):
        # matrix_const -> inverse -> matrix_block -> static_task
        graph = {
            "nodes": [
                {"id": "m", "type": "matrix_const", "params": {"data": "2,1;1,1"}},
                {"id": "inv", "type": "matrix_inv"},
                {"id": "blk", "type": "matrix_block", "params": {"prefix": "A^{-1}"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "m:out", "to": "inv:in"},
                {"from": "inv:out", "to": "blk:in"},
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
        self.assertEqual(
            task.statement[0].render_plain(),
            r"$A^{-1} = \begin{pmatrix}1 & -1\\-1 & 2\end{pmatrix}$")


if __name__ == "__main__":
    unittest.main()
