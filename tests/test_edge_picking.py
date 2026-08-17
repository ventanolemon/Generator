"""
Щелчок по проводу выделяет БЛИЖАЙШИЙ провод, а не первый попавшийся.

Дефект найден живым использованием: провод, проходящий внутри угла
другого, выделить было нельзя — щелчок доставался соседу. Причина в
устройстве, а не в опечатке: Qt отдаёт верхний по Z элемент, а Z у всех
проводов одинаковый (`setZValue(0)`), — значит «верхний» на деле
определяется порядком добавления в сцену.

Раскладка проверки подобрана замером, а не на глаз: два перекрещивающихся
провода, точка щелчка — на первом, в 3.8 пикселя от него и в 6.8 от
второго. Qt в этой точке отдавал ВТОРОЙ (он добавлен позже). Ровно это и
видел пользователь.

Запуск:
    python -m unittest tests.test_edge_picking
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QGraphicsView

from core.graph import GraphDocument
from ui.editors.graph_canvas.items import EdgeItem
from ui.editors.graph_canvas.scene import GraphScene


def _crossing_scene(orthogonal: bool = False) -> GraphScene:
    """
    Два провода крест-накрест: сверху вниз и снизу вверх.

    Провода в одну и ту же пару портов расходятся и не накладываются —
    на такой раскладке дефект не воспроизводится. Нужны именно
    пересекающиеся трассы.
    """
    doc = GraphDocument()
    doc.meta["orthogonal_edges"] = orthogonal
    top = doc.add_node("number_range", {}); doc.set_pos(top.id, 0, 0)
    bottom = doc.add_node("number_range", {}); doc.set_pos(bottom.id, 0, 400)
    lower = doc.add_node("expr_binop", {"op": "mul"})
    doc.set_pos(lower.id, 600, 400)
    upper = doc.add_node("expr_binop", {"op": "add"})
    doc.set_pos(upper.id, 600, 0)
    doc.add_edge(top.id, "out", lower.id, "a")       # добавлен первым
    doc.add_edge(bottom.id, "out", upper.id, "a")    # добавлен вторым
    return GraphScene(doc)


def _contested_point(first: EdgeItem, second: EdgeItem) -> QPointF | None:
    """
    Точка, где щелчок спорный: лежит в зоне попадания ОБОИХ проводов, но
    ближе к первому — тому, который старый разбор проигрывал.
    """
    for i in range(201):
        point = first.path().pointAtPercent(i / 200)
        if not second.shape().contains(second.mapFromScene(point)):
            continue
        if first.distance_to(point) < second.distance_to(point):
            return point
    return None


class NearestWinsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = _crossing_scene()
        self.first, self.second = self.scene.edge_items
        self.point = _contested_point(self.first, self.second)
        if self.point is None:
            self.skipTest("трассы не пересеклись в этой раскладке")

    def test_the_old_rule_would_pick_the_wrong_wire(self):
        """
        Регрессия наоборот: показываем, что разбор Qt в этой точке даёт
        ДРУГОЙ провод. Без этого проверка ниже не отличается от
        «выделяется единственный подходящий».
        """
        qt_choice = self.scene.items(self.point)[0]
        self.assertIs(qt_choice, self.second)
        self.assertLess(self.first.distance_to(self.point),
                        self.second.distance_to(self.point))

    def test_nearest_edge_picks_the_wire_under_the_cursor(self):
        self.assertIs(self.scene._nearest_edge(self.point), self.first)

    def test_click_selects_the_nearest_wire(self):
        self.scene.clearSelection()
        _click(self.scene, self.point)
        self.assertEqual(self.scene.selectedItems(), [self.first])

    def test_orthogonal_routes_behave_the_same(self):
        scene = _crossing_scene(orthogonal=True)
        first, second = scene.edge_items
        point = _contested_point(first, second)
        if point is None:
            self.skipTest("ортогональные трассы не пересеклись")
        self.assertIs(scene._nearest_edge(point), first)


class PlainClickTests(unittest.TestCase):
    """Обычные щелчки не должны сломаться от новой ветки разбора."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.scene = _crossing_scene()

    def test_each_wire_can_be_selected_on_its_own(self):
        for index, edge in enumerate(self.scene.edge_items):
            with self.subTest(провод=index):
                self.scene.clearSelection()
                _click(self.scene, edge.path().pointAtPercent(0.25))
                self.assertEqual(self.scene.selectedItems(), [edge])

    def test_click_on_empty_space_selects_nothing(self):
        _click(self.scene, self.scene.edge_items[0].path().pointAtPercent(0.25))
        self.assertTrue(self.scene.selectedItems())
        _click(self.scene, QPointF(-500, -500))
        self.assertEqual(self.scene.selectedItems(), [])

    def test_nodes_are_still_selectable(self):
        from ui.editors.graph_canvas.items import NodeItem
        node = next(it for it in self.scene.items() if isinstance(it, NodeItem))
        _click(self.scene, node.sceneBoundingRect().center())
        self.assertEqual(self.scene.selectedItems(), [node])


class HitAreaTests(unittest.TestCase):
    """Зона попадания шире штриха: по линии в 2.4 пикселя не попасть."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Сцену держим: без ссылки она собирается вместе со своими
        # элементами, и провод оказывается удалён на стороне C++.
        self.scene = _crossing_scene()
        self.edge = self.scene.edge_items[0]

    def test_a_few_pixels_off_the_wire_still_hits_it(self):
        centre = self.edge.path().pointAtPercent(0.5)
        near = QPointF(centre.x(), centre.y() + EdgeItem.HIT_WIDTH / 2 - 1.5)
        self.assertTrue(
            self.edge.shape().contains(self.edge.mapFromScene(near)))

    def test_far_off_the_wire_does_not_hit_it(self):
        centre = self.edge.path().pointAtPercent(0.5)
        far = QPointF(centre.x(), centre.y() + EdgeItem.HIT_WIDTH * 3)
        self.assertFalse(
            self.edge.shape().contains(self.edge.mapFromScene(far)))

    def test_distance_is_zero_on_the_wire(self):
        centre = self.edge.path().pointAtPercent(0.5)
        self.assertLess(self.edge.distance_to(centre), 1.0)

    def test_distance_grows_with_offset(self):
        centre = self.edge.path().pointAtPercent(0.5)
        near = self.edge.distance_to(QPointF(centre.x(), centre.y() + 5))
        far = self.edge.distance_to(QPointF(centre.x(), centre.y() + 50))
        self.assertLess(near, far)


def _click(scene: GraphScene, point: QPointF) -> None:
    """
    Настоящий щелчок мышью через представление.

    `QGraphicsSceneMouseEvent` в PyQt6 нельзя создать из Python, а
    подделка объекта события проверяла бы наш собственный макет вместо
    доставки Qt — то есть ровно ту часть, где дефект и жил.
    """
    view = QGraphicsView(scene)
    view.resize(900, 700)
    view.setSceneRect(scene.sceneRect())
    view.show()
    QTest.qWaitForWindowExposed(view)
    pos = view.mapFromScene(point)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, QPoint(pos.x(), pos.y()))
    view.hide()
    view.setScene(None)


if __name__ == "__main__":
    unittest.main()
