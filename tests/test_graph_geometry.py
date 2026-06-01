"""
Тесты вектор-геометрии (PR-3 фазы 3e): произведения, нормы, углы, прямые,
плоскости. Векторы — матрицы-столбцы (тип MATRIX).

Скалярные результаты — headless; каноническая прямая (BLOCK) — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec
from core.graph.symbolic import to_latex
from core.graph.nodes.linalg import (
    CrossProductNode, DotProductNode, MatrixConstNode, NormNode,
    PlaneFromPointNormalNode, PointPlaneDistanceNode, TripleProductNode,
    VectorAngleNode,
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


def _m(data):
    return MatrixConstNode("m", {"data": data}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_geometry_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("vec_dot", "vec_cross", "vec_triple", "vec_norm",
                    "vec_angle", "plane_point_normal", "point_plane_distance",
                    "line_canonical"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ProductTests(unittest.TestCase):
    def test_dot(self):
        out = DotProductNode("d", {}).compute({"a": _m("1;2;3"), "b": _m("4;5;6")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "32")

    def test_dot_mismatch_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            DotProductNode("d", {}).compute({"a": _m("1;2"), "b": _m("1;2;3")}, _ctx())

    def test_cross(self):
        import sympy as sp
        out = CrossProductNode("c", {}).compute({"a": _m("1;2;3"), "b": _m("4;5;6")}, _ctx())["out"]
        self.assertEqual(out, sp.Matrix([-3, 6, -3]))

    def test_cross_requires_3d(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            CrossProductNode("c", {}).compute({"a": _m("1;2"), "b": _m("3;4")}, _ctx())

    def test_triple_unit(self):
        out = TripleProductNode("t", {}).compute(
            {"a": _m("1;0;0"), "b": _m("0;1;0"), "c": _m("0;0;1")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "1")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class MetricTests(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(to_latex(NormNode("n", {}).compute({"in": _m("1;2;3")}, _ctx())["out"]),
                         r"\sqrt{14}")

    def test_angle_perpendicular(self):
        out = VectorAngleNode("a", {}).compute({"a": _m("1;0"), "b": _m("0;1")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{\pi}{2}")

    def test_angle_parallel(self):
        out = VectorAngleNode("a", {}).compute({"a": _m("1;0"), "b": _m("2;0")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "0")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class PlaneTests(unittest.TestCase):
    def test_plane_equation(self):
        out = PlaneFromPointNormalNode("p", {}).compute(
            {"point": _m("1;0;-2"), "normal": _m("2;-1;3")}, _ctx())["out"]
        self.assertEqual(to_latex(out), "2 x - y + 3 z + 4")

    def test_distance(self):
        out = PointPlaneDistanceNode("d", {}).compute(
            {"q": _m("3;3;3"), "p0": _m("1;0;-2"), "normal": _m("2;-1;3")}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"\frac{8 \sqrt{14}}{7}")


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class LineTests(unittest.TestCase):
    def test_canonical_line(self):
        from core.graph.nodes.linalg import LineCanonicalNode
        out = LineCanonicalNode("l", {}).compute(
            {"point": _m("1;0;-2"), "direction": _m("2;3;1")}, _ctx())["out"]
        self.assertEqual(out.render_plain(),
                         r"$\frac{x - 1}{2} = \frac{y}{3} = \frac{z + 2}{1}$")

    def test_full_graph_plane_to_task(self):
        # точка + нормаль -> уравнение плоскости -> expr_block -> task
        graph = {
            "nodes": [
                {"id": "p", "type": "matrix_const", "params": {"data": "1;0;-2"}},
                {"id": "n", "type": "matrix_const", "params": {"data": "2;-1;3"}},
                {"id": "pl", "type": "plane_point_normal"},
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
                {"from": "p:out", "to": "pl:point"},
                {"from": "n:out", "to": "pl:normal"},
                {"from": "pl:out", "to": "blk:in"},
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
        self.assertEqual(task.statement[0].render_plain(), "$2 x - y + 3 z + 4$")


if __name__ == "__main__":
    unittest.main()
