"""
PR-1 фазы 3b-2: константы-источники (bool перенесён в source, добавлена строка)
и z-order контекстного меню сцены.

Источники проверяются headless; z-order — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, ExecContext
from core.graph.nodes.sources import ConstantBoolNode, ConstantStringNode

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx():
    return ExecContext(rng=random.Random(0))


class SourceNodeTests(unittest.TestCase):
    def test_constant_bool_is_source(self):
        entry = next(e for e in DEFAULT_REGISTRY.palette()
                     if e["type_id"] == "constant_bool")
        self.assertEqual(entry["category"], "source")

    def test_constant_bool_value(self):
        self.assertIs(ConstantBoolNode("b", {"value": "true"}).compute({}, _ctx())["out"], True)
        self.assertIs(ConstantBoolNode("b", {"value": "false"}).compute({}, _ctx())["out"], False)

    def test_constant_string_registered_as_source(self):
        entry = next(e for e in DEFAULT_REGISTRY.palette()
                     if e["type_id"] == "constant_string")
        self.assertEqual(entry["category"], "source")

    def test_constant_string_value(self):
        self.assertEqual(ConstantStringNode("s", {"value": "привет"}).compute({}, _ctx())["out"],
                         "привет")
        self.assertEqual(ConstantStringNode("s", {}).compute({}, _ctx())["out"], "")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ZOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self):
        from core.graph import GraphDocument
        from ui.editors.graph_canvas import GraphScene
        scene = GraphScene(GraphDocument())
        a = scene.add_node("constant_number", QPointF(0, 0))
        b = scene.add_node("constant_number", QPointF(100, 0))
        c = scene.add_node("constant_number", QPointF(200, 0))
        return scene, a, b, c

    def test_to_front_and_back(self):
        scene, a, b, c = self._scene()
        scene.node_to_front(a)
        self.assertGreater(a.zValue(), b.zValue())
        self.assertGreater(a.zValue(), c.zValue())
        scene.node_to_back(a)
        self.assertLess(a.zValue(), b.zValue())
        self.assertLess(a.zValue(), c.zValue())

    def test_raise_and_lower_one_step(self):
        scene, a, b, c = self._scene()
        scene._normalize_z()          # a<b<c (1,2,3)
        self.assertLess(a.zValue(), b.zValue())
        scene.raise_node(a)           # a поднимается над b
        self.assertGreater(a.zValue(), b.zValue())
        self.assertLess(a.zValue(), c.zValue())
        scene.lower_node(a)           # обратно
        self.assertLess(a.zValue(), b.zValue())

    def test_nodes_stay_above_edges(self):
        # Все узлы держатся z>=1, провода на z=0.
        scene, a, b, c = self._scene()
        scene.node_to_back(b)
        for it in scene.node_items.values():
            self.assertGreaterEqual(it.zValue(), 1.0)


if __name__ == "__main__":
    unittest.main()
