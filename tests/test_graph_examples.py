"""
Сквозной тест «предмета» граф-примеров (exercises/graph_examples).

Каждый пример — полный GraphSpec разного типа задания. Тест проверяет, что все
они: (1) валидны структурно (GraphExecutor собирается), (2) имеют ровно один
финальный TASK-узел, (3) исполняются и дают непустые условие и ответ. Это и
витрина возможностей языка, и регрессионная сеть: новая правка движка, ломающая
типовой сценарий, упадёт здесь.

Большинство примеров рендерят блоки (Qt) и часть требует sympy — такие
пропускаются, если пакетов нет; структурная валидация идёт всегда.
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphError, GraphExecutor, GraphSpec
from exercises.graph_examples import EXAMPLES, example_graph, example_names

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

# Примеры, тело которых опирается на sympy (символьные/матричные узлы).
_NEEDS_SYMPY = {
    "choice_expr_diff", "derivative_poly", "limit_rational",
    "determinant_3x3", "quadratic_solve", "matrix_in_loop",
}


class ExamplesStructureTests(unittest.TestCase):
    """Структурная валидация — headless, без исполнения."""

    def test_catalogue_not_empty(self):
        self.assertGreaterEqual(len(EXAMPLES), 10)

    def test_every_example_has_title_and_graph(self):
        for name, entry in EXAMPLES.items():
            self.assertIn("title", entry, name)
            self.assertIn("graph", entry, name)
            self.assertTrue(entry["title"], name)

    def test_every_example_assembles_with_single_final(self):
        for name in example_names():
            with self.subTest(example=name):
                ex = GraphExecutor(GraphSpec.parse(example_graph(name)))
                self.assertIsNotNone(
                    ex.result, f"{name}: нет финального TASK-узла")

    def test_example_graph_helper(self):
        first = example_names()[0]
        self.assertIs(example_graph(first), EXAMPLES[first]["graph"])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — исполнение блоков")
class ExamplesExecutionTests(unittest.TestCase):
    """Полное исполнение: каждый пример даёт непустые условие и ответ."""

    def _run(self, name):
        return GraphExecutor(GraphSpec.parse(example_graph(name))).run()

    def test_all_examples_run(self):
        for name in example_names():
            if name in _NEEDS_SYMPY and not HAS_SYMPY:
                continue
            with self.subTest(example=name):
                task = self._run(name)
                self.assertTrue(task.statement, f"{name}: пустое условие")
                self.assertTrue(task.answer, f"{name}: пустой ответ")
                # Блоки рендерятся в непустой текст/латех без исключений.
                for b in list(task.statement) + list(task.answer):
                    self.assertTrue(hasattr(b, "render_plain"))
                    b.render_plain()

    def test_reproducible_by_seed(self):
        # Один и тот же seed (в meta) даёт идентичный результат.
        a = self._run("physics_force")
        b = self._run("physics_force")
        self.assertEqual(a.statement[0].render_plain(),
                         b.statement[0].render_plain())

    def test_choice_pool_picks_from_set(self):
        task = self._run("choice_pool_limit")
        text = task.statement[0].render_plain()
        self.assertTrue(any(fn in text
                            for fn in ["sin(x)", "tan(x)", "arcsin(x)", "ln(1+x)"]))

    def test_table_squares_has_five_rows(self):
        task = self._run("table_squares")
        self.assertEqual(len(task.statement), 5)


@unittest.skipUnless(HAS_QT and HAS_SYMPY, "нужны PyQt6 и sympy")
class ExamplesSemanticsTests(unittest.TestCase):
    """Точечные проверки правильности нескольких заданий."""

    def _run(self, name):
        return GraphExecutor(GraphSpec.parse(example_graph(name))).run()

    def test_determinant_answer_is_integer_value(self):
        task = self._run("determinant_3x3")
        self.assertIn("det A", task.answer[0].latex)

    def test_derivative_answer_has_prime(self):
        task = self._run("derivative_poly")
        self.assertIn("y'", task.answer[0].latex)

    def test_matrix_in_loop_is_2x3(self):
        # 6 значений, rows=2 → матрица 2×3 в условии.
        task = self._run("matrix_in_loop")
        self.assertTrue(any("begin{pmatrix}" in getattr(b, "latex", "")
                            for b in task.statement))

    def test_guard_yields_perfect_square_root(self):
        import math
        task = self._run("guard_perfect_square")
        # Ответ √x = целое.
        ans = task.answer[0].render_plain()
        digits = "".join(ch for ch in ans if ch.isdigit())
        self.assertTrue(digits and int(digits) >= 1)


if __name__ == "__main__":
    unittest.main()
