"""
Тесты узла random_choice и полиморфных маркеров текста.

random_choice — «пул вариантов» одним узлом: случайный элемент из набора
(вход LIST или параметр items), приведённый к elem_type. Полиморфные маркеры:
#имя# в template/text принимают не только число, но и строку/выражение —
закрывает паттерн «подставить выбранную функцию в условие».

random_choice и template — headless; text (рендер блока) — под Qt.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.errors import RetryGeneration
from core.graph.nodes.lists import RandomChoiceNode
from core.graph.nodes.compute import TemplateNode, _marker_str

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


class RandomChoiceTests(unittest.TestCase):
    def test_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("random_choice"))

    def test_string_choice_from_items(self):
        n = RandomChoiceNode("c", {"elem_type": "string",
                                   "items": ["sin(x)", "tan(x)", "ln(1+x)"]})
        out = n.compute({}, _ctx(1))["out"]
        self.assertIn(out, ["sin(x)", "tan(x)", "ln(1+x)"])
        self.assertIsInstance(out, str)

    def test_choice_from_list_input(self):
        n = RandomChoiceNode("c", {"elem_type": "number"})
        out = n.compute({"list": [2, 5, 10]}, _ctx(0))["out"]
        self.assertIn(out, [2.0, 5.0, 10.0])
        self.assertIsInstance(out, float)

    def test_list_input_overrides_items(self):
        n = RandomChoiceNode("c", {"elem_type": "string", "items": ["a", "b"]})
        out = n.compute({"list": ["z"]}, _ctx(0))["out"]
        self.assertEqual(out, "z")

    def test_output_port_type_follows_elem_type(self):
        self.assertEqual(RandomChoiceNode("c", {"elem_type": "expr"})
                         .output_ports()[0].type, PortType.EXPR)
        self.assertEqual(RandomChoiceNode("c", {"elem_type": "number"})
                         .output_ports()[0].type, PortType.NUMBER)

    def test_number_elem_from_text_items(self):
        n = RandomChoiceNode("c", {"elem_type": "number", "items": ["7"]})
        self.assertEqual(n.compute({}, _ctx(0))["out"], 7.0)

    def test_bool_elem(self):
        n = RandomChoiceNode("c", {"elem_type": "bool", "items": ["да"]})
        self.assertIs(n.compute({}, _ctx(0))["out"], True)

    def test_empty_set_requests_retry(self):
        with self.assertRaises(RetryGeneration):
            RandomChoiceNode("c", {"elem_type": "string", "items": []}).compute({}, _ctx())

    def test_reproducible_by_seed(self):
        spec = {"elem_type": "string", "items": ["a", "b", "c", "d", "e"]}
        a = RandomChoiceNode("c", dict(spec)).compute({}, _ctx(42))["out"]
        b = RandomChoiceNode("c", dict(spec)).compute({}, _ctx(42))["out"]
        self.assertEqual(a, b)

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_expr_elem_parses_to_sympy(self):
        import sympy as sp
        n = RandomChoiceNode("c", {"elem_type": "expr", "items": ["x**2"]})
        out = n.compute({}, _ctx(0))["out"]
        self.assertEqual(out, sp.Symbol("x")**2)


class MarkerStrTests(unittest.TestCase):
    def test_integer_without_dot(self):
        self.assertEqual(_marker_str(5.0), "5")

    def test_float(self):
        self.assertEqual(_marker_str(2.5), "2.5")

    def test_string_passthrough(self):
        self.assertEqual(_marker_str("sin(x)"), "sin(x)")

    def test_bool_localized(self):
        self.assertEqual(_marker_str(True), "да")
        self.assertEqual(_marker_str(False), "нет")

    def test_none_empty(self):
        self.assertEqual(_marker_str(None), "")

    @unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
    def test_sympy_expr_caret(self):
        import sympy as sp
        x = sp.Symbol("x")
        self.assertEqual(_marker_str(x**2), "x^2")


class PolymorphicTemplateTests(unittest.TestCase):
    def test_marker_ports_are_any(self):
        t = TemplateNode("t", {"text": "#a# и #b#"})
        types = {p.name: p.type for p in t.input_ports()}
        self.assertEqual(types["a"], PortType.ANY)
        self.assertEqual(types["b"], PortType.ANY)

    def test_string_substitution(self):
        t = TemplateNode("t", {"text": "функция #f#"})
        self.assertEqual(t.compute({"f": "cos(x)"}, _ctx())["out"], "функция cos(x)")

    def test_number_still_formats(self):
        t = TemplateNode("t", {"text": "#n# штук"})
        self.assertEqual(t.compute({"n": 3.0}, _ctx())["out"], "3 штук")

    def test_string_into_template_via_graph(self):
        # random_choice(string) → template:#f# — раньше падало (STRING↛NUMBER).
        data = {
            "nodes": [
                {"id": "f", "type": "random_choice",
                 "params": {"elem_type": "string", "items": ["sin(x)"]}},
                {"id": "tpl", "type": "template",
                 "params": {"text": "предел #f#"}},
            ],
            "edges": [{"from": "f:out", "to": "tpl:f"}],
        }
        outs = GraphExecutor(GraphSpec.parse(data)).run_full()
        self.assertEqual(outs["tpl"]["out"], "предел sin(x)")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — рендер блока text")
class TextNodePolymorphicTests(unittest.TestCase):
    def test_text_marker_ports_any(self):
        from core.graph.nodes.content import TextNode
        t = TextNode("t", {"text": "#f#"})
        self.assertEqual(t.input_ports()[0].type, PortType.ANY)

    def test_chosen_function_into_statement_end_to_end(self):
        # Полный граф: выбор функции (строка) → условие; раньше невозможно.
        data = {
            "nodes": [
                {"id": "f", "type": "random_choice",
                 "params": {"elem_type": "string",
                            "items": ["sin(x)", "tan(x)", "arcsin(x)"]}},
                {"id": "cond", "type": "text",
                 "params": {"text": "Найдите предел #f#/x при x→0."}},
                {"id": "ans", "type": "text", "params": {"text": "= 1"}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "f:out", "to": "cond:f"},
                {"from": "cond:out", "to": "task:statement"},
                {"from": "ans:out", "to": "task:answer"},
            ],
            "meta": {"seed": 7},
        }
        task = GraphExecutor(GraphSpec.parse(data)).run()
        text = task.statement[0].render_plain()
        self.assertTrue(text.startswith("Найдите предел "))
        self.assertIn("/x при x→0", text)


if __name__ == "__main__":
    unittest.main()
