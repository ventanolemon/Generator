"""
GraphScene — сцена редактора. Держит GraphDocument и зеркалит его в графические
элементы. Тянет провода мышью, удаляет выделенное, принимает drop из палитры.

GraphCanvasView — QGraphicsView с зумом колесом и панорамой.
"""

from __future__ import annotations
import json
from typing import Optional

from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsScene, QGraphicsView, QGraphicsPathItem, QMenu,
)

from core.graph import DocEdge, GraphDocument

from . import style
from .items import EdgeItem, NodeItem, PortItem, can_connect


class GraphScene(QGraphicsScene):
    """Сцена, отражающая GraphDocument."""

    changed_doc = pyqtSignal()          # граф изменился (узел/провод add/remove)
    selection_node = pyqtSignal(object) # выбран узел (node_id) или None

    def __init__(self, doc: Optional[GraphDocument] = None, parent=None):
        super().__init__(parent)
        self.doc = doc or GraphDocument()
        self.registry = self.doc.registry
        self._entries = {e["type_id"]: e for e in self.registry.palette()}
        self.node_items: dict[str, NodeItem] = {}
        self.edge_items: list[EdgeItem] = []

        self.setBackgroundBrush(style.SCENE_BG)
        self.setSceneRect(0, 0, 2400, 1600)

        # временный провод при протягивании
        self._drag_from: Optional[PortItem] = None
        self._temp_edge: Optional[QGraphicsPathItem] = None

        self.selectionChanged.connect(self._on_selection)
        self.rebuild()

    # ---------- Полная перерисовка из модели ----------

    def rebuild(self) -> None:
        self.blockSignals(True)
        self.clear()
        self.node_items.clear()
        self.edge_items.clear()
        for nid in self.doc.nodes:
            self._spawn_node_item(nid)
        for e in list(self.doc.edges):
            self._spawn_edge_item(e.from_node, e.from_port, e.to_node, e.to_port)
        self.blockSignals(False)

    def _spawn_node_item(self, node_id: str) -> NodeItem:
        entry = self._entries[self.doc.nodes[node_id].type]
        item = NodeItem(self.doc, node_id, entry)
        self.addItem(item)
        self.node_items[node_id] = item
        return item

    def _find_port(self, node_id: str, port_name: str, is_output: bool) -> Optional[PortItem]:
        item = self.node_items.get(node_id)
        if item is None:
            return None
        ports = item.out_ports if is_output else item.in_ports
        for p in ports:
            if p.port.name == port_name:
                return p
        return None

    def _spawn_edge_item(self, fn, fp, tn, tp) -> Optional[EdgeItem]:
        src = self._find_port(fn, fp, is_output=True)
        dst = self._find_port(tn, tp, is_output=False)
        if src is None or dst is None:
            return None
        edge = EdgeItem(src, dst)
        self.addItem(edge)
        self.edge_items.append(edge)
        src.node_item.edges.append(edge)
        dst.node_item.edges.append(edge)
        return edge

    # ---------- Добавление узла (из палитры) ----------

    def add_node(self, type_id: str, pos: QPointF) -> NodeItem:
        node = self.doc.add_node(type_id, x=pos.x(), y=pos.y())
        item = self._spawn_node_item(node.id)
        self.changed_doc.emit()
        return item

    # ---------- Удаление выделенного ----------

    def delete_selected(self) -> None:
        removed = False
        for it in list(self.selectedItems()):
            if isinstance(it, NodeItem):
                self._remove_node_item(it)
                removed = True
            elif isinstance(it, EdgeItem):
                self._remove_edge_item(it)
                removed = True
        if removed:
            self.changed_doc.emit()

    def _remove_node_item(self, item: NodeItem) -> None:
        for e in list(item.edges):
            self._remove_edge_item(e)
        self.doc.remove_node(item.node_id)
        self.node_items.pop(item.node_id, None)
        if item.scene():
            self.removeItem(item)

    # ---------- Копирование / вставка ----------

    def copy_selection(self) -> dict | None:
        """
        Снимок выделенных узлов и проводов МЕЖДУ ними (для буфера обмена).
        Провода к невыделенным узлам не копируются. None — если ничего не выбрано.
        """
        sel_ids = [it.node_id for it in self.selectedItems()
                   if isinstance(it, NodeItem)]
        if not sel_ids:
            return None
        sel = set(sel_ids)
        nodes = []
        for nid in sel_ids:
            n = self.doc.nodes[nid]
            nodes.append({"id": n.id, "type": n.type,
                          "params": json.loads(json.dumps(n.params)),
                          "x": n.x, "y": n.y})
        edges = [
            {"from_node": e.from_node, "from_port": e.from_port,
             "to_node": e.to_node, "to_port": e.to_port}
            for e in self.doc.edges
            if e.from_node in sel and e.to_node in sel
        ]
        return {"nodes": nodes, "edges": edges}

    def paste(self, clip: dict, dx: float = 30.0, dy: float = 30.0) -> list[str]:
        """
        Вставить узлы из буфера со свежими id и сдвигом. Возвращает новые id
        (их выделяем). Внутренние провода переносятся на новые id.
        """
        if not clip or not clip.get("nodes"):
            return []
        id_map: dict[str, str] = {}
        new_items: list[NodeItem] = []
        for n in clip["nodes"]:
            new_id = self.doc.unique_id(n["type"])
            id_map[n["id"]] = new_id
            self.doc.add_node(n["type"], params=dict(n.get("params") or {}),
                              x=float(n.get("x", 0)) + dx,
                              y=float(n.get("y", 0)) + dy, node_id=new_id)
            new_items.append(self._spawn_node_item(new_id))
        for e in clip.get("edges", []):
            fn = id_map.get(e["from_node"]); tn = id_map.get(e["to_node"])
            if fn and tn:
                self.doc.add_edge(fn, e["from_port"], tn, e["to_port"])
                self._spawn_edge_item(fn, e["from_port"], tn, e["to_port"])
        # Выделяем вставленное (удобно тащить дальше).
        self.clearSelection()
        for it in new_items:
            it.setSelected(True)
        if new_items:
            self.changed_doc.emit()
        return list(id_map.values())

    def select_all(self) -> None:
        """Выделить все узлы и провода на холсте."""
        for it in self.node_items.values():
            it.setSelected(True)
        for e in self.edge_items:
            e.setSelected(True)

    def _remove_edge_item(self, edge: EdgeItem) -> None:
        fn, fp, tn, tp = edge.as_doc_tuple()
        self.doc.remove_edge(DocEdge(fn, fp, tn, tp))
        for owner in (edge.src.node_item, edge.dst.node_item):
            if edge in owner.edges:
                owner.edges.remove(edge)
        if edge in self.edge_items:
            self.edge_items.remove(edge)
        if edge.scene():
            self.removeItem(edge)

    # ---------- Протягивание провода ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(event.scenePos())
            if port is not None:
                self._drag_from = port
                self._temp_edge = QGraphicsPathItem()
                self._temp_edge.setPen(QPen(style.port_color(port.port.type), 2, Qt.PenStyle.DashLine))
                self._temp_edge.setZValue(3)
                self.addItem(self._temp_edge)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._temp_edge is not None and self._drag_from is not None:
            p1 = self._drag_from.scene_center()
            p2 = event.scenePos()
            dx = max(40.0, abs(p2.x() - p1.x()) * 0.5)
            path = QPainterPath(p1)
            path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
            self._temp_edge.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._temp_edge is not None and self._drag_from is not None:
            self.removeItem(self._temp_edge)
            self._temp_edge = None
            target = self._port_at(event.scenePos())
            if can_connect(self._drag_from, target):
                self._commit_connection(self._drag_from, target)
            self._drag_from = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _commit_connection(self, a: PortItem, b: PortItem) -> None:
        src, dst = (a, b) if a.is_output else (b, a)
        # вытеснить существующий провод на этом входе (модель + сцена)
        for e in list(self.edge_items):
            if e.dst.node_id == dst.node_id and e.dst.port.name == dst.port.name:
                self._remove_edge_item(e)
        self.doc.add_edge(src.node_id, src.port.name, dst.node_id, dst.port.name)
        self._spawn_edge_item(src.node_id, src.port.name, dst.node_id, dst.port.name)
        self.changed_doc.emit()

    def _port_at(self, scene_pos: QPointF) -> Optional[PortItem]:
        for it in self.items(scene_pos):
            if isinstance(it, PortItem):
                return it
        return None

    # ---------- Параметры узла изменились извне (инспектор) ----------

    def refresh_node(self, node_id: str) -> None:
        if node_id not in self.node_items:
            return
        # Смена динамических портов могла сделать часть рёбер висячими —
        # обрезаем их в модели и полностью перерисовываем сцену из модели.
        self.doc.prune_invalid_edges()
        self.rebuild()
        # Сохраняем выделение узла, чтобы инспектор продолжал его показывать.
        again = self.node_items.get(node_id)
        if again is not None:
            again.setSelected(True)
        self.changed_doc.emit()

    def _on_selection(self) -> None:
        sel = [it for it in self.selectedItems() if isinstance(it, NodeItem)]
        self.selection_node.emit(sel[0].node_id if len(sel) == 1 else None)

    # ---------- Порядок наложения узлов (z-order) ----------

    def _normalize_z(self) -> None:
        """
        Пере-нумеровать узлы целыми z = 1..N в текущем порядке наложения
        (по zValue, затем по порядку вставки). Провода остаются на z=0 —
        узлы всегда выше них. Делает шаги вперёд/назад однозначными.
        """
        items = list(self.node_items.values())
        idx = {it: i for i, it in enumerate(items)}
        ordered = sorted(items, key=lambda it: (it.zValue(), idx[it]))
        for i, it in enumerate(ordered, start=1):
            it.setZValue(float(i))

    def node_to_front(self, item: NodeItem) -> None:
        item.setZValue(len(self.node_items) + 10.0)
        self._normalize_z()

    def node_to_back(self, item: NodeItem) -> None:
        item.setZValue(-10.0)
        self._normalize_z()

    def raise_node(self, item: NodeItem) -> None:
        """На один слой вперёд (выше)."""
        item.setZValue(item.zValue() + 1.5)
        self._normalize_z()

    def lower_node(self, item: NodeItem) -> None:
        """На один слой назад (ниже)."""
        item.setZValue(item.zValue() - 1.5)
        self._normalize_z()

    @staticmethod
    def _climb_to_node(item) -> Optional[NodeItem]:
        while item is not None and not isinstance(item, NodeItem):
            item = item.parentItem()
        return item

    def contextMenuEvent(self, event):
        node = None
        for it in self.items(event.scenePos()):
            node = self._climb_to_node(it)
            if node is not None:
                break
        if node is None:
            return super().contextMenuEvent(event)

        menu = QMenu()
        a_front = menu.addAction("На передний план")
        a_back = menu.addAction("На задний план")
        menu.addSeparator()
        a_fwd = menu.addAction("Переместить вперёд")
        a_bwd = menu.addAction("Переместить назад")
        chosen = menu.exec(event.screenPos())
        if chosen is a_front:
            self.node_to_front(node)
        elif chosen is a_back:
            self.node_to_back(node)
        elif chosen is a_fwd:
            self.raise_node(node)
        elif chosen is a_bwd:
            self.lower_node(node)
        event.accept()


class GraphCanvasView(QGraphicsView):
    """Вид с зумом и панорамой.

    Панорама: зажать пробел — курсор превращается в «руку», ЛКМ тянет холст.
    Отпустить пробел — возврат к рамочному выделению.

    Сочетания клавиш редактирования транслируются сигналами наружу (редактор их
    связывает с undo/redo/copy/paste): сам вид о документе и истории не знает.
    """

    copy_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    moved_nodes = pyqtSignal()     # узлы перетащили (по отпусканию ЛКМ)

    def __init__(self, scene: GraphScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 1.0
        self._space_pan = False        # активен ли режим панорамы по пробелу
        self._press_positions: dict = {}   # для определения реального перемещения

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        new_zoom = self._zoom * factor
        if 0.3 <= new_zoom <= 3.0:
            self._zoom = new_zoom
            self.scale(factor, factor)

    def mousePressEvent(self, event):
        # Запомнить позиции узлов до возможного перетаскивания.
        sc = self.scene()
        if (event.button() == Qt.MouseButton.LeftButton
                and not self._space_pan and isinstance(sc, GraphScene)):
            self._press_positions = {
                nid: (it.x(), it.y()) for nid, it in sc.node_items.items()
            }
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        # Если какой-то узел реально сместился — зафиксировать в истории.
        if self._press_positions:
            sc = self.scene()
            moved = False
            if isinstance(sc, GraphScene):
                for nid, (px, py) in self._press_positions.items():
                    it = sc.node_items.get(nid)
                    if it is not None and (abs(it.x() - px) > 0.5
                                           or abs(it.y() - py) > 0.5):
                        moved = True
                        break
            self._press_positions = {}
            if moved:
                self.moved_nodes.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sc = self.scene()
            if isinstance(sc, GraphScene):
                sc.delete_selected()
                event.accept()
                return
        # Сочетания клавиш редактирования (Ctrl+C/V/Z, Ctrl+Shift+Z).
        mods = event.modifiers()
        ctrl = mods & Qt.KeyboardModifier.ControlModifier
        shift = mods & Qt.KeyboardModifier.ShiftModifier
        if ctrl:
            k = event.key()
            if k == Qt.Key.Key_A:
                sc = self.scene()
                if isinstance(sc, GraphScene):
                    sc.select_all()
                event.accept(); return
            if k == Qt.Key.Key_C:
                self.copy_requested.emit(); event.accept(); return
            if k == Qt.Key.Key_V:
                self.paste_requested.emit(); event.accept(); return
            if k == Qt.Key.Key_Z and not shift:
                self.undo_requested.emit(); event.accept(); return
            if (k == Qt.Key.Key_Z and shift) or k == Qt.Key.Key_Y:
                self.redo_requested.emit(); event.accept(); return
        # Пробел — включить «руку» для панорамы (игнорируем автоповтор).
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if not self._space_pan:
                self._space_pan = True
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        # Отпустили пробел — вернуть рамочное выделение и обычный курсор.
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            if self._space_pan:
                self._space_pan = False
                self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
                self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)
