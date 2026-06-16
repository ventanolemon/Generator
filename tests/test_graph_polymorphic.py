"""
Тесты полиморфизма системы типов: тип PortType.ANY и узел to_block.

ANY — полиморфный порт, совместимый с любым типом (для узлов-диспетчеров).
to_block (ANY → BLOCK) разбирает фактический тип значения и оборачивает его
в подходящий Block: число/bool/строка → TextBlock, sympy-выражение/матрица →
FormulaBlock, PIL-картинка → ImageBlock, готовый Block — passthrough.

Рендер блоков тянет Qt → эти ветки под skipUnless(HAS_QT); чистая совместимость
типов и сборка графа — headless.
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.port_types import coerce_value, is_compatible
from core.graph.nodes.content import ToBlockNode

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
    import PIL  # noqa: F401
    HAS_PIL = True
except Exception:
    HAS_PIL = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


class AnyCompatibilityTests(unittest.TestCase):
    def test_any_accepts_every_type_as_input(self):
        for t in PortType:
            self.assertTrue(is_compatible(t, PortType.ANY),
                            f"{t} должен соединяться со входом ANY")

    def test_any_output_fits_every_input(self):
        for t in PortType:
            self.assertTrue(is_compatible(PortType.ANY, t))

    def test_existing_rules_unchanged(self):
        # Прежние авто-повышения и строгое равенство не сломались.
        self.assertTrue(is_compatible(PortType.BLOCK, PortType.BLOCK_LIST))
        self.assertTrue(is_compatible(PortType.NUMBER, PortType.EXPR))
        self.assertFalse(is_compatible(PortType.STRING, PortType.NUMBER))
        self.assertFalse(is_compatible(PortType.MATRIX, PortType.NUMBER))

    def test_coerce_through_any_passes_value_unchanged(self):
        v = {"complex": "value"}
        self.assertIs(coerce_value(v, PortType.NUMBER_DICT, PortType.ANY), v)

    def test_to_block_declares_any_input(self):
        n = ToBlockNode("b", {})
        self.assertEqual(n.input_ports()[0].type, PortType.ANY)
        self.assertEqual(n.output_ports()[0].type, PortType.BLOCK)

    def test_registered_in_default_registry(self):
        self.assertTrue(DEFAULT_REGISTRY.has("to_block"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — рендер блоков")
class ToBlockDispatchTests(unittest.TestCase):
    def _render(self, value, params=None):
        return ToBlockNode("b", params or {}).compute({"in": value}, _ctx())["out"]

    def test_number_renders_as_text(self):
        block = self._render(42)
        self.assertEqual(block.render_plain(), "42")   # целое без .0

    def test_float_number_as_text(self):
        block = self._render(3.5)
        self.assertEqual(block.render_plain(), "3.5")

    def test_number_with_prefix(self):
        self.assertEqual(self._render(5, {"prefix": "S ="}).render_plain(), "S = 5")

    def test_number_style_formula_makes_formula_block(self):
        from core.blocks import FormulaBlock
        self.assertIsInstance(self._render(7, {"style": "formula"}), FormulaBlock)

    def test_string_renders_as_text(self):
        self.assertEqual(self._render("привет").render_plain(), "привет")

    def test_bool_renders_localized(self):
        self.assertEqual(self._render(True).render_plain(), "да")
        self.assertEqual(self._render(False).render_plain(), "нет")

    def test_block_passthrough(self):
        from core.blocks import TextBlock
        b = TextBlock("готовый")
        self.assertIs(self._render(b), b)

    def test_none_input_requests_retry(self):
        from core.graph.errors import RetryGeneration
        with self.assertRaises(RetryGeneration):
            self._render(None)


@unittest.skipUnless(HAS_QT and HAS_SYMPY, "нужны PyQt6 и sympy")
class ToBlockSymbolicTests(unittest.TestCase):
    def _render(self, value, params=None):
        return ToBlockNode("b", params or {}).compute({"in": value}, _ctx())["out"]

    def test_expr_renders_as_formula(self):
        import sympy as sp
        from core.blocks import FormulaBlock
        x = sp.Symbol("x")
        block = self._render(x**2 + 1)
        self.assertIsInstance(block, FormulaBlock)

    def test_matrix_renders_as_formula(self):
        import sympy as sp
        from core.blocks import FormulaBlock
        block = self._render(sp.Matrix([[1, 2], [3, 4]]), {"env": "bmatrix"})
        self.assertIsInstance(block, FormulaBlock)

    def test_expr_prefix(self):
        import sympy as sp
        x = sp.Symbol("x")
        block = self._render(x + 1, {"prefix": "f(x)"})
        self.assertIn("f(x) =", block.latex)


@unittest.skipUnless(HAS_QT and HAS_PIL, "нужны PyQt6 и Pillow")
class ToBlockImageTests(unittest.TestCase):
    def test_pil_image_renders_as_image_block(self):
        from PIL import Image
        from core.blocks import ImageBlock
        img = Image.new("RGB", (8, 8), "white")
        block = ToBlockNode("b", {"caption": "рис"}).compute({"in": img}, _ctx())["out"]
        self.assertIsInstance(block, ImageBlock)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — исполнение блоков")
class ToBlockGraphTests(unittest.TestCase):
    def test_number_to_block_fills_the_gap_end_to_end(self):
        # random_natural → to_block → static_task. Раньше число нельзя было
        # подать в блок напрямую — теперь to_block закрывает дыру.
        data = {
            "nodes": [
                {"id": "n", "type": "random_natural",
                 "params": {"min": 5, "max": 5}},
                {"id": "b", "type": "to_block", "params": {"prefix": "n ="}},
                {"id": "ans", "type": "text", "params": {"text": "ответ"}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "n:out", "to": "b:in"},
                {"from": "b:out", "to": "task:statement"},
                {"from": "ans:out", "to": "task:answer"},
            ],
            "meta": {"seed": 1},
        }
        task = GraphExecutor(GraphSpec.parse(data)).run()
        self.assertEqual(task.statement[0].render_plain(), "n = 5")

    def test_matrix_to_block_via_polymorphic_node(self):
        if not HAS_SYMPY:
            self.skipTest("sympy не установлен")
        data = {
            "nodes": [
                {"id": "m", "type": "matrix_const",
                 "params": {"data": "1,2;3,4"}},
                {"id": "b", "type": "to_block", "params": {"prefix": "A"}},
                {"id": "ans", "type": "text", "params": {"text": "ответ"}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "m:out", "to": "b:in"},
                {"from": "b:out", "to": "task:statement"},
                {"from": "ans:out", "to": "task:answer"},
            ],
        }
        task = GraphExecutor(GraphSpec.parse(data)).run()
        self.assertIn("A =", task.statement[0].latex)


if __name__ == "__main__":
    unittest.main()
