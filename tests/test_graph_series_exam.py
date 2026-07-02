"""
Тесты контрольной по рядам (exercises/graph_examples/series_exam) и
расширений языка, сделанных под неё:

  * select поддерживает expr/matrix/list (выбор между структурами условия);
  * туннели/импорты циклов переносят expr/matrix;
  * substitute_values сопоставляет символы по имени (предположения не мешают);
  * compare принимает правый операнд параметром b (без узла-константы).

Семантика генераторов проверяется по выходам узлов (run_full): вердикт №2
пересчитывается из параметров, категория №3 сверяется с текстом ответа,
разложение №7 проверяется тождеством sympy.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.nodes.control import CompareNode, SelectNode
from exercises.graph_examples.series_exam import (
    SERIES_EXAM, generate_variant, series_exam_names,
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


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


def _spec(name: str, seed=None) -> GraphSpec:
    import copy
    raw = copy.deepcopy(SERIES_EXAM[name]["graph"])
    if seed is not None:
        raw.setdefault("meta", {})["seed"] = seed
    return GraphSpec.parse(raw)


def _plain(task) -> str:
    return " | ".join(
        getattr(b, "latex", None) or b.render_plain()
        for b in list(task.statement) + list(task.answer)
    )


class LanguageExtensionTests(unittest.TestCase):
    def test_compare_with_param_b(self):
        n = CompareNode("c", {"op": "<", "b": 1})
        self.assertTrue(n.compute({"a": 0.5}, _ctx())["out"])
        self.assertFalse(n.compute({"a": 2.0}, _ctx())["out"])

    def test_compare_wired_b_takes_priority(self):
        n = CompareNode("c", {"op": "<", "b": 1})
        self.assertTrue(n.compute({"a": 5, "b": 10}, _ctx())["out"])

    def test_select_expr_type(self):
        n = SelectNode("s", {"value_type": "expr"})
        self.assertEqual(n.input_ports()[1].type, PortType.EXPR)
        self.assertEqual(n.output_ports()[0].type, PortType.EXPR)

    def test_select_matrix_and_list_types(self):
        self.assertEqual(SelectNode("s", {"value_type": "matrix"})
                         .output_ports()[0].type, PortType.MATRIX)
        self.assertEqual(SelectNode("s", {"value_type": "list"})
                         .output_ports()[0].type, PortType.LIST)

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_tunnel_carries_expr(self):
        spec = {
            "nodes": [{"id": "rep", "type": "repeat", "params": {
                "count": 2, "outputs": ["e:expr:last"], "body": {
                    "nodes": [
                        {"id": "c", "type": "expr_const",
                         "params": {"expr": "x**2 + 1"}},
                        {"id": "ov", "type": "output_var",
                         "params": {"name": "e", "type": "expr"}},
                    ],
                    "edges": [{"from": "c:out", "to": "ov:value"}],
                }}}],
            "edges": [],
        }
        import sympy as sp
        outs = GraphExecutor(GraphSpec.parse(spec)).run_full()
        self.assertEqual(outs["rep"]["e"], sp.Symbol("x") ** 2 + 1)

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_substitute_values_matches_by_name(self):
        from core.graph.symbolic import (
            build_symbols, parse_expr, substitute_values,
        )
        syms = build_symbols(["n", "a"], "positive")   # символы с предположениями
        e = parse_expr("a**n", syms)
        out = substitute_values(e, {"a": 5.0})
        self.assertEqual(str(out), "5**n")


class SeriesExamStructureTests(unittest.TestCase):
    def test_eight_tasks(self):
        self.assertEqual(len(series_exam_names()), 8)

    def test_all_assemble_with_final(self):
        for name in series_exam_names():
            with self.subTest(task=name):
                ex = GraphExecutor(_spec(name))
                self.assertIsNotNone(ex.result, name)


@unittest.skipUnless(HAS_QT and HAS_SYMPY, "нужны PyQt6 и sympy")
class SeriesExamExecutionTests(unittest.TestCase):
    def test_all_run_over_seeds(self):
        for seed in (0, 1, 2):
            for name in series_exam_names():
                with self.subTest(task=name, seed=seed):
                    task = GraphExecutor(_spec(name, seed)).run()
                    self.assertTrue(task.statement, name)
                    self.assertTrue(task.answer, name)
                    self.assertTrue(_plain(task).strip())

    def test_s1_branch_matches_verdict(self):
        for seed in range(6):
            outs = GraphExecutor(_spec("s1_comparison", seed)).run_full()
            d = outs["d"]["out"]
            answer = outs["ans"]["out"].render_plain()
            if d == 1:
                self.assertIn("Сходится", answer)
            else:
                self.assertIn("Расходится", answer)

    def test_s2_verdict_matches_recomputed_limit(self):
        for seed in range(6):
            outs = GraphExecutor(_spec("s2_dalambert", seed)).run_full()
            a, b, c = (outs[k]["out"] for k in ("a", "b", "c"))
            L = a ** b / c ** c
            self.assertNotAlmostEqual(L, 1.0)     # guard отсёк L=1
            answer = outs["ans"]["out"].render_plain()
            self.assertIn("Сходится" if L < 1 else "Расходится", answer)

    def test_s3_category_matches_answer(self):
        seen = set()
        for seed in range(10):
            outs = GraphExecutor(_spec("s3_leibniz", seed)).run_full()
            k = int(outs["k"]["out"])
            seen.add(k)
            answer = outs["ans"]["out"].render_plain()
            expected = {0: "абсолютно", 1: "условно", 2: "Расходится"}[k]
            self.assertIn(expected, answer)
        self.assertGreaterEqual(len(seen), 2)      # категории реально меняются

    def test_s7_partial_fractions_identity(self):
        import sympy as sp
        for seed in range(4):
            outs = GraphExecutor(_spec("s7_rational", seed)).run_full()
            A, B = outs["A"]["out"], outs["B"]["out"]
            p, q = outs["pp"]["out"], outs["qq"]["out"]
            self.assertNotEqual(p, q)              # guard отсёк кратный полюс
            x = sp.Symbol("x")
            f = outs["fx"]["out"]
            manual = sp.Integer(int(A)) / (x + int(p)) + sp.Integer(int(B)) / (x + int(q))
            self.assertEqual(sp.simplify(f - manual), 0)

    def test_s4_interval_consistent(self):
        outs = GraphExecutor(_spec("s4_power", 3)).run_full()
        x0, R = outs["x0"]["out"], outs["R"]["out"]
        self.assertEqual(outs["lo"]["out"], x0 - R)
        self.assertEqual(outs["hi"]["out"], x0 + R)

    def test_s5_majorant_exponent_above_one(self):
        for seed in range(4):
            outs = GraphExecutor(_spec("s5_weierstrass", seed)).run_full()
            self.assertGreater(outs["s"]["out"], 1.0)

    def test_variant_generation(self):
        v = generate_variant(7)
        self.assertEqual(len(v), 8)
        for title, task in v:
            self.assertTrue(title)
            self.assertTrue(task.statement)
            self.assertTrue(task.answer)

    def test_variant_reproducible_and_diverse(self):
        a = [_plain(t) for _n, t in generate_variant(5)]
        b = [_plain(t) for _n, t in generate_variant(5)]
        c = [_plain(t) for _n, t in generate_variant(6)]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


if __name__ == "__main__":
    unittest.main()
