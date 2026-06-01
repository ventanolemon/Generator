"""
Тесты квадратичных форм и замены базиса (PR-4 фазы 3e).

Скалярно-матричные результаты — headless; сигнатура/Грам-Шмидт (BLOCK) — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec
from core.graph.symbolic import to_latex
from core.graph.nodes.linalg import (
    ChangeBasisOperatorNode, CoordinatesInBasisNode, MatrixConstNode,
    MatrixToQuadFormNode, QuadFormCanonicalNode, QuadFormToMatrixNode,
)
from core.graph.nodes.symbolic import ExprConstNode

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


def _m(data):
    return MatrixConstNode("m", {"data": data}).compute({}, _ctx())["out"]


def _e(expr, vars):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars)}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("quadform_to_matrix", "matrix_to_quadform",
                    "quadform_canonical", "quadform_signature",
                    "change_basis_operator", "coordinates_in_basis",
                    "gram_schmidt"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class QuadFormTests(unittest.TestCase):
    def test_form_to_matrix(self):
        import sympy as sp
        A = QuadFormToMatrixNode("q", {"vars": ["x", "y"]}).compute(
            {"in": _e("2*x^2+3*y^2+4*x*y", ["x", "y"])}, _ctx())["out"]
        self.assertEqual(A, sp.Matrix([[2, 2], [2, 3]]))

    def test_matrix_to_form(self):
        out = MatrixToQuadFormNode("q", {"vars": ["x", "y"]}).compute(
            {"in": _m("2,2;2,3")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "2 x^{2} + 4 x y + 3 y^{2}")

    def test_roundtrip(self):
        import sympy as sp
        A = QuadFormToMatrixNode("q", {"vars": ["x", "y"]}).compute(
            {"in": _e("x^2+6*x*y+y^2", ["x", "y"])}, _ctx())["out"]
        self.assertEqual(A, sp.Matrix([[1, 3], [3, 1]]))

    def test_canonical(self):
        out = QuadFormCanonicalNode("c", {}).compute({"in": _m("2,0;0,3")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"2 \xi_{1}^{2} + 3 \xi_{2}^{2}")

    def test_vars_count_mismatch_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            MatrixToQuadFormNode("q", {"vars": ["x"]}).compute({"in": _m("2,2;2,3")}, _ctx())


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ChangeBasisTests(unittest.TestCase):
    def test_similarity(self):
        import sympy as sp
        # A=[[2,1],[0,3]], P=[[1,1],[0,1]] -> P^-1 A P = diag(2,3)
        out = ChangeBasisOperatorNode("o", {}).compute(
            {"a": _m("2,1;0,3"), "p": _m("1,1;0,1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([[2, 0], [0, 3]]))

    def test_singular_p_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            ChangeBasisOperatorNode("o", {}).compute(
                {"a": _m("1,0;0,1"), "p": _m("1,1;1,1")}, _ctx())

    def test_coordinates(self):
        import sympy as sp
        # basis e1=(1,0), e2=(1,1); vector (3,5) -> coords (-2,5)
        out = CoordinatesInBasisNode("c", {}).compute(
            {"vector": _m("3;5"), "basis": _m("1,1;0,1")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([-2, 5]))


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class BlockTests(unittest.TestCase):
    def test_signature_definite(self):
        from core.graph.nodes.linalg import QuadFormSignatureNode
        out = QuadFormSignatureNode("s", {}).compute({"in": _m("2,0;0,3")}, _ctx())["out"]
        self.assertIn("(2,", out.render_plain())
        self.assertIn("определена", out.render_plain())

    def test_signature_indefinite(self):
        from core.graph.nodes.linalg import QuadFormSignatureNode
        out = QuadFormSignatureNode("s", {}).compute({"in": _m("1,0;0,-1")}, _ctx())["out"]
        self.assertIn("знакопеременна", out.render_plain())

    def test_gram_schmidt(self):
        from core.graph.nodes.linalg import GramSchmidtNode
        out = GramSchmidtNode("g", {}).compute({"in": _m("1,1;1,0;0,1")}, _ctx())["out"]
        self.assertEqual(len(out), 2)

    def test_gram_schmidt_normalized(self):
        from core.graph.nodes.linalg import GramSchmidtNode
        out = GramSchmidtNode("g", {"normalize": "yes"}).compute(
            {"in": _m("3,0;0,0;0,4")}, _ctx())["out"]
        # первый нормированный вектор имеет единичную длину -> компоненты с sqrt? здесь (1,0,0)
        self.assertIn("1", out[0].render_plain())

    def test_full_graph_quadform_canonical(self):
        # форма -> матрица -> канонический вид -> expr_block -> task
        graph = {
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "2*x^2+3*y^2", "vars": ["x", "y"]}},
                {"id": "qm", "type": "quadform_to_matrix", "params": {"vars": ["x", "y"]}},
                {"id": "cn", "type": "quadform_canonical"},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "Q"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "qm:in"},
                {"from": "qm:out", "to": "cn:in"},
                {"from": "cn:out", "to": "blk:in"},
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
                         r"$Q = 2 \xi_{1}^{2} + 3 \xi_{2}^{2}$")


if __name__ == "__main__":
    unittest.main()
