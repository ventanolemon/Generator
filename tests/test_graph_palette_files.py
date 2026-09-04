"""
Тесты раздела «Словари» в палитре: обнаружение файлов, авто-определение типа
узла по содержимому, сигнал add_file_requested и интеграция с редактором.

Требует Qt (палитра — виджет).
"""

from __future__ import annotations
import json
import os
import unittest
from core.tmpdb import temp_path  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF
    HAS_QT = True
except Exception:
    HAS_QT = False


def _write(obj, suffix=".json") -> str:
    path = temp_path(suffix=suffix)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class DetectTypeTests(unittest.TestCase):
    def test_words_vocabulary(self):
        from ui.editors.graph_canvas.palette import _node_type_for_file
        p = _write({"vocabulary": [{"term": "a", "translation": "б"}]})
        try:
            self.assertEqual(_node_type_for_file(p), "words_file")
        finally:
            os.remove(p)

    def test_words_direct(self):
        from ui.editors.graph_canvas.palette import _node_type_for_file
        p = _write({"a": "б", "c": "д"})
        try:
            self.assertEqual(_node_type_for_file(p), "words_file")
        finally:
            os.remove(p)

    def test_sentences(self):
        from ui.editors.graph_canvas.palette import _node_type_for_file
        p = _write([{"template": "A ___ b.", "answers": ["x"]}])
        try:
            self.assertEqual(_node_type_for_file(p), "sentences_file")
        finally:
            os.remove(p)

    def test_unknown(self):
        from ui.editors.graph_canvas.palette import _node_type_for_file
        p = _write(12345)
        try:
            self.assertIsNone(_node_type_for_file(p))
        finally:
            os.remove(p)


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class PaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_has_files_section(self):
        from ui.editors.graph_canvas.palette import NodePalette
        pal = NodePalette()
        tops = [pal.tree.topLevelItem(i).text(0)
                for i in range(pal.tree.topLevelItemCount())]
        # Раздел появляется, если есть resources/words с файлами.
        from ui.editors.graph_canvas.palette import _words_dir
        wd = _words_dir()
        if wd and wd.exists() and list(wd.glob("*.json")):
            self.assertTrue(any("Словари" in t for t in tops))

    def test_double_click_file_emits_path(self):
        from ui.editors.graph_canvas.palette import NodePalette, _FILE_ROLE
        from PyQt6.QtWidgets import QTreeWidgetItem
        from PyQt6.QtCore import Qt
        pal = NodePalette()
        got = []
        pal.add_file_requested.connect(lambda t, p: got.append((t, p)))
        # Искусственный файловый элемент.
        item = QTreeWidgetItem(["demo"])
        item.setData(0, Qt.ItemDataRole.UserRole, "words_file")
        item.setData(0, _FILE_ROLE, "/tmp/demo.json")
        pal._on_double_click(item, 0)
        self.assertEqual(got, [("words_file", "/tmp/demo.json")])

    def test_double_click_regular_node_emits_type_only(self):
        from ui.editors.graph_canvas.palette import NodePalette
        from PyQt6.QtWidgets import QTreeWidgetItem
        from PyQt6.QtCore import Qt
        pal = NodePalette()
        got_type = []
        got_file = []
        pal.add_requested.connect(lambda t: got_type.append(t))
        pal.add_file_requested.connect(lambda t, p: got_file.append((t, p)))
        item = QTreeWidgetItem(["Константа"])
        item.setData(0, Qt.ItemDataRole.UserRole, "constant_number")
        pal._on_double_click(item, 0)
        self.assertEqual(got_type, ["constant_number"])
        self.assertEqual(got_file, [])


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class EditorIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_add_file_sets_param(self):
        from ui.editors.graph_editor import GraphEditor
        from core.graph import GraphDocument

        class FakeRepo:
            def get_partition(self, *a, **k):
                return None

        ed = GraphEditor(FakeRepo(), subject_id=3, partition_id=None)
        ed._load_doc(GraphDocument())
        p = _write({"vocabulary": [{"term": "a", "translation": "б"}]})
        try:
            ed._on_palette_add_file("words_file", p)
            nid = list(ed.doc.nodes)[0]
            node = ed.doc.nodes[nid]
            self.assertEqual(node.type, "words_file")
            self.assertEqual(node.params["file"], p)
        finally:
            os.remove(p)


if __name__ == "__main__":
    unittest.main()
