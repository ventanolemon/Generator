"""
Qt-интеграция проброса типа (см. tests/test_graph_type_propagation.py для
headless-правил самого механизма). Здесь — что реальный GraphEditor+
ParamInspector+GraphScene стек ДЕЙСТВИТЕЛЬНО перерисовывает порты ДРУГИХ,
не редактируемых напрямую узлов: пользователь меняет elem_type на одном
блоке (комбобокс инспектора) или протягивает провод — и подключённые узлы
подхватывают тип сами, без отдельного захода в каждый по цепочке.

Драйвит тот же реальный стек, что и test_graph_inspector_portchange.py
(комбобокс + processEvents, без моков).

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_graph_type_propagation_qt
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
class TypePropagationQtTests(unittest.TestCase):
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
        form = inspector._form
        for i in range(form.rowCount()):
            lbl_item = form.itemAt(i, QFormLayout.ItemRole.LabelRole)
            fld_item = form.itemAt(i, QFormLayout.ItemRole.FieldRole)
            if lbl_item is None or fld_item is None:
                continue
            lbl = lbl_item.widget()
            fld = fld_item.widget()
            if (hasattr(lbl, "text") and lbl.text() == label_text
                    and isinstance(fld, QComboBox)):
                return fld
        return None

    def _select(self, ed, item) -> None:
        ed.scene.clearSelection()
        item.setSelected(True)
        self.app.processEvents()

    @staticmethod
    def _port(item, name: str, is_output: bool):
        pool = item.out_ports if is_output else item.in_ports
        for p in pool:
            if p.port.name == name:
                return p
        raise AssertionError(f"порт {name!r} не найден на узле {item.node_id!r}")

    def test_wiring_cascades_across_list_boundary_on_real_scene(self):
        """list_new(elem_type=expr) --out→list--> list_get: сцена сразу
        рисует list_get.out как EXPR, без отдельного клика по инспектору."""
        ed = self._editor()
        ln = ed.scene.add_node("list_new", _pt(0, 0))
        ed.doc.set_params(ln.node_id, {**ed.doc.nodes[ln.node_id].params,
                                       "count": 0, "elem_type": "expr"})
        ed.scene.refresh_node(ln.node_id)      # как после реального commit_ports
        ln = ed.scene.node_items[ln.node_id]   # rebuild() создал новый NodeItem

        lg = ed.scene.add_node("list_get", _pt(300, 0))
        self.assertEqual(ed.doc.nodes[lg.node_id].params.get("elem_type", "number"),
                         "number")

        src = self._port(ln, "out", is_output=True)
        dst = self._port(lg, "list", is_output=False)
        ed.scene._commit_connection(src, dst)

        self.assertEqual(ed.doc.nodes[lg.node_id].params["elem_type"], "expr")
        # Сцена перерисована целиком (_commit_connection делает rebuild) —
        # НА ЭКРАНЕ у list_get реально другой NodeItem с портом EXPR.
        lg_new = ed.scene.node_items[lg.node_id]
        self.assertIsNot(lg_new, lg, "узел перерисован (новый NodeItem)")
        out_port = self._port(lg_new, "out", is_output=True)
        self.assertEqual(out_port.port.type, PortType.EXPR)

    def test_editing_source_elem_type_via_inspector_cascades_downstream(self):
        """Пользователь меняет elem_type комбобоксом на list_new — list_get,
        уже подключённый к нему, перекрашивается сам (сценарий из вопроса:
        не нужно лезть в каждый блок по цепочке)."""
        ed = self._editor()
        ln = ed.scene.add_node("list_new", _pt(0, 0))
        ed.doc.set_params(ln.node_id, {**ed.doc.nodes[ln.node_id].params,
                                       "count": 0, "elem_type": "expr"})
        ed.scene.refresh_node(ln.node_id)
        ln = ed.scene.node_items[ln.node_id]

        lg = ed.scene.add_node("list_get", _pt(300, 0))
        ed.scene._commit_connection(
            self._port(ln, "out", is_output=True),
            self._port(lg, "list", is_output=False),
        )
        # _commit_connection делает полный rebuild() — старые NodeItem-ссылки
        # (в т.ч. ln) уже удалённые C++-объекты, перечитываем из сцены.
        ln = ed.scene.node_items[ln.node_id]
        lg = ed.scene.node_items[lg.node_id]
        self.assertEqual(ed.doc.nodes[lg.node_id].params["elem_type"], "expr")

        # Теперь меняем elem_type НА list_new через настоящий комбобокс
        # инспектора (тот самый путь, что реентерабельно падал до фикса
        # test_graph_inspector_portchange.py) — и ожидаем каскад на list_get.
        self._select(ed, ln)
        combo = self._find_combo(ed.inspector, "elem_type")
        self.assertIsNotNone(combo, "поле elem_type не найдено в форме")
        combo.setCurrentText("string")
        self.app.processEvents()
        self.app.processEvents()   # singleShot может встать в очередь не сразу

        self.assertEqual(ed.doc.nodes[ln.node_id].params["elem_type"], "string")
        self.assertEqual(ed.doc.nodes[lg.node_id].params["elem_type"], "string",
                         "list_get подхватил новый тип без отдельной правки")
        lg_new = ed.scene.node_items[lg.node_id]
        out_port = self._port(lg_new, "out", is_output=True)
        self.assertEqual(out_port.port.type, PortType.STRING)

    def test_cascade_inside_loop_body_frame(self):
        """Тот же каскад внутри развёрнутого тела цикла (frame.py:
        add_inner_edge/refresh_inner) — не только на корневом холсте."""
        ed = self._editor()
        rep = ed.scene.add_node("repeat", _pt(0, 0))
        ed.scene.set_frame_expanded(rep.node_id, True)
        frame = ed.scene.node_items[rep.node_id]

        iv = frame.body_doc.add_node("input_var", {"name": "k", "type": "number"},
                                     x=20, y=20)
        ss = frame.body_doc.add_node("shift_set", {"name": "acc", "type": "number"},
                                     x=250, y=20)
        frame.refresh_inner(ed.scene)
        iv_item = frame.inner_nodes[iv.id]
        ss_item = frame.inner_nodes[ss.id]

        src = self._port(iv_item, "out", is_output=True)
        dst = self._port(ss_item, "value", is_output=False)
        frame.add_inner_edge(ed.scene, src, dst)

        self.assertEqual(frame.body_doc.nodes[ss.id].params["type"], "number")

        # Меняем тип входной переменной внутри тела — shift_set внутри той же
        # рамки следует за ним.
        frame.body_doc.set_params(
            iv.id, {**frame.body_doc.nodes[iv.id].params, "type": "block"})
        frame.refresh_inner(ed.scene, iv.id)

        self.assertEqual(frame.body_doc.nodes[ss.id].params["type"], "block")
        ss_new = frame.inner_nodes[ss.id]
        val_port = self._port(ss_new, "value", is_output=False)
        self.assertEqual(val_port.port.type, PortType.BLOCK)


if __name__ == "__main__":
    unittest.main()
