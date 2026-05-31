"""
Тесты навигации GraphEditor по вложенному телу цикла (repeat.body).

Проверяют: вход в подграф кладёт уровень в стек, выход сохраняет
отредактированное тело в параметр узла, корневой граф (_root_spec_dict)
неразрушающе сворачивает все уровни. Требует Qt (редактор — виджет).
"""

from __future__ import annotations
import os
import unittest

# Без дисплея Qt по умолчанию пытается xcb и аварийно завершается. Если
# платформа не задана извне — используем offscreen (headless-совместимо).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SubgraphNavTests(unittest.TestCase):
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

    def test_enter_exit_persists_body(self):
        ed = self._editor()
        rep = ed.scene.add_node("repeat", _pt(100, 100))

        ed._enter_subgraph(rep.node_id, "body")
        self.assertEqual(len(ed._nav_stack), 1)

        ed.scene.add_node("loop_index", _pt(50, 50))
        self.assertEqual(len(ed.doc.nodes), 1)

        ed._exit_subgraph()
        self.assertEqual(len(ed._nav_stack), 0)
        body = ed.doc.nodes[rep.node_id].params.get("body")
        self.assertIsInstance(body, dict)
        self.assertEqual(len(body["nodes"]), 1)
        self.assertEqual(body["nodes"][0]["type"], "loop_index")

    def test_root_spec_dict_folds_open_subgraph(self):
        ed = self._editor()
        rep = ed.scene.add_node("repeat", _pt(100, 100))
        ed._enter_subgraph(rep.node_id, "body")
        ed.scene.add_node("loop_index", _pt(50, 50))

        # Не выходя из тела, корневой dict уже содержит body с этим узлом.
        root = ed._root_spec_dict()
        rep_node = next(n for n in root["nodes"] if n["id"] == rep.node_id)
        self.assertEqual(len(rep_node["params"]["body"]["nodes"]), 1)
        # UI остался во вложенном уровне (неразрушающе).
        self.assertEqual(len(ed._nav_stack), 1)

    def test_breadcrumb_updates(self):
        ed = self._editor()
        rep = ed.scene.add_node("repeat", _pt(100, 100))
        self.assertEqual(ed.breadcrumb.text(), "Главный граф")
        ed._enter_subgraph(rep.node_id, "body")
        self.assertIn("тело", ed.breadcrumb.text())
        ed._exit_subgraph()
        self.assertEqual(ed.breadcrumb.text(), "Главный граф")


def _pt(x, y):
    from PyQt6.QtCore import QPointF
    return QPointF(x, y)


if __name__ == "__main__":
    unittest.main()
