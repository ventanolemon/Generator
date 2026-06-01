"""
Тесты кейс-структуры (case): по селектору исполняется одна из ветвей-подграфов.

Механика (счётчик ветвей, выбор по селектору, default, import-туннели) —
headless; сбор блоков выбранной ветви — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.nodes.loop import CaseNode, IMPORT_PREFIX

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(**extra):
    return ExecContext(rng=random.Random(0), extra=extra)


def _const_block_body(text):
    """Ветвь, выдающая один текстовый блок с заданным текстом."""
    return {
        "nodes": [
            {"id": "z", "type": "constant_number", "params": {"value": 1}},
            {"id": "vd", "type": "var_dict", "params": {"names": ["z"]}},
            {"id": "tpl", "type": "template", "params": {"text": text}},
            {"id": "tb", "type": "text_block"},
        ],
        "edges": [
            {"from": "z:out", "to": "vd:z"},
            {"from": "vd:out", "to": "tpl:vars"},
            {"from": "tpl:out", "to": "tb:text"},
        ],
    }


class RegistryTests(unittest.TestCase):
    def test_case_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("case"))

    def test_branch_keys(self):
        n = CaseNode("c", {"cases": 3})
        self.assertEqual(n.branch_keys(), ["case_0", "case_1", "case_2"])

    def test_selector_and_imports_ports(self):
        n = DEFAULT_REGISTRY.create("case", "c", {"cases": 2, "imports": ["k:string"]})
        names = {p.name: (p.type, p.required) for p in n.input_ports()}
        self.assertEqual(names["selector"], (PortType.NUMBER, True))
        self.assertEqual(names["k"], (PortType.STRING, False))


class SelectorTests(unittest.TestCase):
    def test_non_number_selector_retries(self):
        from core.graph import RetryGeneration
        n = CaseNode("c", {"cases": 2})
        with self.assertRaises(RetryGeneration):
            n.compute({"selector": "nope"}, _ctx())

    def test_empty_branch_empty_result(self):
        # Селектор в диапазоне, но ветвь пуста → пустой список.
        n = CaseNode("c", {"cases": 2, "case_0": {"nodes": [], "edges": [], "meta": {}}})
        self.assertEqual(n.compute({"selector": 0}, _ctx())["out"], [])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class BranchExecutionTests(unittest.TestCase):
    def test_selects_correct_branch(self):
        params = {
            "cases": 2,
            "case_0": _const_block_body("ноль"),
            "case_1": _const_block_body("один"),
            "default": _const_block_body("иначе"),
        }
        n = CaseNode("c", params)
        self.assertEqual([b.render_plain() for b in n.compute({"selector": 0}, _ctx())["out"]],
                         ["ноль"])
        self.assertEqual([b.render_plain() for b in n.compute({"selector": 1}, _ctx())["out"]],
                         ["один"])

    def test_out_of_range_uses_default(self):
        params = {
            "cases": 2,
            "case_0": _const_block_body("ноль"),
            "case_1": _const_block_body("один"),
            "default": _const_block_body("иначе"),
        }
        n = CaseNode("c", params)
        self.assertEqual([b.render_plain() for b in n.compute({"selector": 9}, _ctx())["out"]],
                         ["иначе"])
        self.assertEqual([b.render_plain() for b in n.compute({"selector": -1}, _ctx())["out"]],
                         ["иначе"])

    def test_only_selected_branch_executes(self):
        # Невыбранная ветвь содержит заведомо «падающий» узёл (formula с делением
        # на ноль не бросает; используем constraint, который провалит ветвь).
        bad = {
            "nodes": [
                {"id": "z", "type": "constant_number", "params": {"value": 0}},
                {"id": "vd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "ct", "type": "constraint", "params": {"expr": "z > 0"}},
                {"id": "tpl", "type": "template", "params": {"text": "плохо"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "z:out", "to": "vd:z"},
                {"from": "vd:out", "to": "ct:vars"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        params = {"cases": 2, "case_0": _const_block_body("хорошо"), "case_1": bad}
        n = CaseNode("c", params)
        # Выбираем 0 — «плохая» ветвь не исполняется, ошибки нет.
        out = n.compute({"selector": 0}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in out], ["хорошо"])

    def test_import_visible_in_branch(self):
        # Ветвь печатает значение внешней переменной k.
        body = {
            "nodes": [
                {"id": "iv", "type": "input_var", "params": {"name": "k", "type": "string"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [{"from": "iv:out", "to": "tb:text"}],
        }
        n = CaseNode("c", {"cases": 1, "imports": ["k:string"], "case_0": body})
        out = n.compute({"selector": 0, "k": "привет"}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in out], ["привет"])

    def test_case_in_full_graph(self):
        graph = {
            "nodes": [
                {"id": "sel", "type": "constant_number", "params": {"value": 1}},
                {"id": "c", "type": "case", "params": {
                    "cases": 2,
                    "case_0": _const_block_body("ветвь ноль"),
                    "case_1": _const_block_body("ветвь один"),
                }},
                {"id": "task", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "sel:out", "to": "c:selector"},
                {"from": "c:out", "to": "task:statement"},
                {"from": "az:out", "to": "avd:z"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "task:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual([b.render_plain() for b in task.statement], ["ветвь один"])


if __name__ == "__main__":
    unittest.main()
