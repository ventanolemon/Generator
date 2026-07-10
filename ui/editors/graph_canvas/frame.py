"""
Рамка-структура цикла на холсте (LabVIEW-style).

Развёрнутый узел repeat/map рисуется не компактным прямоугольником, а рамкой
(LoopFrameItem), внутри которой видно и редактируется ТЕЛО цикла — вложенный
GraphDocument из params["body"]: внутренние узлы можно двигать, соединять,
удалять и добавлять, не уходя на отдельный холст. Граница модели не меняется:
тело по-прежнему сериализуется в параметр узла-цикла, движок исполнения не
затронут; «развёрнутость» — состояние вида (meta["expanded_nodes"] документа).

Внутренние элементы (InnerNodeItem/EdgeItem) — обычные элементы сцены, а не
дети рамки: сохраняется привычное наложение «провода под узлами». Рамка сама
переносит внутренние элементы при своём перемещении и автоматически растёт
под содержимое. Порты цикла (count и внешние переменные слева, out и туннели
справа) лежат на границе рамки — это и есть туннели; внутренняя их сторона —
узлы input_var/output_var в теле.
"""

from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsItem

from core.graph import GraphDocument, GraphError

from . import style
from .items import EdgeItem, NodeItem, PortItem


# Геометрия рамки.
FRAME_HEADER_H = 28.0
FRAME_PAD = 18.0
FRAME_MIN_W = 300.0
FRAME_MIN_H = 170.0

# Типы узлов, умеющих разворачиваться в рамку (одно тело в params["body"]).
FRAMEABLE_TYPES = ("repeat", "map")


class InnerNodeItem(NodeItem):
    """
    Узел тела цикла на основном холсте. Координаты в body-документе —
    локальные (относительно начала содержимого рамки); элемент сам пересчитывает
    их при перемещении и не даёт утащить себя выше/левее рамки.
    """

    is_inner = True

    def __init__(self, frame: "LoopFrameItem", node_id: str, palette_entry: dict):
        self.frame = frame                      # до super: itemChange зовётся в setPos
        super().__init__(frame.body_doc, node_id, palette_entry)

    def itemChange(self, change, value):
        GC = QGraphicsItem.GraphicsItemChange
        if change == GC.ItemPositionChange and not self.frame.syncing:
            origin = self.frame.content_origin_scene()
            return QPointF(max(value.x(), origin.x()),
                           max(value.y(), origin.y()))
        if change == GC.ItemPositionHasChanged:
            for e in self.edges:
                e.update_path()
            if not self.frame.syncing:
                local = self.scenePos() - self.frame.content_origin_scene()
                self.doc.set_pos(self.node_id, local.x(), local.y())
                self.frame.on_inner_moved()
        # Минуя NodeItem.itemChange: он пишет в документ сценовые координаты.
        return super(NodeItem, self).itemChange(change, value)


class LoopFrameItem(NodeItem):
    """
    Развёрнутый узел цикла: рамка с портами на границе и телом внутри.

    Для сцены это полноценный NodeItem (node_id, in_ports/out_ports, edges,
    set_result_role), поэтому внешние провода и выделение работают как обычно.
    Дополнительно держит body_doc (живой GraphDocument тела) и элементы тела;
    каждая правка тела сразу сериализуется обратно в params (commit_body).
    """

    is_frame = True

    def __init__(self, doc: GraphDocument, node_id: str, palette_entry: dict,
                 body_key: str = "body"):
        self.body_key = body_key
        self.syncing = True            # подавляет обратную запись координат
        self._size = QSizeF(FRAME_MIN_W, FRAME_MIN_H)
        self.inner_nodes: dict[str, InnerNodeItem] = {}
        self.inner_edges: list[EdgeItem] = []

        node = doc.nodes[node_id]
        body = node.params.get(body_key) or {"nodes": [], "edges": [], "meta": {}}
        # Бросает GraphError при битом теле — сцена откатится к компактному виду.
        self.body_doc = GraphDocument.from_spec_dict(body, registry=doc.registry)
        self.body_doc.is_subgraph = True

        super().__init__(doc, node_id, palette_entry)
        self.setZValue(0.5)            # фон: ниже проводов и узлов
        self._last_pos = self.pos()
        self.syncing = False

    # ---------- Наполнение внутренними элементами ----------

    def populate(self, scene) -> None:
        """Создать элементы тела (узлы и провода). Звать после addItem(frame)."""
        self.syncing = True
        try:
            self._normalize_body_coords()
            origin = self.content_origin_scene()
            for nid, node in self.body_doc.nodes.items():
                entry = scene._entries[node.type]
                item = InnerNodeItem(self, nid, entry)
                scene.addItem(item)
                item.setZValue(3.0)
                item.setPos(origin + QPointF(node.x, node.y))
                self.inner_nodes[nid] = item
            for e in list(self.body_doc.edges):
                self._spawn_inner_edge(scene, e.from_node, e.from_port,
                                       e.to_node, e.to_port)
        finally:
            self.syncing = False
        self.update_geometry()

    def _normalize_body_coords(self) -> None:
        """Сдвинуть тело так, чтобы координаты были неотрицательны."""
        nodes = self.body_doc.nodes.values()
        if not nodes:
            return
        dx = min(0.0, min(n.x for n in nodes))
        dy = min(0.0, min(n.y for n in nodes))
        if dx < 0 or dy < 0:
            for n in nodes:
                n.x -= dx
                n.y -= dy

    def _find_inner_port(self, node_id: str, port_name: str,
                         is_output: bool) -> Optional[PortItem]:
        item = self.inner_nodes.get(node_id)
        if item is None:
            return None
        for p in (item.out_ports if is_output else item.in_ports):
            if p.port.name == port_name:
                return p
        return None

    def _spawn_inner_edge(self, scene, fn, fp, tn, tp) -> Optional[EdgeItem]:
        src = self._find_inner_port(fn, fp, is_output=True)
        dst = self._find_inner_port(tn, tp, is_output=False)
        if src is None or dst is None:
            return None
        edge = EdgeItem(src, dst)
        edge.setZValue(2.5)            # над рамкой, под внутренними узлами
        scene.addItem(edge)
        self.inner_edges.append(edge)
        src.node_item.edges.append(edge)
        dst.node_item.edges.append(edge)
        return edge

    # ---------- Правки тела (модель + сцена + сериализация в params) ----------

    def commit_body(self) -> None:
        """Сериализовать тело обратно в параметр узла-цикла."""
        node = self.doc.nodes.get(self.node_id)
        if node is not None:
            node.params[self.body_key] = self.body_doc.to_spec_dict()

    def add_inner_node(self, scene, type_id: str) -> InnerNodeItem:
        """Добавить узел в тело — на свободное место под существующими."""
        if self.inner_nodes:
            nodes = self.body_doc.nodes.values()
            x = min(n.x for n in nodes)
            y = max(n.y + 110 for n in nodes)
        else:
            x, y = 20.0, 20.0
        node = self.body_doc.add_node(type_id, x=x, y=y)
        entry = scene._entries[type_id]
        self.syncing = True
        try:
            item = InnerNodeItem(self, node.id, entry)
            scene.addItem(item)
            item.setZValue(3.0)
            item.setPos(self.content_origin_scene() + QPointF(node.x, node.y))
        finally:
            self.syncing = False
        self.inner_nodes[node.id] = item
        self.update_geometry()
        self.commit_body()
        return item

    def add_inner_edge(self, scene, src: PortItem, dst: PortItem) -> None:
        """Соединить два внутренних порта (вытесняя провод на занятом входе)."""
        for e in list(self.inner_edges):
            if e.dst.node_id == dst.node_id and e.dst.port.name == dst.port.name:
                self.remove_inner_edge(scene, e)
        self.body_doc.add_edge(src.node_id, src.port.name,
                               dst.node_id, dst.port.name)
        # add_edge уже мог протолкнуть тип дальше по телу (elem_type и т.п.,
        # см. GraphDocument.propagate_types_from_node внутри add_edge) —
        # перестраиваем тело целиком, а не одним точечным проводом, чтобы
        # каскад отразился сразу.
        self.refresh_inner(scene)

    def remove_inner_edge(self, scene, edge: EdgeItem) -> None:
        fn, fp, tn, tp = edge.as_doc_tuple()
        from core.graph import DocEdge
        self.body_doc.remove_edge(DocEdge(fn, fp, tn, tp))
        for owner in (edge.src.node_item, edge.dst.node_item):
            if edge in owner.edges:
                owner.edges.remove(edge)
        if edge in self.inner_edges:
            self.inner_edges.remove(edge)
        if edge.scene():
            scene.removeItem(edge)
        self.commit_body()

    def remove_inner_node(self, scene, item: InnerNodeItem) -> None:
        for e in list(item.edges):
            self.remove_inner_edge(scene, e)
        self.body_doc.remove_node(item.node_id)
        self.inner_nodes.pop(item.node_id, None)
        if item.scene():
            scene.removeItem(item)
        self.update_geometry()
        self.commit_body()

    def clear_inner(self, scene) -> None:
        """Убрать все внутренние элементы со сцены (при удалении/свёртке рамки)."""
        for e in list(self.inner_edges):
            for owner in (e.src.node_item, e.dst.node_item):
                if e in owner.edges:
                    owner.edges.remove(e)
            if e.scene():
                scene.removeItem(e)
        self.inner_edges.clear()
        for item in self.inner_nodes.values():
            if item.scene():
                scene.removeItem(item)
        self.inner_nodes.clear()

    def refresh_inner(self, scene, node_id: str | None = None) -> None:
        """
        Перестроить тело после смены параметров внутреннего узла.

        node_id — узел, чей TYPE_PARAM (elem_type/value_type/type) мог
        поменяться: перед обрезкой висячих проводов протолкнуть новый тип по
        подключённым (см. GraphDocument.propagate_types_from_node) — иначе
        prune_invalid_edges снесёт провод, который проброс делает валидным
        снова. None — вызывающий уже пробросил сам (например, add_inner_edge
        через body_doc.add_edge) или пробрасывать нечего.
        """
        if node_id is not None:
            self.body_doc.propagate_types_from_node(node_id)
        self.body_doc.prune_invalid_edges()
        self.clear_inner(scene)
        self.populate(scene)
        self.commit_body()

    # ---------- Геометрия ----------

    def content_origin_scene(self) -> QPointF:
        return self.scenePos() + QPointF(FRAME_PAD, FRAME_HEADER_H + FRAME_PAD)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._size.width(), self._size.height())

    def update_geometry(self) -> None:
        """Авто-размер рамки под содержимое тела (+ запас на расстановку)."""
        w, h = FRAME_MIN_W, FRAME_MIN_H
        for nid, item in self.inner_nodes.items():
            node = self.body_doc.nodes.get(nid)
            if node is None:
                continue
            r = item.boundingRect()
            w = max(w, node.x + r.width() + 2 * FRAME_PAD + 40)
            h = max(h, node.y + r.height() + FRAME_HEADER_H + 2 * FRAME_PAD + 20)
        size = QSizeF(w, h)
        if size != self._size:
            self.prepareGeometryChange()
            self._size = size
            self._layout_ports()
            for e in self.edges:
                e.update_path()
        self.update()

    def on_inner_moved(self) -> None:
        self.update_geometry()
        self.commit_body()

    # ---------- Порты на границе рамки ----------

    def _build_ports(self) -> None:
        ins, outs = self.doc.ports(self.node_id)
        for p in ins:
            self.in_ports.append(PortItem(self, p, is_output=False))
        for p in outs:
            self.out_ports.append(PortItem(self, p, is_output=True))
        self._layout_ports()

    def _layout_ports(self) -> None:
        y0 = FRAME_HEADER_H + 20
        for i, p in enumerate(self.in_ports):
            p.setPos(0, y0 + i * style.ROW_H)
        for i, p in enumerate(self.out_ports):
            p.setPos(self._size.width(), y0 + i * style.ROW_H)

    # ---------- Перемещение рамки: тело едет вместе с ней ----------

    def itemChange(self, change, value):
        result = super().itemChange(change, value)
        if (change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged
                and not self.syncing):
            delta = self.pos() - self._last_pos
            self._last_pos = self.pos()
            if delta.x() or delta.y():
                self.syncing = True
                try:
                    for item in self.inner_nodes.values():
                        # При мульти-выделении Qt сам двигает выбранные элементы.
                        if not item.isSelected():
                            item.moveBy(delta.x(), delta.y())
                finally:
                    self.syncing = False
                for e in self.inner_edges:
                    e.update_path()
        return result

    # ---------- Взаимодействие ----------

    def header_rect(self) -> QRectF:
        return QRectF(0, 0, self._size.width(), FRAME_HEADER_H)

    def collapse_glyph_rect(self) -> QRectF:
        return QRectF(self._size.width() - 24, 5, 18, 18)

    def _request_collapse(self) -> None:
        # Отложенно: rebuild сцены удалит этот элемент, прямо из обработчика
        # события Qt этого делать нельзя.
        from PyQt6.QtCore import QTimer
        sc = self.scene()
        if sc is not None and hasattr(sc, "set_frame_expanded"):
            nid = self.node_id
            QTimer.singleShot(0, lambda s=sc, n=nid: s.set_frame_expanded(n, False))

    def mousePressEvent(self, event):
        # Глиф «свернуть» в заголовке.
        if self.collapse_glyph_rect().contains(event.pos()):
            self._request_collapse()
            event.accept()
            return
        # Перенос/выделение — только за заголовок; клик по полю тела уходит
        # вниз (рамочное выделение внутренних узлов работает как на холсте).
        if self.header_rect().contains(event.pos()):
            super().mousePressEvent(event)
        else:
            event.ignore()

    def mouseDoubleClickEvent(self, event):
        if self.header_rect().contains(event.pos()):
            self._request_collapse()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ---------- Отрисовка ----------

    def paint(self, painter, option, widget=None) -> None:
        from PyQt6.QtGui import QPainter
        rect = self.boundingRect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body = QPainterPath()
        body.addRoundedRect(rect, 8, 8)
        painter.setBrush(QBrush(style.FRAME_BG))
        pen = (QPen(style.NODE_BORDER_SEL, 2) if self.isSelected()
               else QPen(style.FRAME_BORDER, 1.6))
        painter.setPen(pen)
        painter.drawPath(body)

        # заголовок
        header = self.header_rect()
        hp = QPainterPath()
        hp.addRoundedRect(header, 8, 8)
        painter.fillPath(hp, QBrush(style.category_color(self.entry["category"])))
        painter.setPen(QPen(style.NODE_TEXT))
        title = (self.entry.get("display_name") or self.entry["type_id"])
        summary = self._param_summary()
        if summary:
            title += f"   [{summary}]"
        painter.drawText(header.adjusted(10, 0, -30, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         title)
        # глиф «свернуть»
        g = self.collapse_glyph_rect()
        painter.setPen(QPen(style.NODE_TEXT, 1.4))
        painter.drawRect(g.adjusted(3, 3, -3, -3))
        painter.drawLine(QPointF(g.left() + 6, g.center().y()),
                         QPointF(g.right() - 6, g.center().y()))

        # подписи портов на границе
        f = painter.font()
        f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(QPen(style.NODE_TEXT))
        for p in self.in_ports:
            y = p.pos().y()
            painter.drawText(QRectF(12, y - 8, 150, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             p.port.name)
        for p in self.out_ports:
            y = p.pos().y()
            painter.drawText(QRectF(rect.width() - 162, y - 8, 150, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             p.port.name)

        if not self.inner_nodes:
            painter.setPen(QPen(QColor("#777777")))
            painter.drawText(rect.adjusted(0, FRAME_HEADER_H, 0, 0),
                             Qt.AlignmentFlag.AlignCenter,
                             "Тело пусто — добавьте узлы из палитры,\n"
                             "когда рамка выделена.")


def make_frame_item(doc: GraphDocument, node_id: str,
                    palette_entry: dict) -> Optional[LoopFrameItem]:
    """Создать рамку для узла, если его тело загружается; иначе None."""
    try:
        return LoopFrameItem(doc, node_id, palette_entry)
    except GraphError:
        return None
