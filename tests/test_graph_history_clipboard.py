"""
Тесты undo/redo (GraphHistory) и копирования/вставки узлов.

GraphHistory — headless (чистая структура данных). Копирование/вставка и
интеграция с редактором — под Qt (offscreen).
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.editors.graph_canvas.history import GraphHistory

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF
    HAS_QT = True
except Exception:
    HAS_QT = False


class HistoryTests(unittest.TestCase):
    def _snap(self, n):
        return {"nodes": list(range(n)), "edges": []}

    def test_reset_then_no_undo(self):
        h = GraphHistory()
        h.reset(self._snap(0))
        self.assertFalse(h.can_undo())
        self.assertFalse(h.can_redo())

    def test_push_enables_undo(self):
        h = GraphHistory()
        h.reset(self._snap(0))
        h.push(self._snap(1))
        self.assertTrue(h.can_undo())
        self.assertFalse(h.can_redo())

    def test_undo_redo_cycle(self):
        h = GraphHistory()
        h.reset(self._snap(0))
        h.push(self._snap(1))
        h.push(self._snap(2))
        self.assertEqual(h.undo(), self._snap(1))
        self.assertEqual(h.undo(), self._snap(0))
        self.assertIsNone(h.undo())            # граница
        self.assertEqual(h.redo(), self._snap(1))
        self.assertEqual(h.redo(), self._snap(2))
        self.assertIsNone(h.redo())            # граница

    def test_push_truncates_redo_tail(self):
        h = GraphHistory()
        h.reset(self._snap(0))
        h.push(self._snap(1))
        h.push(self._snap(2))
        h.undo()                               # на снимке 1
        h.push(self._snap(9))                  # новая ветка — redo обрезан
        self.assertFalse(h.can_redo())
        self.assertEqual(h.undo(), self._snap(1))

    def test_duplicate_push_ignored(self):
        h = GraphHistory()
        h.reset(self._snap(1))
        h.push(self._snap(1))                  # тот же снимок
        self.assertFalse(h.can_undo())

    def test_limit_caps_size(self):
        h = GraphHistory(limit=3)
        h.reset(self._snap(0))
        for i in range(1, 10):
            h.push(self._snap(i))
        # не больше лимита
        self.assertLessEqual(len(h._snaps), 3)

    def test_snapshots_are_isolated(self):
        # Изменение исходного словаря не должно влиять на сохранённый снимок
        # (deepcopy при reset/push/undo).
        h = GraphHistory()
        s = {"nodes": [1]}
        h.reset(s)
        h.push({"nodes": [1, 2]})
        s["nodes"].append(42)          # мутируем исходник после сохранения
        snap = h.undo()
        self.assertEqual(snap, {"nodes": [1]})


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class EditorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self):
        from ui.editors.graph_editor import GraphEditor
        from core.graph import GraphDocument

        class FakeRepo:
            def get_partition(self, *a, **k):
                return None

        ed = GraphEditor(FakeRepo(), subject_id=3, partition_id=None)
        ed._load_doc(GraphDocument())
        return ed

    def test_undo_redo_add(self):
        ed = self._editor()
        ed.scene.add_node("constant_number", QPointF(0, 0))
        ed.scene.add_node("constant_number", QPointF(100, 0))
        self.assertEqual(len(ed.doc.nodes), 2)
        ed.undo()
        self.assertEqual(len(ed.doc.nodes), 1)
        ed.undo()
        self.assertEqual(len(ed.doc.nodes), 0)
        ed.redo()
        self.assertEqual(len(ed.doc.nodes), 1)

    def test_undo_delete(self):
        ed = self._editor()
        it = ed.scene.add_node("constant_number", QPointF(0, 0))
        it.setSelected(True)
        ed.scene.delete_selected()
        self.assertEqual(len(ed.doc.nodes), 0)
        ed.undo()
        self.assertEqual(len(ed.doc.nodes), 1)

    def test_copy_paste_single(self):
        ed = self._editor()
        it = ed.scene.add_node("constant_number", QPointF(0, 0))
        it.setSelected(True)
        ed.copy_selection()
        ed.paste_clipboard()
        self.assertEqual(len(ed.doc.nodes), 2)
        # id уникальны
        self.assertEqual(len(set(ed.doc.nodes)), 2)

    def test_copy_paste_preserves_internal_edge(self):
        ed = self._editor()
        c = ed.scene.add_node("constant_number", QPointF(0, 0))
        vd = ed.scene.add_node("var_dict", QPointF(200, 0))
        ed.doc.set_params(vd.node_id, {"names": ["a"]})
        ed.scene.refresh_node(vd.node_id)
        cid, vid = c.node_id, vd.node_id
        ed.scene._commit_connection(ed.scene._find_port(cid, "out", True),
                                    ed.scene._find_port(vid, "a", False))
        self.assertEqual(len(ed.doc.edges), 1)
        ed.scene.node_items[cid].setSelected(True)
        ed.scene.node_items[vid].setSelected(True)
        ed.copy_selection()
        ed.paste_clipboard()
        self.assertEqual(len(ed.doc.nodes), 4)
        self.assertEqual(len(ed.doc.edges), 2)

    def test_paste_offsets_position(self):
        ed = self._editor()
        it = ed.scene.add_node("constant_number", QPointF(50, 50))
        it.setSelected(True)
        ed.copy_selection()
        ed.paste_clipboard()
        xs = sorted((n.x, n.y) for n in ed.doc.nodes.values())
        self.assertNotEqual(xs[0], xs[1])      # вставленный сдвинут

    def test_undo_paste(self):
        ed = self._editor()
        it = ed.scene.add_node("constant_number", QPointF(0, 0))
        it.setSelected(True)
        ed.copy_selection()
        ed.paste_clipboard()
        self.assertEqual(len(ed.doc.nodes), 2)
        ed.undo()
        self.assertEqual(len(ed.doc.nodes), 1)

    def test_move_snapshot_undo(self):
        ed = self._editor()
        it = ed.scene.add_node("constant_number", QPointF(0, 0))
        nid = it.node_id
        ed.doc.set_pos(nid, 500, 300)
        ed.snapshot_after_move()
        ed.undo()
        self.assertEqual((ed.doc.nodes[nid].x, ed.doc.nodes[nid].y), (0.0, 0.0))

    def test_select_all(self):
        ed = self._editor()
        c = ed.scene.add_node("constant_number", QPointF(0, 0))
        vd = ed.scene.add_node("var_dict", QPointF(200, 0))
        ed.doc.set_params(vd.node_id, {"names": ["a"]})
        ed.scene.refresh_node(vd.node_id)
        ed.scene._commit_connection(
            ed.scene._find_port(c.node_id, "out", True),
            ed.scene._find_port(vd.node_id, "a", False))
        ed.scene.select_all()
        nsel = sum(1 for it in ed.scene.node_items.values() if it.isSelected())
        esel = sum(1 for e in ed.scene.edge_items if e.isSelected())
        self.assertEqual((nsel, esel), (2, 1))

    def test_edge_paint_when_selected(self):
        # Выделённый провод рисуется без ошибок (жёлтая обводка в paint).
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtCore import QRectF
        ed = self._editor()
        c = ed.scene.add_node("constant_number", QPointF(0, 0))
        vd = ed.scene.add_node("var_dict", QPointF(200, 0))
        ed.doc.set_params(vd.node_id, {"names": ["a"]})
        ed.scene.refresh_node(vd.node_id)
        ed.scene._commit_connection(
            ed.scene._find_port(c.node_id, "out", True),
            ed.scene._find_port(vd.node_id, "a", False))
        ed.scene.edge_items[0].setSelected(True)
        img = QImage(200, 100, QImage.Format.Format_ARGB32)
        p = QPainter(img)
        ed.scene.render(p, target=QRectF(0, 0, 200, 100))
        p.end()
        self.assertTrue(ed.scene.edge_items[0].isSelected())


if __name__ == "__main__":
    unittest.main()
