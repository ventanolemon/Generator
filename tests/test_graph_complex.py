"""
Тесты ТФКП (PR-4 фазы 3d): re/im/arg/abs/conjugate/expand_complex/residue/solve.

Операции — headless через sympy; solve→BLOCK_LIST и полный граф — под Qt.
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
    AbsNode, ArgNode, ConjugateNode, ExpandComplexNode, ExprConstNode, ImNode,
    ReNode, ResidueNode, SolveNode, SymbolNode,
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


def _e(expr, vars=("z",), assumptions="complex"):
    return ExprConstNode("e", {"expr": expr, "vars": list(vars),
                               "assumptions": assumptions}).compute({}, _ctx())["out"]


def _x(name="z"):
    return SymbolNode("s", {"name": name}).compute({}, _ctx())["out"]


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class RegistryTests(unittest.TestCase):
    def test_complex_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("re", "im", "arg", "abs", "conjugate", "expand_complex",
                    "residue", "solve"):
            self.assertIn(tid, ids)


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ComponentTests(unittest.TestCase):
    def test_re_im(self):
        self.assertEqual(to_latex(ReNode("n", {}).compute({"in": _e("2+3*I")}, _ctx())["out"]), "2")
        self.assertEqual(to_latex(ImNode("n", {}).compute({"in": _e("2+3*I")}, _ctx())["out"]), "3")

    def test_abs(self):
        self.assertEqual(to_latex(AbsNode("n", {}).compute({"in": _e("3+4*I")}, _ctx())["out"]), "5")

    def test_arg(self):
        self.assertEqual(to_latex(ArgNode("n", {}).compute({"in": _e("1+I")}, _ctx())["out"]),
                         r"\frac{\pi}{4}")

    def test_conjugate(self):
        self.assertEqual(to_latex(ConjugateNode("n", {}).compute({"in": _e("2+3*I")}, _ctx())["out"]),
                         "2 - 3 i")

    def test_i_lowercase_parses(self):
        # 'i' тоже мнимая единица.
        self.assertEqual(to_latex(ReNode("n", {}).compute({"in": _e("5+2*i")}, _ctx())["out"]), "5")

    def test_euler(self):
        expr = _e("exp(I*x)", ("x",), assumptions="real")
        out = ExpandComplexNode("n", {}).compute({"in": expr}, _ctx())["out"]
        self.assertEqual(to_latex(out),
                         r"i \sin{\left(x \right)} + \cos{\left(x \right)}")


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ResidueTests(unittest.TestCase):
    def test_simple_pole(self):
        out = ResidueNode("n", {"point": "I"}).compute(
            {"in": _e("1/(z^2+1)"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), r"- \frac{i}{2}")

    def test_essential_singularity(self):
        # res(exp(z)/z, 0) = 1
        out = ResidueNode("n", {"point": "0"}).compute(
            {"in": _e("exp(z)/z"), "var": _x()}, _ctx())["out"]
        self.assertEqual(to_latex(out), "1")


@unittest.skipUnless(HAS_SYMPY and HAS_QT, "нужны sympy и PyQt6")
class SolveTests(unittest.TestCase):
    def test_roots_to_blocklist(self):
        out = SolveNode("n", {"prefix": "z"}).compute(
            {"in": _e("z^4-1"), "var": _x()}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in out],
                         ["$z = -1$", "$z = 1$", "$z = - i$", "$z = i$"])

    def test_quadratic_no_prefix(self):
        out = SolveNode("n", {}).compute({"in": _e("z^2+1"), "var": _x()}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in out], ["$- i$", "$i$"])

    def test_solve_in_full_graph(self):
        # solve z^2+1 -> BLOCK_LIST прямо в statement задачи.
        graph = {
            "nodes": [
                {"id": "z", "type": "symbol", "params": {"name": "z"}},
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "z^2+1", "vars": ["z"]}},
                {"id": "sol", "type": "solve", "params": {"prefix": "z"}},
                {"id": "st", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["w"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "sol:in"},
                {"from": "z:out", "to": "sol:var"},
                {"from": "sol:out", "to": "st:statement"},
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
                         ["$z = - i$", "$z = i$"])


if __name__ == "__main__":
    unittest.main()
