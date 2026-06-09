"""
Тесты упрощения нодового программирования:
- formula/template/text автоматически заводят входы по именам переменных/маркеров;
- BLOCK → BLOCK_LIST авто-повышение (static_task принимает одиночный блок);
- макро-узел simple_task (всё задание в одном узле);
- обратная совместимость со старым стилем (var_dict → formula:vars).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.port_types import is_compatible, coerce_value

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


class CompatibilityTests(unittest.TestCase):
    def test_block_promotes_to_block_list(self):
        self.assertTrue(is_compatible(PortType.BLOCK, PortType.BLOCK_LIST))
        self.assertEqual(coerce_value("b", PortType.BLOCK, PortType.BLOCK_LIST), ["b"])

    def test_number_promotes_to_expr(self):
        self.assertTrue(is_compatible(PortType.NUMBER, PortType.EXPR))

    def test_no_reverse_promotion(self):
        self.assertFalse(is_compatible(PortType.BLOCK_LIST, PortType.BLOCK))


class FormulaAutoInputsTests(unittest.TestCase):
    def test_formula_derives_named_inputs(self):
        from core.graph.nodes.compute import FormulaNode
        # Имена не из набора физ-констант (c=скорость света, g, e, h… —
        # движок физики считает их константами, а не переменными).
        n = FormulaNode("f", {"expr": "a + b*k"})
        names = [p.name for p in n.input_ports()]
        self.assertIn("a", names)
        self.assertIn("b", names)
        self.assertIn("k", names)
        self.assertIn("vars", names)        # запасной вход остаётся

    def test_formula_computes_from_named(self):
        from core.graph.nodes.compute import FormulaNode
        out = FormulaNode("f", {"expr": "a + b"}).compute({"a": 3, "b": 4}, _ctx())["out"]
        self.assertEqual(out, 7.0)

    def test_formula_vars_dict_still_works(self):
        from core.graph.nodes.compute import FormulaNode
        out = FormulaNode("f", {"expr": "a*2"}).compute({"vars": {"a": 5}}, _ctx())["out"]
        self.assertEqual(out, 10.0)


class TemplateAutoInputsTests(unittest.TestCase):
    def test_template_derives_marker_inputs(self):
        from core.graph.nodes.compute import TemplateNode
        n = TemplateNode("t", {"text": "#a# и #b#"})
        names = [p.name for p in n.input_ports()]
        self.assertEqual(names, ["a", "b", "vars"])

    def test_template_substitutes_named(self):
        from core.graph.nodes.compute import TemplateNode
        out = TemplateNode("t", {"text": "#a# + #b#"}).compute({"a": 2, "b": 3}, _ctx())["out"]
        self.assertEqual(out, "2 + 3")


@unittest.skipUnless(HAS_QT, "нужен PyQt6 (блоки)")
class TextNodeTests(unittest.TestCase):
    def test_text_node_makes_block(self):
        from core.graph.nodes.content import TextNode
        from core.blocks import TextBlock
        out = TextNode("t", {"text": "Ответ: #x#"}).compute({"x": 42}, _ctx())["out"]
        self.assertIsInstance(out, TextBlock)
        self.assertEqual(out.render_plain(), "Ответ: 42")

    def test_text_node_inputs_from_markers(self):
        from core.graph.nodes.content import TextNode
        names = [p.name for p in TextNode("t", {"text": "#p# / #q#"}).input_ports()]
        self.assertEqual(names, ["p", "q", "vars"])


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class SimpleTaskTests(unittest.TestCase):
    def test_registered_in_task_category(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()
               if e["category"] == "task"}
        self.assertIn("simple_task", ids)

    def test_single_node_task(self):
        from core.graph.nodes.task_macros import SimpleTaskNode
        out = SimpleTaskNode("t", {
            "variables": ["a:1:10", "b:1:10"],
            "statement": "#a# + #b# = ?",
            "answer_formula": "a + b",
            "answer": "#result#",
        }).compute({}, _ctx())["out"]
        from core.task import StaticTask
        self.assertIsInstance(out, StaticTask)
        # ответ = сумма из условия
        stmt = out.statement[0].render_plain()
        a, b = [int(x) for x in stmt.replace(" + ", " ").replace(" = ?", "").split()]
        self.assertEqual(out.answer[0].render_plain(), str(a + b))

    def test_reproducible(self):
        # Воспроизводимость — через исполнитель (он сидит глобальный random,
        # как для random_natural); тот же seed → тот же результат.
        g = {"nodes": [{"id": "t", "type": "simple_task", "params": {
            "variables": ["a:1:100"], "statement": "#a#",
            "answer_formula": "a*a", "answer": "#result#"}}],
            "edges": [], "meta": {"seed": 9}}
        a = GraphExecutor(GraphSpec.parse(g)).run().answer[0].render_plain()
        b = GraphExecutor(GraphSpec.parse(g)).run().answer[0].render_plain()
        self.assertEqual(a, b)

    def test_bad_variable_spec_rejected(self):
        from core.graph.nodes.task_macros import SimpleTaskNode
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            SimpleTaskNode("t", {"variables": ["a"]})  # нет min:max


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class EndToEndTests(unittest.TestCase):
    def test_simplified_graph_six_nodes(self):
        from exercises.graph.generators import EXAMPLE_GRAPH
        self.assertLessEqual(len(EXAMPLE_GRAPH["nodes"]), 7)
        g = dict(EXAMPLE_GRAPH); g["meta"] = dict(g["meta"]); g["meta"]["seed"] = 1
        task = GraphExecutor(GraphSpec.parse(g)).run()
        self.assertTrue(task.statement and task.answer)

    def test_block_to_static_task_without_block_list(self):
        # text -> static_task напрямую (BLOCK → BLOCK_LIST повышение)
        g = {
            "nodes": [
                {"id": "q", "type": "text", "params": {"text": "вопрос"}},
                {"id": "a", "type": "text", "params": {"text": "ответ"}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "q:out", "to": "task:statement"},
                {"from": "a:out", "to": "task:answer"},
            ],
        }
        task = GraphExecutor(GraphSpec.parse(g)).run()
        self.assertEqual(task.statement[0].render_plain(), "вопрос")
        self.assertEqual(task.answer[0].render_plain(), "ответ")


if __name__ == "__main__":
    unittest.main()
