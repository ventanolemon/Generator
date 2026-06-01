"""
Тесты регистра сдвига (shift_get/shift_set): состояние между итерациями repeat.

Механика (parse_registers, начальные значения, чтение/запись, проброс между
итерациями) — headless; накопление с выводом блоков — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.graph.nodes.loop import (
    REGISTER_PREFIX, RepeatNode, ShiftGetNode, ShiftSetNode,
    parse_registers, _register_initial,
)

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(**extra):
    return ExecContext(rng=random.Random(0), extra=extra)


class ParseRegistersTests(unittest.TestCase):
    def test_name_type_initial(self):
        self.assertEqual(parse_registers({"registers": ["acc:number:10"]}),
                         [("acc", PortType.NUMBER, "10")])

    def test_default_type_no_initial(self):
        self.assertEqual(parse_registers({"registers": ["acc"]}),
                         [("acc", PortType.NUMBER, None)])

    def test_string_register(self):
        self.assertEqual(parse_registers({"registers": ["w:string:hi"]}),
                         [("w", PortType.STRING, "hi")])

    def test_unknown_type_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            parse_registers({"registers": ["acc:weird"]})

    def test_duplicate_rejected(self):
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            parse_registers({"registers": ["a:number", "a:string"]})


class InitialValueTests(unittest.TestCase):
    def test_number_initial(self):
        self.assertEqual(_register_initial(PortType.NUMBER, "10"), 10.0)
        self.assertEqual(_register_initial(PortType.NUMBER, None), 0.0)
        self.assertEqual(_register_initial(PortType.NUMBER, "bad"), 0.0)

    def test_string_initial(self):
        self.assertEqual(_register_initial(PortType.STRING, "x"), "x")
        self.assertEqual(_register_initial(PortType.STRING, None), "")


class ShiftNodeTests(unittest.TestCase):
    def test_get_reads_register(self):
        n = ShiftGetNode("g", {"name": "acc", "type": "number"})
        self.assertEqual(n.compute({}, _ctx(**{REGISTER_PREFIX + "acc": 7.0}))["out"], 7.0)

    def test_get_missing_retries(self):
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            ShiftGetNode("g", {"name": "acc"}).compute({}, _ctx())

    def test_set_passthrough(self):
        n = ShiftSetNode("s", {"name": "acc", "type": "number"})
        self.assertEqual(n.compute({"value": 5.0}, _ctx())["out"], 5.0)

    def test_set_typed_ports(self):
        n = ShiftSetNode("s", {"type": "string"})
        self.assertEqual(n.input_ports()[0].type, PortType.STRING)
        self.assertEqual(n.output_ports()[0].type, PortType.STRING)

    def test_registered(self):
        self.assertTrue(DEFAULT_REGISTRY.has("shift_get"))
        self.assertTrue(DEFAULT_REGISTRY.has("shift_set"))


def _accumulator_body():
    # shift_get(acc) + loop_index -> acc+i -> shift_set(acc); печатает текущее acc.
    return {
        "nodes": [
            {"id": "sg", "type": "shift_get", "params": {"name": "acc", "type": "number"}},
            {"id": "li", "type": "loop_index"},
            {"id": "vd", "type": "var_dict", "params": {"names": ["acc", "i"]}},
            {"id": "f", "type": "formula", "params": {"expr": "acc + i"}},
            {"id": "ss", "type": "shift_set", "params": {"name": "acc", "type": "number"}},
            # вывод текущего значения acc до прибавления
            {"id": "vd2", "type": "var_dict", "params": {"names": ["acc"]}},
            {"id": "tpl", "type": "template", "params": {"text": "acc=#acc#"}},
            {"id": "tb", "type": "text_block"},
        ],
        "edges": [
            {"from": "sg:out", "to": "vd:acc"},
            {"from": "li:out", "to": "vd:i"},
            {"from": "vd:out", "to": "f:vars"},
            {"from": "f:out", "to": "ss:value"},
            {"from": "sg:out", "to": "vd2:acc"},
            {"from": "vd2:out", "to": "tpl:vars"},
            {"from": "tpl:out", "to": "tb:text"},
        ],
    }


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AccumulatorTests(unittest.TestCase):
    def test_running_value_across_iterations(self):
        # acc стартует 0; на итерации i печатает текущее acc, затем acc += i.
        # Значения acc на входах: 0, 0(+0), 1(+1)=... -> 0,0,1,3,6
        n = RepeatNode("r", {"count": 5, "registers": ["acc:number:0"],
                             "body": _accumulator_body()})
        blocks = n.compute({}, _ctx())["out"]
        self.assertEqual([b.render_plain() for b in blocks],
                         ["acc=0", "acc=0", "acc=1", "acc=3", "acc=6"])

    def test_initial_value_used(self):
        n = RepeatNode("r", {"count": 3, "registers": ["acc:number:100"],
                             "body": _accumulator_body()})
        blocks = n.compute({}, _ctx())["out"]
        # 100, 100(+0), 101(+1)=... -> 100,100,101
        self.assertEqual([b.render_plain() for b in blocks],
                         ["acc=100", "acc=100", "acc=101"])

    def test_no_registers_backward_compatible(self):
        # Тело без регистров работает как раньше.
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "#i#"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        n = RepeatNode("r", {"count": 3, "body": body})
        self.assertEqual([b.render_plain() for b in n.compute({}, _ctx())["out"]],
                         ["0", "1", "2"])


if __name__ == "__main__":
    unittest.main()
