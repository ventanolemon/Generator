"""
Наглядность узлов на холсте: сводка содержимого Node.summary() +
узел свёртки списка expr_reduce + символьные алиасы операций expr_binop.

Headless-часть: тексты сводок ключевых узлов, безопасный пробник
GraphDocument.node_summary, семантика expr_reduce (Σ/Π, пустой список),
алиасы '+'/'×'/'^' в expr_binop. Qt-часть (offscreen): NodeItem резервирует
ленту-сводку под заголовком (высота узла растёт, порты сдвигаются вниз)
ТОЛЬКО у узлов с переопределённым summary().

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_graph_summaries
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext, GraphDocument, Node
from core.graph.errors import GraphValidationError, RetryGeneration

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


def _summary(type_id: str, params: dict) -> str:
    return DEFAULT_REGISTRY.get(type_id)("t", params).summary()


class SummaryTextTests(unittest.TestCase):
    """Тексты сводок: то, что пользователь видит на теле узла."""

    def test_constant_number_int_formatted(self):
        self.assertEqual(_summary("constant_number", {"value": 5.0}), "5")

    def test_random_natural_range(self):
        self.assertEqual(_summary("random_natural", {"min": 1, "max": 20}),
                         "1…20")

    def test_random_natural_step(self):
        s = _summary("random_natural", {"min": 10, "max": 100, "step": 10})
        self.assertIn("10…100", s)
        self.assertIn("шаг 10", s)

    def test_formula(self):
        self.assertEqual(_summary("formula", {"expr": "m * a"}), "= m * a")

    def test_var_dict_names(self):
        self.assertEqual(_summary("var_dict", {"names": ["v", "t"]}),
                         "{v, t}")

    def test_text_collapses_whitespace(self):
        s = _summary("text", {"text": "  Найдите   предел\n функции "})
        self.assertEqual(s, "«Найдите предел функции»")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_expr_const_shows_expression(self):
        self.assertEqual(_summary("expr_const", {"expr": "(x+1)^2"}),
                         "(x+1)^2")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_binop_glyphs(self):
        for op, glyph in [("add", "+"), ("sub", "−"), ("mul", "×"),
                          ("div", "÷"), ("pow", "^")]:
            self.assertEqual(_summary("expr_binop", {"op": op}), glyph)

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_reduce_glyphs(self):
        self.assertEqual(_summary("expr_reduce", {"op": "add"}), "Σ")
        self.assertEqual(_summary("expr_reduce", {"op": "mul"}), "Π")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_diff_superscript_order(self):
        self.assertEqual(_summary("diff", {"var": "x", "order": 1}), "d/dx")
        self.assertEqual(_summary("diff", {"var": "x", "order": 2}),
                         "d²/dx²")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_limit_point_and_direction(self):
        self.assertEqual(_summary("limit", {"var": "x", "point": "oo"}),
                         "lim x→∞")
        s = _summary("limit", {"var": "x", "point": "0", "dir": "+"})
        self.assertEqual(s, "lim x→0⁺")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_integrate_bounds(self):
        s = _summary("integrate", {"var": "x", "lower": "0", "upper": "oo"})
        self.assertEqual(s, "∫[0; ∞] dx")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_subs_expr_target(self):
        self.assertEqual(_summary("subs_expr", {"name": "u"}), "u := ●")

    def test_repeat_count_and_body(self):
        s = _summary("repeat", {
            "count": 4,
            "body": {"nodes": [{"id": "a", "type": "text", "params": {}}],
                     "edges": [], "meta": {}},
        })
        self.assertIn("× 4", s)
        self.assertIn("1", s)

    def test_tunnel_arrows(self):
        self.assertEqual(_summary("input_var", {"name": "k"}), "↘ k")
        self.assertEqual(_summary("output_var", {"name": "res"}), "↗ res")

    def test_constraint_words(self):
        s = _summary("constraint", {"kind": "natural", "min": 10, "max": 150})
        self.assertIn("натуральное", s)
        self.assertIn("10…150", s)


class NodeSummaryProbeTests(unittest.TestCase):
    """GraphDocument.node_summary — безопасный пробник для холста."""

    def test_returns_summary_for_node(self):
        doc = GraphDocument()
        n = doc.add_node("random_natural", {"min": 2, "max": 9})
        self.assertEqual(doc.node_summary(n.id), "2…9")

    def test_unknown_node_id_empty(self):
        self.assertEqual(GraphDocument().node_summary("нет-такого"), "")

    def test_broken_params_swallowed(self):
        # Кривые params не должны ронять отрисовку холста: пустая строка.
        doc = GraphDocument()
        n = doc.add_node("random_natural", {"min": 2, "max": 9})
        doc.nodes[n.id].params = {"min": object(), "max": object()}
        self.assertEqual(doc.node_summary(n.id), "")

    def test_base_summary_is_key_value(self):
        # Узел БЕЗ переопределения — базовый формат k=v (fallback инспектора).
        doc = GraphDocument()
        n = doc.add_node("to_block", {"style": "formula"})
        self.assertIn("style=formula", doc.node_summary(n.id))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ExprReduceTests(unittest.TestCase):
    """Свёртка списка выражений: Σ и Π одним узлом вместо цепочки binop."""

    def _node(self, op="mul"):
        return DEFAULT_REGISTRY.get("expr_reduce")("r", {"op": op})

    def _exprs(self, *texts):
        import sympy as sp
        return [sp.sympify(t) for t in texts]

    def test_product_of_three(self):
        import sympy as sp
        out = self._node("mul").compute(
            {"list": self._exprs("x", "x+1", "2")}, _ctx())["out"]
        self.assertEqual(sp.expand(out), sp.expand(2 * sp.Symbol("x")
                                                   * (sp.Symbol("x") + 1)))

    def test_sum_of_three(self):
        import sympy as sp
        out = self._node("add").compute(
            {"list": self._exprs("x", "x**2", "1")}, _ctx())["out"]
        x = sp.Symbol("x")
        self.assertEqual(sp.expand(out - (x + x ** 2 + 1)), 0)

    def test_numbers_coerced_to_expr(self):
        out = self._node("add").compute({"list": [1, 2, 3]}, _ctx())["out"]
        self.assertEqual(int(out), 6)

    def test_single_item_passthrough(self):
        import sympy as sp
        out = self._node("mul").compute(
            {"list": self._exprs("x+1")}, _ctx())["out"]
        self.assertEqual(out, sp.Symbol("x") + 1)

    def test_empty_list_retries(self):
        with self.assertRaises(RetryGeneration):
            self._node("mul").compute({"list": []}, _ctx())

    def test_symbol_aliases_accepted(self):
        # '+' и '*' работают и в expr_reduce.
        out = self._node("+").compute({"list": [2, 3]}, _ctx())["out"]
        self.assertEqual(int(out), 5)
        self._node("+").validate_params()      # не бросает
        with self.assertRaises(GraphValidationError):
            self._node("^").validate_params()  # степень для свёртки не имеет смысла

    def test_registered_in_default_registry(self):
        self.assertTrue(DEFAULT_REGISTRY.has("expr_reduce"))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ExprBinopAliasTests(unittest.TestCase):
    """Символьные алиасы операций: пользователь пишет '+', а не 'add'."""

    def _compute(self, op):
        import sympy as sp
        node = DEFAULT_REGISTRY.get("expr_binop")("b", {"op": op})
        node.validate_params()
        return node.compute({"a": sp.Symbol("x"), "b": sp.Integer(2)},
                            _ctx())["out"]

    def test_plus_alias(self):
        import sympy as sp
        self.assertEqual(self._compute("+"), sp.Symbol("x") + 2)

    def test_unicode_times_alias(self):
        import sympy as sp
        self.assertEqual(self._compute("×"), 2 * sp.Symbol("x"))

    def test_double_star_alias(self):
        import sympy as sp
        self.assertEqual(self._compute("**"), sp.Symbol("x") ** 2)

    def test_unknown_op_rejected(self):
        # Конструктор Node сам зовёт validate_params — кривая операция
        # отклоняется уже при создании узла.
        with self.assertRaises(GraphValidationError):
            DEFAULT_REGISTRY.get("expr_binop")("b", {"op": "%"})

    def test_alias_summary_is_glyph(self):
        node = DEFAULT_REGISTRY.get("expr_binop")("b", {"op": "*"})
        self.assertEqual(node.summary(), "×")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SummaryBandQtTests(unittest.TestCase):
    """Лента-сводка на NodeItem: геометрия и резервирование по классу."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _item(self, type_id: str, params: dict):
        from ui.editors.graph_canvas.items import NodeItem
        doc = GraphDocument()
        node = doc.add_node(type_id, params)
        entry = next(e for e in DEFAULT_REGISTRY.palette()
                     if e["type_id"] == type_id)
        return NodeItem(doc, node.id, entry)

    def test_band_reserved_for_summary_node(self):
        from ui.editors.graph_canvas import style
        item = self._item("expr_binop", {"op": "mul"})
        plain = self._item("to_block", {})       # без своего summary()
        self.assertTrue(item._summary_reserved)
        self.assertFalse(plain._summary_reserved)
        self.assertAlmostEqual(
            item.boundingRect().height() - plain.boundingRect().height(),
            style.SUMMARY_H
            + (item._row_count() - plain._row_count()) * style.ROW_H)

    def test_ports_shift_below_band(self):
        from ui.editors.graph_canvas import style
        item = self._item("expr_binop", {"op": "add"})
        y_first = item.in_ports[0].pos().y()
        self.assertAlmostEqual(
            y_first, style.HEADER_H + style.SUMMARY_H + style.ROW_H / 2)

    def test_no_band_no_shift(self):
        from ui.editors.graph_canvas import style
        item = self._item("to_block", {})
        y_first = item.in_ports[0].pos().y()
        self.assertAlmostEqual(y_first, style.HEADER_H + style.ROW_H / 2)

    def test_band_survives_rebuild_ports(self):
        from ui.editors.graph_canvas import style
        item = self._item("expr_reduce", {"op": "add"})
        item.rebuild_ports()
        self.assertAlmostEqual(
            item.in_ports[0].pos().y(),
            style.HEADER_H + style.SUMMARY_H + style.ROW_H / 2)

    def test_paint_offscreen_smoke(self):
        # Полный paint в картинку: сводка-глиф не должна ничего ронять.
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtWidgets import QGraphicsScene
        item = self._item("expr_reduce", {"op": "mul"})
        scene = QGraphicsScene()
        scene.addItem(item)
        img = QImage(300, 200, QImage.Format.Format_ARGB32)
        img.fill(0)
        p = QPainter(img)
        scene.render(p, QRectF(0, 0, 300, 200))
        p.end()

    def test_override_detection_matches_base(self):
        # Санити контракта: у to_block summary — базовый, у expr_binop — свой.
        self.assertIs(DEFAULT_REGISTRY.get("to_block").summary, Node.summary)
        self.assertIsNot(DEFAULT_REGISTRY.get("expr_binop").summary,
                         Node.summary)


if __name__ == "__main__":
    unittest.main()
