"""
Тесты туннелей вывода циклов (Этап B) и узла list_to_matrix.

Туннели (как выходные туннели LabVIEW): параметр outputs ['имя:тип:режим', ...]
у repeat/map/case добавляет внешнему узлу выходной порт; значение в теле задаёт
узел output_var с тем же именем. Режим list — индексированный сбор значений
всех итераций, last — последнее значение. Регистры сдвига сохраняются и
работают вместе с туннелями.

Всё headless, кроме list_to_matrix (нужен sympy — skipUnless по образцу
test_graph_linalg).
"""

from __future__ import annotations
import random
import unittest

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec,
    GraphValidationError, PortType,
)
from core.graph.errors import RetryGeneration
from core.graph.nodes.loop import (
    MapNode, OutputVarNode, RepeatNode, parse_outputs,
)

try:
    import sympy  # noqa: F401
    HAS_SYMPY = True
except Exception:
    HAS_SYMPY = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


def _exec(data: dict) -> GraphExecutor:
    return GraphExecutor(GraphSpec.parse(data))


# Тело: i² через формулу, значение уходит в туннель 's'.
def _square_body(tunnel="s"):
    return {
        "nodes": [
            {"id": "li", "type": "loop_index"},
            {"id": "f", "type": "formula", "params": {"expr": "i * i"}},
            {"id": "ov", "type": "output_var",
             "params": {"name": tunnel, "type": "number"}},
        ],
        "edges": [
            {"from": "li:out", "to": "f:i"},
            {"from": "f:out", "to": "ov:value"},
        ],
    }


class ParseOutputsTests(unittest.TestCase):
    def test_defaults_number_list(self):
        self.assertEqual(parse_outputs({"outputs": ["x"]}),
                         [("x", PortType.NUMBER, "list")])

    def test_full_form(self):
        self.assertEqual(
            parse_outputs({"outputs": ["s:string:last", "b:block"]}),
            [("s", PortType.STRING, "last"), ("b", PortType.BLOCK, "list")],
        )

    def test_unknown_type_rejected(self):
        with self.assertRaisesRegex(GraphValidationError, "неизвестный тип"):
            parse_outputs({"outputs": ["x:matrix"]})

    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(GraphValidationError, "неизвестный режим"):
            parse_outputs({"outputs": ["x:number:first"]})

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(GraphValidationError, "дважды"):
            parse_outputs({"outputs": ["x", "x:string"]})

    def test_reserved_out_rejected(self):
        with self.assertRaisesRegex(GraphValidationError, "out"):
            parse_outputs({"outputs": ["out:number"]})

    def test_empty_entries_skipped(self):
        self.assertEqual(parse_outputs({"outputs": ["", "  "]}), [])


class TunnelPortsTests(unittest.TestCase):
    def test_repeat_tunnel_ports(self):
        n = RepeatNode("r", {
            "outputs": ["s:number:last", "xs:number", "bs:block"],
            "body": _square_body(),
        })
        ports = {p.name: p.type for p in n.output_ports()}
        self.assertEqual(ports["out"], PortType.BLOCK_LIST)
        self.assertEqual(ports["s"], PortType.NUMBER)      # last → тип как есть
        self.assertEqual(ports["xs"], PortType.LIST)       # list → коллекция
        self.assertEqual(ports["bs"], PortType.BLOCK_LIST) # блоки → BLOCK_LIST

    def test_output_var_is_pure_sink(self):
        # Нет выходных портов: туннель не конкурирует со свободным BLOCK тела.
        n = OutputVarNode("ov", {"name": "s", "type": "block"})
        self.assertEqual(n.output_ports(), [])
        self.assertEqual([p.name for p in n.input_ports()], ["value"])


class RepeatTunnelTests(unittest.TestCase):
    def test_list_mode_collects_each_iteration(self):
        n = RepeatNode("r", {"count": 4, "outputs": ["s:number:list"],
                             "body": _square_body()})
        out = n.compute({}, _ctx())
        self.assertEqual(out["s"], [0.0, 1.0, 4.0, 9.0])
        self.assertEqual(out["out"], [])   # блоков тело не отдаёт

    def test_last_mode_returns_final_value(self):
        n = RepeatNode("r", {"count": 4, "outputs": ["s:number:last"],
                             "body": _square_body()})
        self.assertEqual(n.compute({}, _ctx())["s"], 9.0)

    def test_tunnels_and_registers_together(self):
        # Бегущая сумма: регистр acc переносит сумму между итерациями,
        # туннели отдают и все промежуточные суммы, и итог.
        body = {
            "nodes": [
                {"id": "sg", "type": "shift_get",
                 "params": {"name": "acc", "type": "number"}},
                {"id": "li", "type": "loop_index"},
                {"id": "f", "type": "formula", "params": {"expr": "acc + i"}},
                {"id": "ss", "type": "shift_set",
                 "params": {"name": "acc", "type": "number"}},
                {"id": "o1", "type": "output_var",
                 "params": {"name": "sums", "type": "number"}},
                {"id": "o2", "type": "output_var",
                 "params": {"name": "total", "type": "number"}},
            ],
            "edges": [
                {"from": "sg:out", "to": "f:acc"},
                {"from": "li:out", "to": "f:i"},
                {"from": "f:out", "to": "ss:value"},
                {"from": "f:out", "to": "o1:value"},
                {"from": "f:out", "to": "o2:value"},
            ],
        }
        n = RepeatNode("r", {
            "count": 4,
            "registers": ["acc:number:0"],
            "outputs": ["sums:number:list", "total:number:last"],
            "body": body,
        })
        out = n.compute({}, _ctx())
        self.assertEqual(out["sums"], [0.0, 1.0, 3.0, 6.0])
        self.assertEqual(out["total"], 6.0)

    def test_zero_iterations_defaults(self):
        n = RepeatNode("r", {
            "count": 0,
            "outputs": ["xs:number:list", "s:number:last"],
            "body": _square_body(),   # output_var 's' есть; xs добавим ниже
        })
        # Для нуля итераций важно только начальное значение туннелей.
        n.params["body"]["nodes"].append(
            {"id": "ov2", "type": "output_var",
             "params": {"name": "xs", "type": "number"}})
        n.params["body"]["edges"].append({"from": "f:out", "to": "ov2:value"})
        out = n.compute({}, _ctx())
        self.assertEqual(out["xs"], [])
        self.assertEqual(out["s"], 0.0)   # типовое значение по умолчанию


class ValidateStructureTests(unittest.TestCase):
    def test_declared_tunnel_without_output_var_rejected(self):
        data = {
            "nodes": [{"id": "rep", "type": "repeat", "params": {
                "count": 2, "outputs": ["missing:number"],
                "body": _square_body("s"),
            }}],
            "edges": [],
        }
        with self.assertRaisesRegex(GraphValidationError, "missing"):
            _exec(data)

    def test_type_mismatch_rejected(self):
        data = {
            "nodes": [{"id": "rep", "type": "repeat", "params": {
                "count": 2, "outputs": ["s:string"],
                "body": _square_body("s"),   # output_var имеет тип number
            }}],
            "edges": [],
        }
        with self.assertRaisesRegex(GraphValidationError, "тип"):
            _exec(data)

    def test_matching_tunnel_builds(self):
        data = {
            "nodes": [{"id": "rep", "type": "repeat", "params": {
                "count": 2, "outputs": ["s:number"],
                "body": _square_body("s"),
            }}],
            "edges": [],
        }
        _exec(data)   # не бросает

    def test_case_requires_tunnel_in_every_branch(self):
        branch_ok = {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": 1}},
                {"id": "ov", "type": "output_var",
                 "params": {"name": "v", "type": "number"}},
            ],
            "edges": [{"from": "c:out", "to": "ov:value"}],
        }
        data = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 0}},
                {"id": "cs", "type": "case", "params": {
                    "cases": 2, "outputs": ["v:number"],
                    "case_0": branch_ok,    # case_1 не задана
                }},
            ],
            "edges": [{"from": "n:out", "to": "cs:selector"}],
        }
        with self.assertRaisesRegex(GraphValidationError, "case_1"):
            _exec(data)


class MapTunnelTests(unittest.TestCase):
    def test_map_collects_tunnel_per_element(self):
        body = {
            "nodes": [
                {"id": "mi", "type": "map_item", "params": {"type": "number"}},
                {"id": "f", "type": "formula", "params": {"expr": "x * x"}},
                {"id": "ov", "type": "output_var",
                 "params": {"name": "sq", "type": "number"}},
            ],
            "edges": [
                {"from": "mi:out", "to": "f:x"},
                {"from": "f:out", "to": "ov:value"},
            ],
        }
        n = MapNode("m", {"outputs": ["sq:number"], "body": body})
        out = n.compute({"items": [2, 5]}, _ctx())
        self.assertEqual(out["sq"], [4.0, 25.0])


class CaseTunnelTests(unittest.TestCase):
    @staticmethod
    def _branch(value):
        return {
            "nodes": [
                {"id": "c", "type": "constant_number", "params": {"value": value}},
                {"id": "ov", "type": "output_var",
                 "params": {"name": "v", "type": "number"}},
            ],
            "edges": [{"from": "c:out", "to": "ov:value"}],
        }

    def _graph(self, selector):
        return {
            "nodes": [
                {"id": "n", "type": "constant_number",
                 "params": {"value": selector}},
                {"id": "cs", "type": "case", "params": {
                    "cases": 2, "outputs": ["v:number"],
                    "case_0": self._branch(10), "case_1": self._branch(20),
                }},
            ],
            "edges": [{"from": "n:out", "to": "cs:selector"}],
        }

    def test_tunnel_takes_value_of_selected_branch(self):
        outs = _exec(self._graph(1)).run_full()
        self.assertEqual(outs["cs"]["v"], 20.0)
        outs = _exec(self._graph(0)).run_full()
        self.assertEqual(outs["cs"]["v"], 10.0)

    def test_case_tunnel_port_is_declared_type(self):
        ex = _exec(self._graph(0))
        ports = {p.name: p.type for p in ex.nodes["cs"].output_ports()}
        self.assertEqual(ports["v"], PortType.NUMBER)

    def test_empty_default_with_tunnel_fails_at_run(self):
        # Селектор вне диапазона уводит в пустую default — там туннеля нет.
        ex = _exec(self._graph(5))
        with self.assertRaisesRegex(GraphValidationError, "default"):
            ex.run_full()


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class ListToMatrixTests(unittest.TestCase):
    @staticmethod
    def _node(params=None):
        from core.graph.nodes.linalg import ListToMatrixNode
        return ListToMatrixNode("m", params or {})

    def test_rows_given_cols_inferred(self):
        import sympy as sp
        out = self._node({"rows": 2}).compute({"items": [1, 2, 3, 4, 5, 6]}, _ctx())
        self.assertEqual(out["out"], sp.Matrix([[1, 2, 3], [4, 5, 6]]))

    def test_cols_given_rows_inferred(self):
        import sympy as sp
        out = self._node({"cols": 2}).compute({"items": [1, 2, 3, 4, 5, 6]}, _ctx())
        self.assertEqual(out["out"], sp.Matrix([[1, 2], [3, 4], [5, 6]]))

    def test_square_inference_without_dims(self):
        import sympy as sp
        out = self._node().compute({"items": [1, 2, 3, 4]}, _ctx())
        self.assertEqual(out["out"], sp.Matrix([[1, 2], [3, 4]]))

    def test_rows_from_input_port_override(self):
        out = self._node({"rows": 0}).compute(
            {"items": [1, 2, 3, 4, 5, 6], "rows": 3}, _ctx())
        self.assertEqual(out["out"].shape, (3, 2))

    def test_shape_mismatch_retries(self):
        with self.assertRaises(RetryGeneration):
            self._node({"rows": 4}).compute({"items": [1, 2, 3, 4, 5, 6]}, _ctx())

    def test_non_square_without_dims_retries(self):
        with self.assertRaises(RetryGeneration):
            self._node().compute({"items": [1, 2, 3, 4, 5]}, _ctx())

    def test_non_number_element_retries(self):
        with self.assertRaises(RetryGeneration):
            self._node({"rows": 1}).compute({"items": ["a"]}, _ctx())

    def test_float_elements_kept_pretty(self):
        import sympy as sp
        out = self._node({"rows": 1}).compute({"items": [2.0, 0.5]}, _ctx())
        self.assertEqual(out["out"], sp.Matrix([[2, sp.Rational(1, 2)]]))


@unittest.skipUnless(HAS_SYMPY, "sympy не установлен")
class MatrixInLoopEndToEndTests(unittest.TestCase):
    def test_repeat_tunnel_feeds_list_to_matrix(self):
        # Цикл накапливает i+1 в туннель xs, list_to_matrix сворачивает в 2×3.
        import sympy as sp
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "f", "type": "formula", "params": {"expr": "i + 1"}},
                {"id": "ov", "type": "output_var",
                 "params": {"name": "xs", "type": "number"}},
            ],
            "edges": [
                {"from": "li:out", "to": "f:i"},
                {"from": "f:out", "to": "ov:value"},
            ],
        }
        data = {
            "nodes": [
                {"id": "rep", "type": "repeat", "params": {
                    "count": 6, "outputs": ["xs:number:list"], "body": body,
                }},
                {"id": "m", "type": "list_to_matrix", "params": {"rows": 2}},
            ],
            "edges": [{"from": "rep:xs", "to": "m:items"}],
        }
        outs = _exec(data).run_full()
        self.assertEqual(outs["m"]["out"], sp.Matrix([[1, 2, 3], [4, 5, 6]]))


if __name__ == "__main__":
    unittest.main()
