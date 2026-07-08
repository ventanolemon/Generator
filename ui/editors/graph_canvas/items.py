"""
Графические элементы канваса: порт, узел, провод.

NodeItem отражает один DocNode. Порты раскладываются по input/output. Перемещение
узла пишет позицию обратно в GraphDocument. Провода (EdgeItem) перерисовываются
при движении узлов.
"""

from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QGraphicsItem, QGraphicsObject, QGraphicsPathItem, QGraphicsEllipseItem,
)

from core.graph import GraphDocument, Port, PortType
from core.graph.port_types import is_compatible

from . import style


class PortItem(QGraphicsEllipseItem):
    """Кружок порта на краю узла. Хранит роль (in/out), имя и тип."""

    def __init__(self, node_item: "NodeItem", port: Port, is_output: bool):
        r = style.PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, node_item)
        self.node_item = node_item
        self.port = port
        self.is_output = is_output
        self.highlight = None          # None | "ok" | "convert" — подсветка при drag
        self.setBrush(QBrush(style.port_color(port.type)))
        self.setPen(QPen(QColor("#1A1A1A"), 1))
        self.setZValue(2)
        self.setAcceptHoverEvents(True)
        opt = "" if (is_output or port.required) else " (необязательный)"
        self.setToolTip(f"{port.name} : {port.type.value}{opt}")

    def set_drop_highlight(self, kind) -> None:
        """Подсветка совместимости при протягивании провода: None|'ok'|'convert'."""
        if kind == self.highlight:
            return
        self.highlight = kind
        r = style.PORT_RADIUS
        if kind == "ok":
            self.setPen(QPen(style.DROP_OK, 2.5))
            self.setRect(-r - 2, -r - 2, 2 * r + 4, 2 * r + 4)
        elif kind == "convert":
            self.setPen(QPen(style.DROP_CONVERT, 2.5, Qt.PenStyle.DashLine))
            self.setRect(-r - 2, -r - 2, 2 * r + 4, 2 * r + 4)
        else:
            self.setPen(QPen(QColor("#1A1A1A"), 1))
            self.setRect(-r, -r, 2 * r, 2 * r)

    @property
    def node_id(self) -> str:
        return self.node_item.node_id

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))


class EdgeItem(QGraphicsPathItem):
    """Провод между выходным и входным портами.

    Форма зависит от режима сцены: кубическая кривая (по умолчанию) или
    ортогональная (Г-образная) трасса из прямых углов. Режим читается со сцены
    (`orthogonal_edges`) при каждой перерисовке — переключение мгновенно
    применяется ко всем проводам."""

    def __init__(self, src: PortItem, dst: PortItem):
        super().__init__()
        self.src = src
        self.dst = dst
        self.setZValue(0)
        self.setPen(QPen(style.port_color(src.port.type), 2.4))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.update_path()

    def _is_orthogonal(self) -> bool:
        sc = self.scene()
        return bool(getattr(sc, "orthogonal_edges", False))

    @staticmethod
    def _orthogonal_path(p1: QPointF, p2: QPointF) -> QPainterPath:
        """Г-образная трасса выход→вход: короткие «усы» от портов и переход по
        средней вертикали, чтобы провод не влезал в тела узлов."""
        stub = 18.0
        ax = p1.x() + stub
        bx = p2.x() - stub
        midx = (ax + bx) / 2.0
        path = QPainterPath(p1)
        path.lineTo(ax, p1.y())
        path.lineTo(midx, p1.y())
        path.lineTo(midx, p2.y())
        path.lineTo(bx, p2.y())
        path.lineTo(p2)
        return path

    def update_path(self) -> None:
        p1 = self.src.scene_center()
        p2 = self.dst.scene_center()
        if self._is_orthogonal():
            self.setPath(self._orthogonal_path(p1, p2))
            return
        dx = max(40.0, abs(p2.x() - p1.x()) * 0.5)
        path = QPainterPath(p1)
        path.cubicTo(p1.x() + dx, p1.y(), p2.x() - dx, p2.y(), p2.x(), p2.y())
        self.setPath(path)

    def paint(self, painter, option, widget=None) -> None:
        # У выделенного провода — тонкая жёлтая обводка поверх цветной линии
        # (вместо стандартной пунктирной рамки выделения).
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.isSelected():
            painter.setPen(QPen(style.NODE_BORDER_SEL, 4.5))
            painter.drawPath(self.path())
        painter.setPen(QPen(style.port_color(self.src.port.type), 2.4))
        painter.drawPath(self.path())

    def as_doc_tuple(self) -> tuple[str, str, str, str]:
        return (self.src.node_id, self.src.port.name,
                self.dst.node_id, self.dst.port.name)


class NodeItem(QGraphicsObject):
    """Прямоугольный узел с портами и подписью параметров."""

    # Разновидности элементов холста: обычный узел / узел внутри рамки цикла /
    # сама рамка (см. frame.py). Сцена различает их по этим флагам.
    is_inner = False
    is_frame = False

    def __init__(self, doc: GraphDocument, node_id: str, palette_entry: dict):
        super().__init__()
        self.doc = doc
        self.node_id = node_id
        self.entry = palette_entry
        self.in_ports: list[PortItem] = []
        self.out_ports: list[PortItem] = []
        self.edges: list[EdgeItem] = []
        # Роль относительно финала графа: "result" | "conflict" | "forbidden"
        # | None. Выставляется сценой (см. GraphScene._update_result_marks).
        self.result_role: Optional[str] = None

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(1)
        node = doc.nodes[node_id]
        self.setPos(node.x, node.y)
        self._build_ports()

    # --- геометрия ---

    def _row_count(self) -> int:
        return max(len(self.in_ports), len(self.out_ports), 1)

    def boundingRect(self) -> QRectF:
        h = style.HEADER_H + self._row_count() * style.ROW_H + 8
        return QRectF(0, 0, style.NODE_WIDTH, h)

    def _build_ports(self) -> None:
        ins, outs = self.doc.ports(self.node_id)
        y0 = style.HEADER_H + style.ROW_H / 2
        for i, p in enumerate(ins):
            item = PortItem(self, p, is_output=False)
            item.setPos(0, y0 + i * style.ROW_H)
            self.in_ports.append(item)
        for i, p in enumerate(outs):
            item = PortItem(self, p, is_output=True)
            item.setPos(style.NODE_WIDTH, y0 + i * style.ROW_H)
            self.out_ports.append(item)

    def rebuild_ports(self) -> None:
        """Перестроить порты после изменения параметров (динамические узлы)."""
        for p in self.in_ports + self.out_ports:
            if p.scene():
                p.scene().removeItem(p)
        self.in_ports.clear()
        self.out_ports.clear()
        self.prepareGeometryChange()
        self._build_ports()
        for e in self.edges:
            e.update_path()

    def set_result_role(self, role: Optional[str]) -> None:
        """Пометить узел как финал / конфликт финалов / запрещённый TASK."""
        if role == self.result_role:
            return
        self.result_role = role
        self.setToolTip(style.ROLE_TOOLTIPS.get(role, ""))
        self.update()

    # --- отрисовка ---

    def paint(self, painter, option, widget=None) -> None:
        rect = self.boundingRect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # тело: рамка по роли (финал/конфликт/запрет), у выделенного — жёлтая
        body = QPainterPath()
        body.addRoundedRect(rect, 6, 6)
        painter.setBrush(QBrush(style.NODE_BG))
        role_border = style.ROLE_BORDERS.get(self.result_role or "")
        if self.isSelected():
            pen = QPen(style.NODE_BORDER_SEL, 2)
        elif role_border is not None:
            pen = QPen(role_border, 2)
        else:
            pen = QPen(style.NODE_BORDER, 1)
        painter.setPen(pen)
        painter.drawPath(body)

        # заголовок
        header = QRectF(rect.left(), rect.top(), rect.width(), style.HEADER_H)
        hp = QPainterPath()
        hp.addRoundedRect(header, 6, 6)
        painter.fillPath(hp, QBrush(style.category_color(self.entry["category"])))
        badge_w = self._paint_role_badge(painter, header)
        painter.setPen(QPen(style.NODE_TEXT))
        title = self.entry.get("display_name") or self.entry["type_id"]
        painter.drawText(header.adjusted(8, 0, -8 - badge_w, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         title)

        # подписи портов + краткий параметр
        painter.setPen(QPen(style.NODE_TEXT))
        f = painter.font(); f.setPointSize(8); painter.setFont(f)
        for p in self.in_ports:
            y = p.pos().y()
            painter.drawText(QRectF(10, y - 8, style.NODE_WIDTH - 20, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             p.port.name)
        for p in self.out_ports:
            y = p.pos().y()
            painter.drawText(QRectF(10, y - 8, style.NODE_WIDTH - 20, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                             p.port.name)

        # краткая сводка параметров под заголовком (если есть место)
        summary = self._param_summary()
        if summary and not self.in_ports:
            painter.setPen(QPen(QColor("#AAAAAA")))
            painter.drawText(QRectF(10, style.HEADER_H + 2, style.NODE_WIDTH - 20, 16),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             summary)

    def _paint_role_badge(self, painter, header: QRectF) -> float:
        """Бейдж роли («ВЫХОД» и т.п.) в правой части заголовка. Возвращает
        занятую ширину, чтобы заголовок не налезал на бейдж."""
        badge = style.ROLE_BADGES.get(self.result_role or "")
        if badge is None:
            return 0.0
        text, color = badge
        saved = painter.font()
        f = QFont(saved)
        f.setPointSize(7)
        f.setBold(True)
        painter.setFont(f)
        w = painter.fontMetrics().horizontalAdvance(text) + 10.0
        h = 14.0
        r = QRectF(header.right() - w - 6, header.center().y() - h / 2, w, h)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        painter.fillPath(path, QBrush(color))
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        painter.setFont(saved)
        return w + 6.0

    def _param_summary(self) -> str:
        params = self.doc.nodes[self.node_id].params
        if not params:
            return ""
        bits = []
        for k, v in params.items():
            if isinstance(v, (list, dict)):
                continue
            bits.append(f"{k}={v}")
        return ", ".join(bits)[:28]

    # --- перемещение пишем обратно в модель ---

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.doc.set_pos(self.node_id, self.x(), self.y())
            for e in self.edges:
                e.update_path()
        return super().itemChange(change, value)


def can_connect(src: PortItem, dst: PortItem) -> bool:
    """Можно ли провести провод src→dst (выход→вход, совместимые типы, не себе)."""
    if src is None or dst is None:
        return False
    if src.is_output == dst.is_output:
        return False
    out_port, in_port = (src, dst) if src.is_output else (dst, src)
    if out_port.node_id == in_port.node_id:
        return False
    return is_compatible(out_port.port.type, in_port.port.type)
