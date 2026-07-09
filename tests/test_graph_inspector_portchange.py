"""
Регрессия: смена типа входного/выходного порта (параметр `type`/`elem_type`/
`value_type`) через инспектор роняла процесс access violation'ом
(Windows: "Process finished with exit code -1073741819 / 0xC0000005").

Причина была в реентерабельности сигналов Qt. Цепочка (все вызовы —
СИНХРОННЫЕ, в одном кадре стека):

    QComboBox.currentTextChanged   (сигнал ещё выполняется)
      -> ParamInspector._commit_ports()
        -> ports_changed.emit(node_id)
          -> GraphEditor._on_ports_changed
            -> GraphScene.refresh_node
              -> again.setSelected(True)      # восстановить выделение
                -> QGraphicsScene.selectionChanged
                  -> GraphScene._on_selection
                    -> selection_node.emit(...)
                      -> GraphEditor._on_node_selected
                        -> ParamInspector.show_node(node_id)
                          -> self._clear()    # QFormLayout.removeRow(0)…

`_clear()` уничтожает ВСЕ виджеты формы — включая тот самый QComboBox, чей
сигнал ещё выполняется несколькими кадрами выше по стеку. Уничтожение QObject
из его же обработчика сигнала — undefined behavior в Qt: возврат из сигнала
обращается к уже освобождённому C++ объекту.

Фикс: ParamInspector._commit_ports откладывает ports_changed.emit на
следующий тик цикла событий (QTimer.singleShot(0, ...)) — тем же приёмом,
что уже используется в frame.py/scene.py для аналогичных случаев.

Тест воспроизводит цепочку целиком (не мокает сигналы) на реальном
GraphEditor + ParamInspector + GraphScene, меняя combo box программно и
прокачивая цикл событий — если бы фикса не было, часть этого теста работала
бы на уже уничтоженном виджете (PyQt подняла бы RuntimeError о C++-объекте,
удалённом raньше времени, вместо тихого падения интерпретатора).
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QPointF
    from PyQt6.QtWidgets import QApplication, QComboBox, QFormLayout
    HAS_QT = True
except Exception:
    HAS_QT = False

from core.graph import PortType


def _pt(x, y):
    return QPointF(x, y)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class PortTypeChangeReentrancyTests(unittest.TestCase):
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

    @staticmethod
    def _find_combo(inspector, label_text: str):
        """Найти QComboBox поля формы по подписи строки (как в addRow(key, w))."""
        form = inspector._form
        for i in range(form.rowCount()):
            lbl_item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            fld_item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if lbl_item is None or fld_item is None:
                continue
            lbl = lbl_item.widget()
            fld = fld_item.widget()
            if (isinstance(lbl, type(lbl)) and hasattr(lbl, "text")
                    and lbl.text() == label_text and isinstance(fld, QComboBox)):
                return fld
        return None

    def _select(self, ed, item) -> None:
        """Полный путь выделения — как реальный клик мышью по узлу: триггерит
        GraphScene._on_selection -> GraphEditor._on_node_selected ->
        inspector.show_node (та же цепочка, что и после ports_changed)."""
        ed.scene.clearSelection()
        item.setSelected(True)
        self.app.processEvents()

    def test_changing_map_item_type_does_not_destroy_live_widget(self):
        ed = self._editor()
        item = ed.scene.add_node("map_item", _pt(50, 50))
        self._select(ed, item)
        self.assertEqual(ed.inspector.node_id, item.node_id)

        combo = self._find_combo(ed.inspector, "type")
        self.assertIsNotNone(combo, "поле type не найдено в форме инспектора")
        self.assertEqual(combo.currentText(), "string")   # дефолт map_item

        # Смена значения — то самое действие, что раньше падало. map_item
        # допускает только number/string/block (см. _ITEM_TYPES в loop.py).
        combo.setCurrentText("number")
        # currentTextChanged уже отработал синхронно (_commit записал params),
        # но перестроение портов отложено на QTimer.singleShot(0, ...) — прогоняем
        # цикл событий, чтобы оно сработало.
        self.app.processEvents()
        self.app.processEvents()   # singleShot может встать в очередь не сразу

        self.assertEqual(ed.doc.nodes[item.node_id].params["type"], "number")
        new_item = ed.scene.node_items[item.node_id]
        self.assertEqual(new_item.out_ports[0].port.type, PortType.NUMBER)
        # Инспектор пережил перестроение и продолжает работать с тем же узлом.
        self.assertEqual(ed.inspector.node_id, item.node_id)
        combo_after = self._find_combo(ed.inspector, "type")
        self.assertIsNotNone(combo_after)
        self.assertEqual(combo_after.currentText(), "number")

    def test_changing_shift_get_type_survives_reentrant_reselect(self):
        ed = self._editor()
        item = ed.scene.add_node("shift_get", _pt(80, 80))
        self._select(ed, item)

        combo = self._find_combo(ed.inspector, "type")
        self.assertIsNotNone(combo)
        combo.setCurrentText("matrix")
        self.app.processEvents()
        self.app.processEvents()

        self.assertEqual(ed.doc.nodes[item.node_id].params["type"], "matrix")
        new_item = ed.scene.node_items[item.node_id]
        self.assertEqual(new_item.out_ports[0].port.type, PortType.MATRIX)

    def test_commit_ports_defers_emit_past_current_call_frame(self):
        """_commit_ports не эмитит ports_changed синхронно — иначе перестроение
        сцены (и, следовательно, инспектора) случилось бы прямо внутри
        обработчика сигнала виджета, воспроизводя падение."""
        ed = self._editor()
        item = ed.scene.add_node("map_item", _pt(0, 0))
        self._select(ed, item)

        received = []
        ed.inspector.ports_changed.connect(lambda nid: received.append(nid))

        ed.inspector.node_id = item.node_id
        ed.inspector._commit_ports()
        self.assertEqual(received, [], "ports_changed не должен эмититься синхронно")
        self.app.processEvents()
        self.assertEqual(received, [item.node_id])


if __name__ == "__main__":
    unittest.main()
