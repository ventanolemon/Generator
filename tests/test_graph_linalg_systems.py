"""
Тесты линейной алгебры (PR-2 фазы 3e): системы и операторы.

rref/charpoly — headless; eigen/nullspace/linsolve дают BLOCK_LIST → под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec
from core.graph.symbolic import to_latex
from core.graph.nodes.linalg import (
    CharPolyNode, MatrixConstNode, RrefNode,
)
from core.graph.nodes.symbolic import SymbolNode

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


def _sym(name):
    return SymbolNode("s", {"name": name}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("matrix_rref", "matrix_charpoly", "matrix_eigenvalues",
                    "matrix_eigenvectors", "matrix_nullspace", "matrix_linsolve"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RrefCharpolyTests(unittest.TestCase):
    def test_rref(self):
        out = RrefNode("r", {}).compute({"in": _m("1,2,3;2,4,6")}, _ctx())["out"]
        import sympy as sp
        self.assertEqual(out, sp.Matrix([[1, 2, 3], [0, 0, 0]]))

    def test_charpoly(self):
        out = CharPolyNode("c", {}).compute(
            {"in": _m("2,0;1,3"), "var": _sym("lambda")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\lambda^{2} - 5 \lambda + 6")

    def test_charpoly_non_square_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            CharPolyNode("c", {}).compute(
                {"in": _m("1,2,3;4,5,6"), "var": _sym("x")}, _ctx())


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class EigenTests(unittest.TestCase):
    def test_eigenvalues_with_multiplicity(self):
        from core.graph.nodes.linalg import EigenvaluesNode
        out = EigenvaluesNode("e", {}).compute({"in": _m("2,0,0;1,3,0;0,1,2")}, _ctx())["out"]
        texts = [b.render_plain() for b in out]
        self.assertEqual(len(texts), 2)
        self.assertTrue(any("кратность" in t and "2" in t for t in texts))

    def test_eigenvectors(self):
        from core.graph.nodes.linalg import EigenvectorsNode
        out = EigenvectorsNode("e", {}).compute({"in": _m("2,0;0,3")}, _ctx())["out"]
        texts = [b.render_plain() for b in out]
        self.assertEqual(len(texts), 2)
        self.assertTrue(all("lambda" in t for t in texts))

    def test_nullspace_basis(self):
        from core.graph.nodes.linalg import NullspaceNode
        out = NullspaceNode("n", {}).compute({"in": _m("1,2,3;2,4,6")}, _ctx())["out"]
        # ранг 1, 3 столбца -> ядро размерности 2
        self.assertEqual(len(out), 2)

    def test_nullspace_trivial(self):
        from core.graph.nodes.linalg import NullspaceNode
        out = NullspaceNode("n", {}).compute({"in": _m("1,0;0,1")}, _ctx())["out"]
        self.assertEqual(len(out), 1)
        self.assertIn("vec{0}", out[0].render_plain())

    def test_linsolve_unique(self):
        from core.graph.nodes.linalg import LinSolveNode
        out = LinSolveNode("l", {}).compute(
            {"a": _m("2,1;1,3"), "b": _m("3;5")}, _ctx())["out"]
        self.assertEqual(len(out), 1)
        self.assertIn("frac{4}{5}", out[0].render_plain())

    def test_full_graph_eigenvalues(self):
        # matrix_const -> eigenvalues -> static_task.statement
        graph = {
            "nodes": [
                {"id": "m", "type": "matrix_const", "params": {"data": "2,0;0,3"}},
                {"id": "ev", "type": "matrix_eigenvalues", "params": {"prefix": "\\lambda"}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "m:out", "to": "ev:in"},
                {"from": "ev:out", "to": "st:statement"},
                {"from": "az:out", "to": "avd:w"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "st:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual([b.render_plain() for b in task.statement],
                         [r"$\lambda = 2$", r"$\lambda = 3$"])


if __name__ == "__main__":
    unittest.main()
