"""
Qt-интеграция совместной трассировки: ортогональ — режим по умолчанию,
сцена кладёт трассы роутера в EdgeItem (после тика событий — request_reroute
коалесцируется), перенос узла перекладывает провода, наложений разных цепей
нет на уровне фактических путей сцены.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_graph_routing_qt
"""

from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:                                    # pragma: no cover
    HAS_QT = False

from core.graph.document import GraphDocument  # noqa: E402
from tests.test_graph_routing import _overlaps  # noqa: E402


def _fan_doc() -> GraphDocument:
    """4 параллельных провода в одном канале — худший случай старого Z-роутера
    (все вертикали ложились на общую середину)."""
    doc = GraphDocument()
    for i in range(4):
        doc.add_node("random_natural", {}, x=40, y=40 + i * 150,
                     node_id=f"s{i}")
    doc.add_node("var_dict", {"names": ["a", "b", "c", "d"]},
                 x=560, y=220, node_id="v")
    for i, name in enumerate(["a", "b", "c", "d"]):
        doc.add_edge(f"s{i}", "out", "v", name)
    return doc


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SceneRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self, doc):
        from ui.editors.graph_canvas.scene import GraphScene
        scene = GraphScene(doc)
        self.app.processEvents()          # request_reroute → _do_reroute
        return scene

    def test_orthogonal_is_default_and_meta_stays_clean(self):
        scene = self._scene(_fan_doc())
        self.assertTrue(scene.orthogonal_edges)
        self.assertNotIn("orthogonal_edges", scene.doc.meta)

    def test_routes_are_applied_and_do_not_overlap(self):
        scene = self._scene(_fan_doc())
        routes, nets = {}, {}
        for e in scene.edge_items:
            self.assertIsNotNone(e._route, "роутер положил трассу")
            routes[id(e)] = e._route
            nets[id(e)] = (e.src.node_id, e.src.port.name)
        self.assertEqual(_overlaps(routes, nets), [],
                         "фактические пути сцены без наложений разных цепей")

    def test_moving_node_reroutes(self):
        scene = self._scene(_fan_doc())
        edge = scene.edge_items[0]
        before = list(edge._route)
        scene.node_items["s0"].setPos(40, 700)     # itemChange → request_reroute
        self.app.processEvents()
        after = edge._route
        self.assertIsNotNone(after)
        self.assertNotEqual(before, after, "перенос узла переложил трассу")
        # Концы трассы совпадают с фактическими портами.
        p1 = edge.src.scene_center()
        self.assertAlmostEqual(after[0][0], p1.x(), places=3)
        self.assertAlmostEqual(after[0][1], p1.y(), places=3)

    def test_cubic_mode_skips_router(self):
        scene = self._scene(_fan_doc())
        scene.set_orthogonal(False)
        self.app.processEvents()
        # В кубическом режиме роутер не зовётся; старые трассы игнорируются
        # (update_path рисует кривую), а meta несёт явный False.
        self.assertIs(scene.doc.meta.get("orthogonal_edges"), False)


if __name__ == "__main__":
    unittest.main()
