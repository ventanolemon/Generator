"""
Qt-интеграция подсветки веток и подписей проводов.

Логика веток покрыта в core/test_graph_branches.py; здесь проверяется
именно ХОЛСТ: что режим включается, что раскраска пересчитывается при
правке графа (иначе она показывала бы вчерашнюю картинку — ровно та
ложь, ради ухода от которой ветку и решили не хранить), и что подпись
провода доезжает до отрисовки.

Отрисовка проверяется рендером в изображение, а не проверкой вызовов:
подпись однажды уже рисовалась «правильно» и была невидима — обводка
съедала буквы. Такое ловится только тем, что картинку смотрят.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_graph_branches_qt
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QRectF
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:                                    # pragma: no cover
    HAS_QT = False

from core.graph.document import GraphDocument  # noqa: E402


def _doc() -> GraphDocument:
    doc = GraphDocument()
    doc.add_node("constant_number", {"value": 7}, x=40, y=40, node_id="a")
    doc.add_node("constant_number", {"value": 3}, x=40, y=200, node_id="c")
    doc.add_node("constant_number", {"value": 9}, x=40, y=360, node_id="dead")
    doc.add_node("task", {"statement": "Дано #a#", "slots": ["x:number"]},
                 x=440, y=120, node_id="fin")
    doc.add_edge("a", "out", "fin", "a")
    doc.add_edge("c", "out", "fin", "x")
    return doc


@unittest.skipUnless(HAS_QT, "PyQt6 недоступен")
class BranchSceneTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _scene(self, doc=None):
        from ui.editors.graph_canvas.scene import GraphScene
        return GraphScene(doc or _doc())

    def test_mode_is_off_by_default(self):
        # При разводке проводов нужнее цвет типа порта; ветки — режим
        # чтения и включаются осознанно.
        scene = self._scene()
        self.assertFalse(scene.show_branches)
        self.assertIsNone(scene.branch_of_node("a"))

    def test_mode_gives_the_same_answer_as_the_document(self):
        scene = self._scene()
        scene.set_show_branches(True)
        self.assertEqual(scene.branch_of_node("a"), "statement")
        self.assertEqual(scene.branch_of_node("c"), "answer")
        self.assertIsNone(scene.branch_of_node("dead"))
        self.assertEqual(
            scene.branch_of_edge(("a", "out", "fin", "a")), "statement")

    def test_new_wire_recolours_the_graph(self):
        """
        Ветка зависит от ВСЕГО пути до финала: один провод перекрашивает
        цепочку. Если бы раскраска не пересчитывалась на правках, режим
        показывал бы устаревшую картину — и был бы хуже, чем ничего.
        """
        scene = self._scene()
        scene.set_show_branches(True)
        self.assertIsNone(scene.branch_of_node("dead"))
        # Правка идёт через документ + rebuild — тот же путь, которым
        # ходят инспектор и загрузка графа.
        scene.doc.add_edge("dead", "out", "fin", "x")
        scene.rebuild()
        self.assertEqual(scene.branch_of_node("dead"), "answer")
        # Вытесненный провод из `c` больше ни на что не влияет.
        self.assertIsNone(scene.branch_of_node("c"))

    def test_note_reaches_the_canvas(self):
        scene = self._scene()
        edge = scene.edge_items[0]
        scene.doc.set_edge_note(*edge.as_doc_tuple(), "подпись")
        self.assertEqual(edge._note(), "подпись")

    def test_note_widens_the_repaint_area(self):
        # Текст рисуется поверх линии и вылезает за неё: вне boundingRect
        # сцена не перерисовывает, и от подписи оставались бы хвосты.
        scene = self._scene()
        edge = scene.edge_items[0]
        narrow = edge.boundingRect().width()
        scene.doc.set_edge_note(*edge.as_doc_tuple(), "довольно длинная подпись")
        edge.prepareGeometryChange()
        self.assertGreater(edge.boundingRect().width(), narrow)

    def _render(self, scene) -> QImage:
        img = QImage(700, 560, QImage.Format.Format_ARGB32)
        painter = QPainter(img)
        scene.render(painter, target=QRectF(0, 0, 700, 560),
                     source=QRectF(0, 0, 700, 560))
        painter.end()
        return img

    def test_note_is_actually_visible_on_the_canvas(self):
        """
        Подпись однажды уже «рисовалась» — и была невидима: Qt обводит
        после заливки, и обводка в три пикселя съедала восьмой кегль
        целиком. Поэтому проверяется не вызов рисования, а ПИКСЕЛИ:
        светлых точек с подписью должно стать заметно больше.
        """
        scene = self._scene()
        before = self._render(scene)
        edge = scene.edge_items[0]
        scene.doc.set_edge_note(*edge.as_doc_tuple(),
                                "ОООООООО ППППППП ЖЖЖЖЖЖЖ")
        edge.prepareGeometryChange()
        edge.update()
        after = self._render(scene)

        def bright(img: QImage) -> int:
            count = 0
            for y in range(0, img.height(), 2):
                for x in range(0, img.width(), 2):
                    c = img.pixelColor(x, y)
                    if c.red() > 190 and c.green() > 190 and c.blue() > 190:
                        count += 1
            return count

        self.assertGreater(bright(after), bright(before) + 40)

    def test_rendering_with_branches_on_does_not_crash(self):
        scene = self._scene()
        scene.set_show_branches(True)
        self._render(scene)


if __name__ == "__main__":
    unittest.main()
