"""
Тесты рамки-структуры цикла на холсте (Этап C, LabVIEW-style).

Развёрнутый repeat/map рисуется рамкой (LoopFrameItem) с телом внутри:
внутренние узлы редактируются на месте, порты цикла лежат на границе рамки,
тело сериализуется обратно в params узла. «Развёрнутость» — состояние вида
в meta["expanded_nodes"], движок исполнения не затронут.

Требует Qt (offscreen) для сцены; хелперы документа — headless.
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphDocument

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


BODY = {
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
    "meta": {"layout": {"li": [10, 10], "f": [200, 10], "ov": [390, 10]}},
}


def _doc_with_repeat(expanded=True) -> GraphDocument:
    import copy
    doc = GraphDocument()
    doc.add_node("repeat", params={
        "count": 3, "outputs": ["xs:number:list"],
        "body": copy.deepcopy(BODY),
    }, x=100, y=80, node_id="rep")
    if expanded:
        doc.set_node_expanded("rep", True)
    return doc


class ExpandedMetaTests(unittest.TestCase):
    """Headless: хранение развёрнутости в meta и round-trip."""

    def test_set_and_roundtrip(self):
        doc = _doc_with_repeat(expanded=True)
        self.assertTrue(doc.is_node_expanded("rep"))
        again = GraphDocument.from_spec_dict(doc.to_spec_dict())
        self.assertTrue(again.is_node_expanded("rep"))

    def test_collapse_removes_meta_key(self):
        doc = _doc_with_repeat(expanded=True)
        doc.set_node_expanded("rep", False)
        self.assertNotIn("expanded_nodes", doc.meta)

    def test_remove_node_clears_flag(self):
        doc = _doc_with_repeat(expanded=True)
        doc.remove_node("rep")
        self.assertNotIn("expanded_nodes", doc.meta)

    def test_engine_ignores_expanded_meta(self):
        from core.graph import GraphExecutor, GraphSpec
        doc = _doc_with_repeat(expanded=True)
        ex = GraphExecutor(GraphSpec.parse(doc.to_spec_dict()))
        outs = ex.run_full()
        self.assertEqual(outs["rep"]["xs"], [1.0, 2.0, 3.0])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrameSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self, doc):
        from ui.editors.graph_canvas.scene import GraphScene
        return GraphScene(doc)

    def test_expanded_node_spawns_frame(self):
        from ui.editors.graph_canvas.frame import LoopFrameItem
        scene = self._scene(_doc_with_repeat(expanded=True))
        item = scene.node_items["rep"]
        self.assertIsInstance(item, LoopFrameItem)
        self.assertEqual(set(item.inner_nodes), {"li", "f", "ov"})
        self.assertEqual(len(item.inner_edges), 2)

    def test_collapsed_node_stays_compact(self):
        from ui.editors.graph_canvas.frame import LoopFrameItem
        scene = self._scene(_doc_with_repeat(expanded=False))
        self.assertNotIsInstance(scene.node_items["rep"], LoopFrameItem)

    def test_frame_border_ports(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        self.assertIn("count", [p.port.name for p in frame.in_ports])
        self.assertEqual([p.port.name for p in frame.out_ports], ["out", "xs"])

    def test_toggle_expand_collapse(self):
        from ui.editors.graph_canvas.frame import LoopFrameItem
        scene = self._scene(_doc_with_repeat(expanded=False))
        scene.set_frame_expanded("rep", True)
        self.assertIsInstance(scene.node_items["rep"], LoopFrameItem)
        scene.set_frame_expanded("rep", False)
        self.assertNotIsInstance(scene.node_items["rep"], LoopFrameItem)
        # Тело не потерялось при сворачивании.
        body = scene.doc.nodes["rep"].params["body"]
        self.assertEqual(len(body["nodes"]), 3)

    def test_inner_move_writes_body_local_coords(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        item = frame.inner_nodes["f"]
        origin = frame.content_origin_scene()
        item.setPos(origin.x() + 250, origin.y() + 60)
        body = scene.doc.nodes["rep"].params["body"]
        self.assertEqual(body["meta"]["layout"]["f"], [250.0, 60.0])

    def test_inner_move_clamped_to_frame(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        item = frame.inner_nodes["li"]
        origin = frame.content_origin_scene()
        item.setPos(origin.x() - 500, origin.y() - 500)   # тянем за рамку
        self.assertGreaterEqual(item.scenePos().x(), origin.x())
        self.assertGreaterEqual(item.scenePos().y(), origin.y())

    def test_frame_move_keeps_body_coords(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        before = dict(scene.doc.nodes["rep"].params["body"]["meta"]["layout"])
        frame.setPos(frame.x() + 300, frame.y() + 120)
        after = scene.doc.nodes["rep"].params["body"]["meta"]["layout"]
        self.assertEqual(before, after)
        # А сценовые позиции внутренних узлов сдвинулись вместе с рамкой.
        origin = frame.content_origin_scene()
        li = frame.inner_nodes["li"].scenePos() - origin
        self.assertAlmostEqual(li.x(), before["li"][0], delta=0.5)

    def test_inner_wire_via_commit_connection(self):
        # Новый внутренний узел + провод через общий механизм соединения.
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        item = frame.add_inner_node(scene, "constant_number")
        src = item.out_ports[0]
        dst = next(p for p in frame.inner_nodes["f"].in_ports
                   if p.port.name == "i")
        scene._commit_connection(src, dst)
        body = scene.doc.nodes["rep"].params["body"]
        self.assertIn({"from": f"{item.node_id}:out", "to": "f:i"},
                      body["edges"])

    def test_cross_border_wire_rejected(self):
        # Провод корневой узел → узел тела не создаётся (только туннели).
        doc = _doc_with_repeat(expanded=True)
        doc.add_node("constant_number", node_id="c", x=600, y=80)
        scene = self._scene(doc)
        frame = scene.node_items["rep"]
        src = scene.node_items["c"].out_ports[0]
        dst = next(p for p in frame.inner_nodes["f"].in_ports
                   if p.port.name == "i")
        edges_before = list(scene.doc.nodes["rep"].params["body"]["edges"])
        scene._commit_connection(src, dst)
        self.assertEqual(scene.doc.nodes["rep"].params["body"]["edges"],
                         edges_before)
        self.assertEqual(len(scene.doc.edges), 0)

    def test_delete_inner_node_updates_body(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        frame.inner_nodes["ov"].setSelected(True)
        scene.delete_selected()
        body = scene.doc.nodes["rep"].params["body"]
        self.assertEqual({n["id"] for n in body["nodes"]}, {"li", "f"})
        self.assertEqual(len(body["edges"]), 1)   # f→ov отрезан

    def test_delete_frame_removes_node_and_inner_items(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        frame = scene.node_items["rep"]
        inner = list(frame.inner_nodes.values())
        frame.setSelected(True)
        scene.delete_selected()
        self.assertNotIn("rep", scene.doc.nodes)
        for it in inner:
            self.assertIsNone(it.scene())

    def test_outer_wiring_to_frame_ports(self):
        doc = _doc_with_repeat(expanded=True)
        doc.add_node("constant_number", node_id="c", x=600, y=80)
        scene = self._scene(doc)
        frame = scene.node_items["rep"]
        src = scene.node_items["c"].out_ports[0]
        dst = next(p for p in frame.in_ports if p.port.name == "count")
        scene._commit_connection(src, dst)
        self.assertEqual(scene.doc.edges[0].as_tuple(),
                         ("c", "out", "rep", "count"))

    def test_inner_task_marked_forbidden(self):
        doc = _doc_with_repeat(expanded=True)
        body = doc.nodes["rep"].params["body"]
        body["nodes"].append({"id": "t", "type": "static_task"})
        scene = self._scene(doc)
        frame = scene.node_items["rep"]
        self.assertEqual(frame.inner_nodes["t"].result_role, "forbidden")
        self.assertIsNone(frame.inner_nodes["f"].result_role)

    def test_corrupt_body_falls_back_to_compact(self):
        from ui.editors.graph_canvas.frame import LoopFrameItem
        doc = _doc_with_repeat(expanded=True)
        doc.nodes["rep"].params["body"] = {
            "nodes": [{"id": "x", "type": "no_such_type"}], "edges": [],
        }
        scene = self._scene(doc)
        self.assertNotIsInstance(scene.node_items["rep"], LoopFrameItem)

    def test_all_node_items_includes_inner(self):
        scene = self._scene(_doc_with_repeat(expanded=True))
        ids = {it.node_id for it in scene.all_node_items()}
        self.assertEqual(ids, {"rep", "li", "f", "ov"})


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class FrameEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self, doc=None):
        from ui.editors.graph_editor import GraphEditor

        class FakeRepo:
            def get_partition(self, *a, **k):
                return None

        ed = GraphEditor(FakeRepo(), subject_id=3, partition_id=None)
        ed._load_doc(doc or GraphDocument())
        return ed

    def test_palette_adds_into_selected_frame(self):
        ed = self._editor(_doc_with_repeat(expanded=True))
        frame = ed.scene.node_items["rep"]
        frame.setSelected(True)
        ed._on_palette_add("constant_number")
        body = ed.doc.nodes["rep"].params["body"]
        self.assertIn("constant_number_1", {n["id"] for n in body["nodes"]})
        self.assertEqual(len(ed.doc.nodes), 1)    # в корень не добавился

    def test_palette_blocks_task_into_frame(self):
        from PyQt6.QtWidgets import QMessageBox
        ed = self._editor(_doc_with_repeat(expanded=True))
        ed.scene.node_items["rep"].setSelected(True)
        calls = []
        orig = QMessageBox.warning
        QMessageBox.warning = staticmethod(lambda *a, **k: calls.append(a))
        try:
            ed._on_palette_add("static_task")
        finally:
            QMessageBox.warning = orig
        self.assertEqual(len(calls), 1)
        body = ed.doc.nodes["rep"].params["body"]
        self.assertNotIn("static_task", {n["type"] for n in body["nodes"]})

    def test_inner_selection_routes_inspector_to_body_doc(self):
        ed = self._editor(_doc_with_repeat(expanded=True))
        frame = ed.scene.node_items["rep"]
        frame.inner_nodes["f"].setSelected(True)
        self.assertIs(ed.inspector.doc, frame.body_doc)
        self.assertIs(ed._sel_doc, frame.body_doc)

    def test_inner_subgraph_navigation_chains_levels(self):
        # «Открыть подграф…» у вложенного цикла внутри рамки: входим в тело
        # рамки, затем в тело вложенного цикла — два уровня в стеке.
        doc = _doc_with_repeat(expanded=True)
        body = doc.nodes["rep"].params["body"]
        body["nodes"].append({"id": "rep2", "type": "repeat",
                              "params": {"count": 2}})
        ed = self._editor(doc)
        ed._enter_subgraph("rep2", "body")
        self.assertEqual(len(ed._nav_stack), 2)
        self.assertIn("rep2", ed.breadcrumb.text())
        ed._flush_subgraphs()
        self.assertEqual(len(ed._nav_stack), 0)

    def test_undo_restores_collapsed_state(self):
        ed = self._editor(_doc_with_repeat(expanded=False))
        ed.scene.set_frame_expanded("rep", True)
        self.assertTrue(ed.doc.is_node_expanded("rep"))
        ed.undo()
        self.assertFalse(ed.doc.is_node_expanded("rep"))

    def test_root_spec_reflects_inner_edits_live(self):
        ed = self._editor(_doc_with_repeat(expanded=True))
        frame = ed.scene.node_items["rep"]
        frame.add_inner_node(ed.scene, "constant_number")
        root = ed._root_spec_dict()
        rep = next(n for n in root["nodes"] if n["id"] == "rep")
        self.assertIn("constant_number_1",
                      {n["id"] for n in rep["params"]["body"]["nodes"]})

    def test_check_validates_frame_body(self):
        # Туннель объявлен, output_var удалили прямо в рамке → «Проверить»
        # видит расхождение (тело синхронизировано в params).
        ed = self._editor(_doc_with_repeat(expanded=True))
        frame = ed.scene.node_items["rep"]
        frame.inner_nodes["ov"].setSelected(True)
        ed.scene.delete_selected()
        ed._on_check()
        self.assertIn("туннель", ed.preview.toPlainText())


if __name__ == "__main__":
    unittest.main()
