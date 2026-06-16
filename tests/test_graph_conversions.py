"""
Тесты видимости конверсий (Этап B): реестр конвертеров + UX редактора.

find_converter отвечает «у меня X, хочу Y — какой узел вставить»; редактор
подсвечивает совместимые порты при протягивании (зелёный — напрямую, янтарный —
через конвертер) и умеет вставить узел-конвертер между двумя портами.

Реестр — headless; подсветка/вставка — под Qt (offscreen).
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphDocument, PortType, conversion_table, find_converter

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


class FindConverterTests(unittest.TestCase):
    def test_compatible_types_need_no_converter(self):
        self.assertIsNone(find_converter(PortType.NUMBER, PortType.NUMBER))
        self.assertIsNone(find_converter(PortType.NUMBER, PortType.EXPR))   # авто
        self.assertIsNone(find_converter(PortType.BLOCK, PortType.BLOCK_LIST))  # авто
        self.assertIsNone(find_converter(PortType.NUMBER, PortType.ANY))    # ANY

    def test_scalar_to_block_uses_to_block(self):
        for src in (PortType.NUMBER, PortType.STRING, PortType.BOOL,
                    PortType.EXPR, PortType.MATRIX, PortType.IMAGE):
            self.assertEqual(find_converter(src, PortType.BLOCK), "to_block")

    def test_scalar_to_block_list_via_to_block(self):
        # to_block даёт BLOCK, а он авто-повышается до BLOCK_LIST.
        self.assertEqual(find_converter(PortType.NUMBER, PortType.BLOCK_LIST),
                         "to_block")

    def test_expr_to_number(self):
        self.assertEqual(find_converter(PortType.EXPR, PortType.NUMBER), "expr_eval")

    def test_list_converters(self):
        self.assertEqual(find_converter(PortType.LIST, PortType.MATRIX),
                         "list_to_matrix")
        self.assertEqual(find_converter(PortType.LIST, PortType.NUMBER),
                         "list_length")
        self.assertEqual(find_converter(PortType.LIST, PortType.STRING), "list_join")

    def test_no_converter_returns_none(self):
        self.assertIsNone(find_converter(PortType.STRING, PortType.NUMBER))
        self.assertIsNone(find_converter(PortType.MATRIX, PortType.WORDS))

    def test_all_registry_targets_are_real_nodes(self):
        doc = GraphDocument()
        for _src, _dst, node in conversion_table():
            if node.startswith("("):     # авто-повышение, не узел
                continue
            self.assertTrue(doc.registry.has(node),
                            f"конвертер {node!r} не зарегистрирован")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class DragHighlightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self):
        from ui.editors.graph_canvas.scene import GraphScene
        doc = GraphDocument()
        # число (NUMBER out) + текстовый блок (STRING in) + узел EXPR-приёмник.
        doc.add_node("constant_number", node_id="n", x=0, y=0)
        doc.add_node("text_block", node_id="tb", x=300, y=0)      # вход STRING
        doc.add_node("expr_eval", node_id="ee", x=300, y=200)     # вход EXPR
        doc.add_node("to_block", node_id="b", x=300, y=400)       # вход ANY
        return GraphScene(doc)

    def _port(self, scene, node_id, name, is_output):
        return scene._find_port(node_id, name, is_output)

    def test_highlights_classify_ports_on_drag(self):
        scene = self._scene()
        src = self._port(scene, "n", "out", True)         # NUMBER выход
        scene._apply_drag_highlights(src)
        # ANY-вход to_block — прямая совместимость (ok).
        self.assertEqual(self._port(scene, "b", "in", False).highlight, "ok")
        # EXPR-вход expr_eval — NUMBER→EXPR авто, тоже ok.
        self.assertEqual(self._port(scene, "ee", "in", False).highlight, "ok")
        # STRING-вход text_block — нужен конвертер (NUMBER→BLOCK через to_block),
        # но STRING-вход напрямую несовместим → нет (NUMBER↛STRING).
        self.assertIsNone(self._port(scene, "tb", "text", False).highlight)
        # Сам источник не подсвечен.
        self.assertIsNone(src.highlight)

    def test_convert_highlight_for_block_input(self):
        # NUMBER-выход → BLOCK-вход (block_list.in0) подсвечивается 'convert'.
        from ui.editors.graph_canvas.scene import GraphScene
        doc = GraphDocument()
        doc.add_node("constant_number", node_id="n", x=0, y=0)
        doc.add_node("block_list", params={"count": 1}, node_id="bl", x=300, y=0)
        scene = GraphScene(doc)
        src = scene._find_port("n", "out", True)
        scene._apply_drag_highlights(src)
        self.assertEqual(scene._find_port("bl", "in0", False).highlight, "convert")

    def test_clear_highlights(self):
        scene = self._scene()
        src = self._port(scene, "n", "out", True)
        scene._apply_drag_highlights(src)
        scene._clear_drag_highlights()
        for p in scene._all_port_items():
            self.assertIsNone(p.highlight)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class InsertConverterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_insert_to_block_between_number_and_block_input(self):
        from ui.editors.graph_canvas.scene import GraphScene
        doc = GraphDocument()
        doc.add_node("constant_number", node_id="n", x=0, y=0)
        doc.add_node("block_list", params={"count": 1}, node_id="bl", x=400, y=0)
        scene = GraphScene(doc)
        out_p = scene._find_port("n", "out", True)
        in_p = scene._find_port("bl", "in0", False)
        ok = scene.insert_converter(out_p, in_p, "to_block")
        self.assertTrue(ok)
        # Появился узел to_block, провода n→to_block→bl.
        tb = [nid for nid, nd in scene.doc.nodes.items() if nd.type == "to_block"]
        self.assertEqual(len(tb), 1)
        conv = tb[0]
        edges = {e.as_tuple() for e in scene.doc.edges}
        self.assertIn(("n", "out", conv, "in"), edges)
        self.assertIn((conv, "out", "bl", "in0"), edges)

    def test_insert_expr_eval_between_expr_and_number(self):
        from ui.editors.graph_canvas.scene import GraphScene
        doc = GraphDocument()
        # matrix_det выдаёт EXPR; constraint требует NUMBER на входе in.
        doc.add_node("symbol", node_id="s", x=0, y=0)            # EXPR out
        doc.add_node("constraint", node_id="c", x=400, y=0)      # NUMBER in
        scene = GraphScene(doc)
        out_p = scene._find_port("s", "out", True)
        in_p = scene._find_port("c", "in", False)
        ok = scene.insert_converter(out_p, in_p, "expr_eval")
        self.assertTrue(ok)
        conv = [nid for nid, nd in scene.doc.nodes.items()
                if nd.type == "expr_eval"][0]
        edges = {e.as_tuple() for e in scene.doc.edges}
        self.assertIn(("s", "out", conv, "in"), edges)
        self.assertIn((conv, "out", "c", "in"), edges)

    def test_insert_replaces_existing_edge_on_input(self):
        from ui.editors.graph_canvas.scene import GraphScene
        doc = GraphDocument()
        doc.add_node("constant_number", node_id="n", x=0, y=0)
        doc.add_node("constant_string", node_id="s", x=0, y=200)
        doc.add_node("block_list", params={"count": 1}, node_id="bl", x=400, y=0)
        # Уже есть провод s(STRING)→... нет, in0 ждёт BLOCK. Поставим заглушку:
        doc.add_node("text_block", node_id="tb", x=200, y=200)
        doc.add_edge("tb", "out", "bl", "in0")
        scene = GraphScene(doc)
        out_p = scene._find_port("n", "out", True)
        in_p = scene._find_port("bl", "in0", False)
        scene.insert_converter(out_p, in_p, "to_block")
        # Старый провод tb→bl:in0 вытеснен.
        srcs = {(e.from_node, e.to_node, e.to_port) for e in scene.doc.edges}
        self.assertNotIn(("tb", "bl", "in0"), srcs)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class LegendDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_legend_lists_every_type(self):
        from ui.editors.graph_canvas.legend import TYPE_MEANINGS
        for pt in PortType:
            self.assertIn(pt, TYPE_MEANINGS, f"нет описания типа {pt}")

    def test_dialog_builds(self):
        from ui.editors.graph_canvas.legend import TypeLegendDialog
        dlg = TypeLegendDialog()
        self.assertIn("Типы", dlg.windowTitle())


if __name__ == "__main__":
    unittest.main()
