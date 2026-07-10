"""
Тесты инструментов холста: раскладка по слоям, рамки-комментарии,
ортогональные провода и починка режима панорамы (баг «узлы не двигаются
после панорамирования»).

Хелперы модели (layer_of_nodes / layered_positions / comments) — headless;
сцена и вид требуют Qt (offscreen).
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphDocument, GraphExecutor, GraphSpec

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


def _chain_doc() -> GraphDocument:
    """a,b → vd → f: два источника (слой 0), словарь (1), формула (2)."""
    doc = GraphDocument()
    doc.add_node("random_natural", {"min": 1, "max": 5}, node_id="a")
    doc.add_node("random_natural", {"min": 1, "max": 5}, node_id="b")
    doc.add_node("var_dict", {"names": ["x", "y"]}, node_id="vd")
    doc.add_node("formula", {"expr": "x + y"}, node_id="f")
    doc.add_edge("a", "out", "vd", "x")
    doc.add_edge("b", "out", "vd", "y")
    doc.add_edge("vd", "out", "f", "vars")
    return doc


class LayeredLayoutTests(unittest.TestCase):
    """Headless: раскладка по слоям — чистая функция модели."""

    def test_layers_by_longest_path(self):
        layer = _chain_doc().layer_of_nodes()
        self.assertEqual(layer["a"], 0)
        self.assertEqual(layer["b"], 0)
        self.assertEqual(layer["vd"], 1)
        self.assertEqual(layer["f"], 2)

    def test_positions_columns_and_rows(self):
        pos = _chain_doc().layered_positions(x_gap=200, y_gap=100, x0=0, y0=0)
        # столбец = слой
        self.assertEqual(pos["a"][0], 0)
        self.assertEqual(pos["vd"][0], 200)
        self.assertEqual(pos["f"][0], 400)
        # источники в одном столбце, но разных строках
        self.assertEqual(pos["a"][0], pos["b"][0])
        self.assertNotEqual(pos["a"][1], pos["b"][1])

    def test_apply_writes_model(self):
        doc = _chain_doc()
        doc.apply_layered_layout(x_gap=200, y_gap=100, x0=0, y0=0)
        self.assertEqual((doc.nodes["f"].x, doc.nodes["f"].y), (400, 0))

    def test_isolated_node_is_layer_zero(self):
        doc = GraphDocument()
        doc.add_node("random_natural", {"min": 1, "max": 5}, node_id="lonely")
        self.assertEqual(doc.layer_of_nodes()["lonely"], 0)


class CommentModelTests(unittest.TestCase):
    """Headless: рамки-комментарии в meta и round-trip."""

    def test_add_update_remove(self):
        doc = GraphDocument()
        c = doc.add_comment(x=10, y=20, text="группа")
        self.assertEqual(len(doc.comments()), 1)
        doc.update_comment(c["id"], text="новая", w=300)
        stored = doc.comments()[0]
        self.assertEqual(stored["text"], "новая")
        self.assertEqual(stored["w"], 300)
        doc.remove_comment(c["id"])
        self.assertEqual(doc.comments(), [])

    def test_unique_ids(self):
        doc = GraphDocument()
        a = doc.add_comment()
        b = doc.add_comment()
        self.assertNotEqual(a["id"], b["id"])

    def test_empty_comments_drop_meta_key(self):
        doc = GraphDocument()
        c = doc.add_comment()
        doc.remove_comment(c["id"])
        self.assertNotIn("comments", doc.to_spec_dict()["meta"])

    def test_roundtrip_preserves_comments(self):
        doc = GraphDocument()
        doc.add_comment(x=5, y=6, w=100, h=80, text="пояснение")
        again = GraphDocument.from_spec_dict(doc.to_spec_dict())
        self.assertEqual(again.comments()[0]["text"], "пояснение")

    def test_engine_ignores_comments(self):
        doc = _chain_doc()
        doc.add_comment(text="аннотация")
        # meta с комментариями не мешает движку собрать граф.
        GraphExecutor(GraphSpec.parse(doc.to_spec_dict()))


class OrthogonalMetaTests(unittest.TestCase):
    """Headless: форма проводов хранится в meta и переживает round-trip."""

    def test_flag_roundtrip(self):
        doc = _chain_doc()
        doc.meta["orthogonal_edges"] = True
        again = GraphDocument.from_spec_dict(doc.to_spec_dict())
        self.assertTrue(again.meta.get("orthogonal_edges"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class CanvasToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self, doc=None):
        from ui.editors.graph_canvas.scene import GraphScene
        return GraphScene(doc or _chain_doc())

    def test_orthogonal_toggle_reshapes_edges(self):
        # Ортогональ — режим по умолчанию: сцена стартует с ней и meta чист.
        scene = self._scene()
        edge = scene.edge_items[0]
        self.assertTrue(scene.orthogonal_edges)
        self.assertTrue(edge._is_orthogonal())
        self.assertNotIn("orthogonal_edges", scene.doc.meta)
        self.assertGreater(edge.path().elementCount(), 2)
        # Выключение — кубическая кривая, в meta явный False (умолчание
        # инвертировалось, поэтому теперь персистится именно отказ).
        scene.set_orthogonal(False)
        self.assertIs(scene.doc.meta.get("orthogonal_edges"), False)
        cubic_pts = edge.path().elementCount()
        # Включение обратно очищает meta и возвращает ломаную.
        scene.set_orthogonal(True)
        self.assertNotIn("orthogonal_edges", scene.doc.meta)
        self.assertGreater(edge.path().elementCount(), cubic_pts)

    def test_layout_moves_items_with_model(self):
        scene = self._scene()
        scene.auto_layout_layers()
        for nid, item in scene.node_items.items():
            self.assertAlmostEqual(item.x(), scene.doc.nodes[nid].x, places=3)
            self.assertAlmostEqual(item.y(), scene.doc.nodes[nid].y, places=3)

    def test_comment_lifecycle(self):
        from PyQt6.QtCore import QPointF
        from ui.editors.graph_canvas.comment import CommentItem
        scene = self._scene()
        item = scene.add_comment(QPointF(500, 500))
        self.assertIsInstance(item, CommentItem)
        self.assertEqual(len(scene.comment_items), 1)
        # перенос пишется в модель
        item.setPos(600, 640)
        self.assertAlmostEqual(scene.doc.comments()[0]["x"], 600, places=3)
        # комментарий — фон (ниже проводов/узлов)
        self.assertLess(item.zValue(), 0)
        # удаление через выделение
        item.setSelected(True)
        scene.delete_selected()
        self.assertEqual(scene.comment_items, {})
        self.assertEqual(scene.doc.comments(), [])

    def test_comments_respawn_on_rebuild(self):
        from PyQt6.QtCore import QPointF
        scene = self._scene()
        scene.add_comment(QPointF(10, 10))
        scene.rebuild()
        self.assertEqual(len(scene.comment_items), 1)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class PanDragModeTests(unittest.TestCase):
    """Починка бага: смена режима панорамы не должна «замораживать» узлы."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _view(self):
        from ui.editors.graph_canvas.scene import GraphScene, GraphCanvasView
        scene = GraphScene(_chain_doc())
        return GraphCanvasView(scene)

    def test_space_toggles_hand_when_idle(self):
        from PyQt6.QtWidgets import QGraphicsView
        V = QGraphicsView.DragMode
        v = self._view()
        self.assertEqual(v.dragMode(), V.RubberBandDrag)
        v._space_held = True
        v._sync_drag_mode()
        self.assertEqual(v.dragMode(), V.ScrollHandDrag)
        v._space_held = False
        v._sync_drag_mode()
        self.assertEqual(v.dragMode(), V.RubberBandDrag)

    def test_no_mode_switch_while_button_down(self):
        # Это и есть баг: пробел отпущен во время панорамы (ЛКМ ещё нажата) —
        # режим НЕ должен переключаться, иначе Qt застревает в hand-scroll и
        # узлы больше не двигаются.
        from PyQt6.QtWidgets import QGraphicsView
        V = QGraphicsView.DragMode
        v = self._view()
        v._space_held = True
        v._sync_drag_mode()
        v._left_down = True
        v._space_held = False
        v._sync_drag_mode()
        self.assertEqual(v.dragMode(), V.ScrollHandDrag)   # отложено
        v._left_down = False
        v._sync_drag_mode()                                 # применяется
        self.assertEqual(v.dragMode(), V.RubberBandDrag)

    def test_focus_out_recovers_pan(self):
        from PyQt6.QtWidgets import QGraphicsView
        from PyQt6.QtGui import QFocusEvent
        V = QGraphicsView.DragMode
        v = self._view()
        v._space_held = True
        v._left_down = True
        v._sync_drag_mode()
        v.focusOutEvent(QFocusEvent(QFocusEvent.Type.FocusOut))
        self.assertFalse(v._space_held)
        self.assertEqual(v.dragMode(), V.RubberBandDrag)


if __name__ == "__main__":
    unittest.main()
