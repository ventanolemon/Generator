"""
Тесты контрольной по ТФКП (exercises/graph_examples/complex_exam) и графики.

Новые узлы: complex_points_plot / complex_region_plot (LIST → IMAGE, ленивый
matplotlib), subs_expr (подстановка выражения в выражение), list_concat.
Семантика: тождество r·e^{iφ} = alg в №1 проверяется численно; корни №4
подставляются в уравнение; картинка присутствует в ответах №2–№4.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    ExecContext, GraphError, GraphExecutor, GraphSpec, GraphValidationError,
)
from core.graph.errors import RetryGeneration
from exercises.graph_examples.complex_exam import (
    COMPLEX_EXAM, complex_exam_names, generate_complex_variant,
)

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False

try:
    import sympy  # noqa: F401
    HAS_SYMPY = True
except Exception:
    HAS_SYMPY = False

try:
    import matplotlib  # noqa: F401
    HAS_MPL = True
except Exception:
    HAS_MPL = False

FULL = HAS_QT and HAS_SYMPY and HAS_MPL


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


def _spec(name: str, seed=None) -> GraphSpec:
    import copy
    raw = copy.deepcopy(COMPLEX_EXAM[name]["graph"])
    if seed is not None:
        raw.setdefault("meta", {})["seed"] = seed
    return GraphSpec.parse(raw)


def _has_image(task) -> bool:
    return any(getattr(b, "image", None) is not None for b in task.answer)


@unittest.skipUnless(HAS_MPL, "matplotlib не установлен")
class PlotNodesTests(unittest.TestCase):
    def test_points_plot_returns_pil_image(self):
        from core.graph.nodes.plot import ComplexPointsPlotNode
        img = ComplexPointsPlotNode("p", {}).compute(
            {"points": [1 + 1j, (2, -1), 0.5]}, _ctx())["out"]
        self.assertEqual(type(img).__module__.split(".")[0], "PIL")
        self.assertGreater(img.size[0], 100)

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_points_plot_accepts_sympy_values(self):
        import sympy as sp
        from core.graph.nodes.plot import ComplexPointsPlotNode
        pts = [sp.exp(2 * sp.pi * sp.I * k / 3) for k in range(3)]
        img = ComplexPointsPlotNode("p", {"unit_circle": "yes"}).compute(
            {"points": pts}, _ctx())["out"]
        self.assertGreater(img.size[0], 100)

    def test_points_plot_empty_retries(self):
        from core.graph.nodes.plot import ComplexPointsPlotNode
        with self.assertRaises(RetryGeneration):
            ComplexPointsPlotNode("p", {}).compute({"points": []}, _ctx())

    def test_region_plot_annulus(self):
        from core.graph.nodes.plot import ComplexRegionPlotNode
        img = ComplexRegionPlotNode("r", {"span": 6}).compute(
            {"conds": ["abs(z-2)>1", "abs(z-2)<3", "im(z)>0"]}, _ctx())["out"]
        self.assertGreater(img.size[0], 100)

    def test_region_plot_empty_region_retries(self):
        from core.graph.nodes.plot import ComplexRegionPlotNode
        with self.assertRaises(RetryGeneration):
            ComplexRegionPlotNode("r", {"span": 4}).compute(
                {"conds": ["abs(z)<1", "abs(z)>2"]}, _ctx())

    def test_region_condition_rejects_dangerous_code(self):
        import numpy as np
        from core.graph.nodes.plot import eval_region_condition
        Z = np.zeros((2, 2), dtype=complex)
        for bad in ("__import__('os')", "().__class__", "abs(z).__class__",
                    "open('/etc/passwd')", "lambda: 1"):
            with self.assertRaises(GraphValidationError, msg=bad):
                eval_region_condition(bad, Z)

    def test_region_condition_math_names_work(self):
        import numpy as np
        from core.graph.nodes.plot import eval_region_condition
        xs = np.linspace(-2, 2, 5)
        Z = xs + 0j
        mask = eval_region_condition("abs(z) < 1", Z)
        self.assertEqual(list(mask), [False, False, True, False, False])


class SymbolicAdditionsTests(unittest.TestCase):
    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_subs_expr_substitutes_expression(self):
        # Многобуквенные имена шаблона обязаны быть объявлены (vars/symbols):
        # иначе имплицитное умножение расщепит R0 → R·0. В графах expr_const
        # объявляет их через параметр vars.
        import sympy as sp
        from core.graph.nodes.symbolic import SubsExprNode
        from core.graph.symbolic import build_symbols, parse_expr
        syms = build_symbols(["R0", "F0"])
        t = parse_expr("R0*(cos(F0) + I*sin(F0))", syms)
        n1 = SubsExprNode("s", {"name": "R0"}).compute(
            {"in": t, "value": sp.Integer(4)}, _ctx())["out"]
        n2 = SubsExprNode("s", {"name": "F0"}).compute(
            {"in": n1, "value": sp.pi}, _ctx())["out"]
        self.assertEqual(sp.simplify(n2 + 4), 0)   # 4·(cos π + i sin π) = −4

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_as_expr_integral_float_becomes_integer(self):
        import sympy as sp
        from core.graph.symbolic import as_expr
        self.assertEqual(as_expr(4.0), sp.Integer(4))
        self.assertIsInstance(as_expr(2.5), sp.Float)

    def test_list_concat(self):
        from core.graph.nodes.lists import ListConcatNode
        out = ListConcatNode("c", {}).compute({"a": [1, 2], "b": [3]}, _ctx())
        self.assertEqual(out["out"], [1, 2, 3])


class ComplexExamStructureTests(unittest.TestCase):
    def test_four_tasks(self):
        self.assertEqual(len(complex_exam_names()), 4)

    def test_all_assemble_with_final(self):
        for name in complex_exam_names():
            with self.subTest(task=name):
                ex = GraphExecutor(_spec(name))
                self.assertIsNotNone(ex.result, name)


@unittest.skipUnless(FULL, "нужны PyQt6, sympy и matplotlib")
class ComplexExamExecutionTests(unittest.TestCase):
    def test_all_run_over_seeds(self):
        for seed in (0, 1, 2):
            for name in complex_exam_names():
                with self.subTest(task=name, seed=seed):
                    task = GraphExecutor(_spec(name, seed)).run()
                    self.assertTrue(task.statement)
                    self.assertTrue(task.answer)

    def test_k1_polar_identity_numeric(self):
        import sympy as sp
        for seed in range(6):
            outs = GraphExecutor(_spec("k1_forms", seed)).run_full()
            r, ph, alg = outs["r"]["out"], outs["ph"]["out"], outs["alg"]["out"]
            diff = complex((r * sp.exp(sp.I * ph) - alg).evalf())
            self.assertLess(abs(diff), 1e-6, f"seed={seed}")
            # φ приведён к (−π; π].
            self.assertLessEqual(float(ph.evalf()), 3.15)
            self.assertGreater(float(ph.evalf()), -3.15)

    def test_k2_answer_contains_image(self):
        for seed in range(4):
            task = GraphExecutor(_spec("k2_region", seed)).run()
            self.assertTrue(_has_image(task), f"seed={seed}")

    def test_k3_points_and_image(self):
        for seed in range(4):
            outs = GraphExecutor(_spec("k3_power_values", seed)).run_full()
            pts = outs["loop"]["pts"]
            self.assertGreaterEqual(len(pts), 3)
            fam = outs["fam"]["out"]
            if fam == 1:
                # Все значения (−m)^√p лежат на одной окружности.
                radii = [abs(complex(p.evalf())) for p in pts]
                self.assertAlmostEqual(max(radii), min(radii), places=6)

    def test_k4_roots_satisfy_equation(self):
        import sympy as sp
        for seed in range(6):
            outs = GraphExecutor(_spec("k4_equations", seed)).run_full()
            fam = outs["fam"]["out"]
            pts = outs["loop"]["pts"]
            for z in pts:
                zv = complex(z.evalf())
                if fam == 0:
                    w = complex(outs["W"]["out"].evalf())
                    import cmath
                    self.assertLess(abs(cmath.exp(zv) - w), 1e-6)
                elif fam == 1:
                    a = outs["a4"]["out"]
                    import cmath
                    self.assertLess(abs(cmath.cos(zv) - a), 1e-6)
                else:
                    b = outs["b4"]["out"]
                    import cmath
                    self.assertLess(abs(cmath.sinh(zv) - b), 1e-6)

    def test_variant_generation(self):
        v = generate_complex_variant(3)
        self.assertEqual(len(v), 4)
        for title, task in v:
            self.assertTrue(title and task.statement and task.answer)


if __name__ == "__main__":
    unittest.main()
