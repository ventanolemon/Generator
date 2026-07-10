"""
Тесты проброса типа по типизированным узлам (Node.TYPE_PARAM/TYPE_PARAM_MAP,
GraphDocument.propagate_types_from_node) — headless, core/graph/document.py.

Идея: узлы вроде list_new/list_get/select/input_var выбирают тип своих
портов параметром-перечислением (elem_type/value_type/type). Без проброса
смена этого параметра на одном блоке требует вручную поправить elem_type на
КАЖДОМ подключённом узле по цепочке — сценарий пользователя, вызвавший фикс:
"меняю входные данные с expr на str, не хочу лазить по каждому блоку".

Два правила (см. document.py):
  A — обычный скалярный порт: провод несёт src.port.type; порт назначения,
      САМ управляемый TYPE_PARAM (list_get.out, list_append.item, select.*,
      input_var.out и т.п.), ретайпится под него.
  B — граница LIST: список не несёт тип элемента на проводе, поэтому
      list_new.out → list_get.list синхронизирует elem_type НАПРЯМУЮ по
      строковому ключу между двумя типизированными LIST-узлами.

Запуск: python -m unittest tests.test_graph_type_propagation -v
"""

from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph.document import GraphDocument  # noqa: E402


class RuleAScalarPortTests(unittest.TestCase):
    """Провод из обычного (не-LIST) порта в типизированный порт назначения."""

    def test_wiring_expr_source_retypes_list_append_item(self):
        doc = GraphDocument()
        doc.add_node("expr_const", {"expr": "x+1"}, node_id="E")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="A")
        doc.add_edge("E", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params["elem_type"], "expr")

    def test_wiring_matching_type_is_noop(self):
        doc = GraphDocument()
        doc.add_node("expr_const", {"expr": "x"}, node_id="E")
        doc.add_node("list_append", {"elem_type": "expr"}, node_id="A")
        params_before = dict(doc.nodes["A"].params)
        doc.add_edge("E", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params, params_before)

    def test_unsupported_target_type_leaves_param_untouched(self):
        # select.value_type не поддерживает bool — провод-BOOL в on_true
        # не должен уронить исполнение попыткой поставить несуществующий ключ.
        doc = GraphDocument()
        doc.add_node("constant_bool", {"value": True}, node_id="B")
        doc.add_node("select", {"value_type": "number"}, node_id="S")
        doc.add_edge("B", "out", "S", "on_true")
        self.assertEqual(doc.nodes["S"].params["value_type"], "number")

    def test_select_branches_and_output_retype_together(self):
        doc = GraphDocument()
        doc.add_node("expr_const", {"expr": "x"}, node_id="E")
        doc.add_node("select", {"value_type": "number"}, node_id="S")
        doc.add_edge("E", "out", "S", "on_true")
        self.assertEqual(doc.nodes["S"].params["value_type"], "expr")
        # on_false/out пересчитываются из ТОГО ЖЕ value_type — единый параметр.
        ins, outs = doc.ports("S")
        types = {p.name: p.type.value for p in ins} | {p.name: p.type.value for p in outs}
        self.assertEqual(types["on_false"], "expr")
        self.assertEqual(types["out"], "expr")


class RuleBListBoundaryTests(unittest.TestCase):
    """Проброс elem_type через LIST-порты между двумя типизированными узлами."""

    def test_list_new_to_list_get_syncs_elem_type(self):
        doc = GraphDocument()
        doc.add_node("list_new", {"count": 0, "elem_type": "expr"}, node_id="LN")
        doc.add_node("list_get", {"elem_type": "number"}, node_id="LG")
        doc.add_edge("LN", "out", "LG", "list")
        self.assertEqual(doc.nodes["LG"].params["elem_type"], "expr")

    def test_list_new_to_list_append_list_input_syncs(self):
        doc = GraphDocument()
        doc.add_node("list_new", {"count": 0, "elem_type": "matrix"}, node_id="LN")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="LA")
        doc.add_edge("LN", "out", "LA", "list")
        self.assertEqual(doc.nodes["LA"].params["elem_type"], "matrix")

    def test_plain_list_source_without_type_param_is_ignored(self):
        # random_natural.out тоже мог бы (гипотетически) питать LIST-вход —
        # но обычные узлы без TYPE_PARAM не участвуют в правиле B вовсе.
        doc = GraphDocument()
        doc.add_node("list_concat", {}, node_id="C")   # без TYPE_PARAM
        doc.add_node("list_get", {"elem_type": "number"}, node_id="LG")
        doc.add_edge("C", "out", "LG", "list")
        self.assertEqual(doc.nodes["LG"].params["elem_type"], "number")


class CascadeTests(unittest.TestCase):
    """Смена типа на источнике расходится по всей цепочке потребителей."""

    def test_full_chain_cascades_on_source_edit(self):
        doc = GraphDocument()
        doc.add_node("list_new", {"count": 0, "elem_type": "expr"}, node_id="LN")
        doc.add_node("list_get", {"elem_type": "expr"}, node_id="LG")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="LA")
        doc.add_edge("LN", "out", "LG", "list")
        doc.add_edge("LG", "out", "LA", "item")
        self.assertEqual(doc.nodes["LG"].params["elem_type"], "expr")
        self.assertEqual(doc.nodes["LA"].params["elem_type"], "expr")

        # Пользователь меняет ИСТОЧНИК на "string" — вся цепочка следует сама.
        doc.set_params("LN", {**doc.nodes["LN"].params, "elem_type": "string"})
        changed = doc.propagate_types_from_node("LN")
        self.assertEqual(changed, {"LG", "LA"})
        self.assertEqual(doc.nodes["LG"].params["elem_type"], "string")
        self.assertEqual(doc.nodes["LA"].params["elem_type"], "string")

    def test_input_var_to_shift_set_to_output_var_cascade(self):
        doc = GraphDocument()
        doc.add_node("input_var", {"name": "k", "type": "number"}, node_id="IV")
        doc.add_node("shift_set", {"name": "acc", "type": "number"}, node_id="SS")
        doc.add_node("output_var", {"name": "res", "type": "number"}, node_id="OV")
        doc.add_edge("IV", "out", "SS", "value")
        doc.add_edge("SS", "out", "OV", "value")

        doc.set_params("IV", {**doc.nodes["IV"].params, "type": "string"})
        changed = doc.propagate_types_from_node("IV")
        self.assertEqual(changed, {"SS", "OV"})
        self.assertEqual(doc.nodes["SS"].params["type"], "string")
        self.assertEqual(doc.nodes["OV"].params["type"], "string")

    def test_cycle_safe_no_infinite_loop(self):
        # Граф не допускает содержательных циклов, но propagate обязан не
        # зависать даже на противоестественном самозамкнутом ребре.
        doc = GraphDocument()
        doc.add_node("list_get", {"elem_type": "number"}, node_id="LG")
        doc.edges.append(__import__("core.graph.document", fromlist=["DocEdge"])
                         .DocEdge("LG", "out", "LG", "list"))
        changed = doc.propagate_types_from_node("LG")
        self.assertEqual(changed, set())   # not governed by "list", no crash


class AddEdgeIntegrationTests(unittest.TestCase):
    """add_edge пробрасывает тип сам — без явного вызова propagate."""

    def test_add_edge_propagates_implicitly(self):
        doc = GraphDocument()
        doc.add_node("expr_const", {"expr": "x"}, node_id="E")
        doc.add_node("list_get", {"elem_type": "number"}, node_id="LG")
        # LG.list не задействован здесь — проверяем именно Rule A путём
        # прямого провода в governed-порт другого типизированного узла.
        doc.add_node("list_append", {"elem_type": "number"}, node_id="A")
        doc.add_edge("E", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params["elem_type"], "expr")


class RandomChoiceAndPickTests(unittest.TestCase):
    def test_random_choice_count1_output_retypes_consumer(self):
        doc = GraphDocument()
        doc.add_node("random_choice", {"elem_type": "string", "count": 1,
                                       "items": ["a", "b"]}, node_id="R")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="A")
        doc.add_edge("R", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params["elem_type"], "string")

    def test_random_choice_count_gt1_not_governed(self):
        # count>1 → выход LIST, элементный тип на проводе не несётся как
        # governed-порт (type_param_ports() пуст) — но Rule B всё равно
        # сработает через LIST-границу, если приёмник тоже типизирован.
        doc = GraphDocument()
        doc.add_node("random_choice", {"elem_type": "expr", "count": 2,
                                       "items": ["x", "y"]}, node_id="R")
        doc.add_node("list_get", {"elem_type": "number"}, node_id="LG")
        doc.add_edge("R", "out", "LG", "list")
        self.assertEqual(doc.nodes["LG"].params["elem_type"], "expr")

    def test_pick_channels_retype_together(self):
        doc = GraphDocument()
        doc.add_node("expr_const", {"expr": "x"}, node_id="E")
        doc.add_node("pick", {"count": 3, "value_type": "block"}, node_id="P")
        doc.add_edge("E", "out", "P", "in0")
        self.assertEqual(doc.nodes["P"].params["value_type"], "expr")
        ins, outs = doc.ports("P")
        channel_ports = [p for p in ins if p.name.startswith("in") and p.name != "index"]
        self.assertEqual(len(channel_ports), 3)
        self.assertTrue(all(p.type.value == "expr" for p in channel_ports))
        self.assertEqual(outs[0].type.value, "expr")


class MapItemAndShiftGetTests(unittest.TestCase):
    def test_map_item_retypes_downstream_consumer(self):
        doc = GraphDocument()
        doc.add_node("map_item", {"type": "string"}, node_id="MI")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="A")
        doc.add_edge("MI", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params["elem_type"], "string")

    def test_shift_get_retypes_downstream_consumer(self):
        doc = GraphDocument()
        doc.add_node("shift_get", {"name": "acc", "type": "block"}, node_id="SG")
        doc.add_node("list_append", {"elem_type": "number"}, node_id="A")
        doc.add_edge("SG", "out", "A", "item")
        self.assertEqual(doc.nodes["A"].params["elem_type"], "block")


if __name__ == "__main__":
    unittest.main()
