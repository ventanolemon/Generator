"""
Тесты import-туннелей: внешние переменные внутрь тела repeat/map (PR-3 фазы 3b-2).

Механика (parse_imports, input_var, динамические порты, проброс значений) —
headless; сбор блоков с внешней переменной — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec,
    GraphValidationError, PortType,
)
from core.graph.nodes.loop import (
    IMPORT_PREFIX, InputVarNode, parse_imports,
)

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(**extra):
    return ExecContext(rng=random.Random(0), extra=extra)


class ParseImportsTests(unittest.TestCase):
    def test_basic_name_type(self):
        self.assertEqual(parse_imports({"imports": ["k:number", "w:string"]}),
                         [("k", PortType.NUMBER), ("w", PortType.STRING)])

    def test_default_type_is_number(self):
        self.assertEqual(parse_imports({"imports": ["k"]}), [("k", PortType.NUMBER)])

    def test_blank_and_empty_skipped(self):
        self.assertEqual(parse_imports({"imports": ["", "  ", "k:bool"]}),
                         [("k", PortType.BOOL)])

    def test_unknown_type_rejected(self):
        with self.assertRaises(GraphValidationError):
            parse_imports({"imports": ["k:weird"]})

    def test_duplicate_name_rejected(self):
        with self.assertRaises(GraphValidationError):
            parse_imports({"imports": ["k:number", "k:string"]})

    def test_no_imports_empty(self):
        self.assertEqual(parse_imports({}), [])


class InputVarTests(unittest.TestCase):
    def test_reads_tunnel_value(self):
        n = InputVarNode("iv", {"name": "k", "type": "number"})
        out = n.compute({}, _ctx(**{IMPORT_PREFIX + "k": 42.0}))
        self.assertEqual(out["out"], 42.0)

    def test_missing_tunnel_retries(self):
        from core.graph import RetryGeneration
        n = InputVarNode("iv", {"name": "k", "type": "number"})
        with self.assertRaises(RetryGeneration):
            n.compute({}, _ctx())

    def test_output_type_follows_param(self):
        self.assertEqual(InputVarNode("iv", {"type": "string"}).output_ports()[0].type,
                         PortType.STRING)
        self.assertEqual(InputVarNode("iv", {"type": "list"}).output_ports()[0].type,
                         PortType.LIST)

    def test_bad_type_rejected(self):
        with self.assertRaises(GraphValidationError):
            InputVarNode("iv", {"type": "nope"})


class DynamicPortTests(unittest.TestCase):
    def test_repeat_gains_import_inputs(self):
        n = DEFAULT_REGISTRY.create("repeat", "r", {"imports": ["base:number"]})
        names = [(p.name, p.type, p.required) for p in n.input_ports()]
        self.assertIn(("count", PortType.NUMBER, False), names)
        self.assertIn(("base", PortType.NUMBER, False), names)

    def test_map_gains_import_inputs(self):
        n = DEFAULT_REGISTRY.create("map", "m", {"imports": ["w:string"]})
        names = {p.name: p.type for p in n.input_ports()}
        self.assertEqual(names.get("items"), PortType.LIST)
        self.assertEqual(names.get("w"), PortType.STRING)

    def test_no_imports_unchanged(self):
        # Обратная совместимость: без imports порты прежние.
        n = DEFAULT_REGISTRY.create("repeat", "r", {})
        self.assertEqual([p.name for p in n.input_ports()], ["count"])


class ExecImportTests(unittest.TestCase):
    def test_external_var_visible_inside_body(self):
        # Внутри тела input_var('base') складывается с индексом итерации.
        body = {
            "nodes": [
                {"id": "iv", "type": "input_var", "params": {"name": "base", "type": "number"}},
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["b", "i"]}},
                {"id": "f", "type": "formula", "params": {"expr": "b + i"}},
            ],
            "edges": [
                {"from": "iv:out", "to": "vd:b"},
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "f:vars"},
            ],
        }
        spec = GraphSpec.parse(body)
        vals = []
        for i in range(3):
            out = GraphExecutor(spec).run_full(
                extra={IMPORT_PREFIX + "base": 100.0, "__loop_index__": i})
            vals.append(out["f"]["out"])
        self.assertEqual(vals, [100.0, 101.0, 102.0])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class RepeatWithImportTests(unittest.TestCase):
    def test_repeat_passes_external_constant_into_body(self):
        # constant_number(50) -> repeat.base; тело печатает base+index.
        body = {
            "nodes": [
                {"id": "iv", "type": "input_var", "params": {"name": "base", "type": "number"}},
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["b", "i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "#b#+#i#"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "iv:out", "to": "vd:b"},
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        graph = {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 50}},
                {"id": "n", "type": "constant_number", "params": {"value": 3}},
                {"id": "rep", "type": "repeat",
                 "params": {"imports": ["base:number"], "body": body}},
                {"id": "task", "type": "static_task"},
                {"id": "az", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
                {"id": "atb", "type": "text_block"},
                {"id": "bl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "n:out", "to": "rep:count"},
                {"from": "c:out", "to": "rep:base"},
                {"from": "rep:out", "to": "task:statement"},
                {"from": "az:out", "to": "avd:z"},
                {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"},
                {"from": "atb:out", "to": "bl:in0"},
                {"from": "bl:out", "to": "task:answer"},
            ],
            "meta": {"max_attempts": 1},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        self.assertEqual([b.render_plain() for b in task.statement],
                         ["50+0", "50+1", "50+2"])


if __name__ == "__main__":
    unittest.main()
