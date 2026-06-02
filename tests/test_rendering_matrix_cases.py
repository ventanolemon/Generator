"""
Тесты рендеринга LaTeX-конструкций, которые matplotlib mathtext не умеет:
матрицы (\\begin{...matrix}) и cases (\\begin{cases}). Рисуются собственной
сеткой в core.rendering. Плюс знак предела (limit_display) — он рендерится
mathtext'ом, проверяем что узел даёт невычисленный lim.

Все рендер-тесты — под Qt (matplotlib + QPixmap).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    import sympy as sp
    HAS_DEPS = True
except Exception:
    HAS_DEPS = False


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и sympy")
class MatrixParseTests(unittest.TestCase):
    def test_parse_default_matrix(self):
        from core.rendering import parse_matrix_latex
        import sympy as sp
        delims, rows, pre, suf = parse_matrix_latex(sp.latex(sp.Matrix([[1, 2], [3, 4]])))
        self.assertEqual(delims, ("[", "]"))      # из \left[
        self.assertEqual(rows, [["1", "2"], ["3", "4"]])

    def test_parse_pmatrix(self):
        from core.rendering import parse_matrix_latex
        import sympy as sp
        delims, rows, pre, suf = parse_matrix_latex(
            sp.latex(sp.Matrix([[1, 2]]), mat_str="pmatrix", mat_delim=""))
        self.assertEqual(delims, ("(", ")"))

    def test_parse_with_prefix(self):
        from core.rendering import parse_matrix_latex
        import sympy as sp
        _d, _r, pre, _s = parse_matrix_latex("A = " + sp.latex(sp.Matrix([[1]])))
        self.assertEqual(pre, "A =")

    def test_non_matrix_returns_none(self):
        from core.rendering import parse_matrix_latex
        self.assertIsNone(parse_matrix_latex("x^2 + 1"))


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и sympy")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _ok(self, latex):
        from core.rendering import latex_to_pixmap
        px = latex_to_pixmap(latex)
        return px is not None and not px.isNull()

    def test_matrix_renders(self):
        import sympy as sp
        self.assertTrue(self._ok(sp.latex(sp.Matrix([[1, 2], [3, 4]]))))

    def test_matrix_with_prefix_renders(self):
        import sympy as sp
        self.assertTrue(self._ok("A^{-1} = " + sp.latex(sp.Matrix([[1, 2], [3, 4]]))))

    def test_pmatrix_renders(self):
        import sympy as sp
        self.assertTrue(self._ok(sp.latex(sp.Matrix([[1], [2], [3]]),
                                          mat_str="pmatrix", mat_delim="")))

    def test_cases_renders(self):
        import sympy as sp
        x, n = sp.symbols("x n")
        self.assertTrue(self._ok(sp.latex(sp.integrate(x**n, x))))

    def test_plain_formula_still_renders(self):
        self.assertTrue(self._ok(r"x^2 + \frac{1}{2}"))

    def test_limit_sign_renders(self):
        self.assertTrue(self._ok(r"\lim_{x \to 0} \frac{\sin x}{x}"))


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и sympy")
class LimitDisplayTests(unittest.TestCase):
    def test_unevaluated_limit(self):
        import sympy as sp
        from core.graph import ExecContext
        from core.graph.nodes.symbolic import ExprConstNode, LimitDisplayNode
        from core.graph.symbolic import to_latex
        ctx = ExecContext(rng=random.Random(0))
        e = ExprConstNode("e", {"expr": "sin(x)/x", "vars": ["x"]}).compute({}, ctx)["out"]
        out = LimitDisplayNode("l", {"point": "0"}).compute(
            {"in": e, "var": sp.Symbol("x")}, ctx)["out"]
        self.assertIn(r"\lim", to_latex(out))

    def test_registered(self):
        from core.graph import DEFAULT_REGISTRY
        self.assertTrue(DEFAULT_REGISTRY.has("limit_display"))


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и sympy")
class RobustnessTests(unittest.TestCase):
    """Доработки по аудиту: устойчивость к некорректному вводу."""

    def _ctx(self):
        from core.graph import ExecContext
        return ExecContext(rng=random.Random(0))

    def test_parse_point_garbage_retries(self):
        # _parse_point с мусором → RetryGeneration, не GraphValidationError
        from core.graph import RetryGeneration
        from core.graph.nodes.symbolic import (
            ExprConstNode, SeriesNode, SymbolNode)
        e = ExprConstNode("e", {"expr": "x", "vars": ["x"]}).compute({}, self._ctx())["out"]
        s = SymbolNode("s", {"name": "x"}).compute({}, self._ctx())["out"]
        with self.assertRaises(RetryGeneration):
            SeriesNode("t", {"point": "@bad@"}).compute({"in": e, "var": s}, self._ctx())

    def test_linsolve_bad_b_retries(self):
        from core.graph import RetryGeneration
        from core.graph.nodes.linalg import LinSolveNode, MatrixConstNode
        def m(s):
            return MatrixConstNode("m", {"data": s}).compute({}, self._ctx())["out"]
        with self.assertRaises(RetryGeneration):
            LinSolveNode("l", {}).compute(
                {"a": m("1,2;3,4"), "b": m("1,2,3")}, self._ctx())

    def test_ode_malformed_ics_ignored(self):
        # НУ без скобок не должно ронять решение — просто игнорируется.
        from core.graph.nodes.ode import OdeConstNode, OdeSolveNode
        eq = OdeConstNode("o", {"equation": "y' = y"}).compute({}, self._ctx())["out"]
        out = OdeSolveNode("s", {"ics": ["y0=1", "garbage"]}).compute(
            {"in": eq}, self._ctx())["out"]
        # решение получено (общее, т.к. кривые НУ отброшены)
        self.assertIsNotNone(out)


if __name__ == "__main__":
    unittest.main()
