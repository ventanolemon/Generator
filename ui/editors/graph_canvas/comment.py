"""
Рамка-комментарий на холсте (аннотация, вне исполнения).

CommentItem — полупрозрачный прямоугольник с текстовой шапкой для группировки
узлов и пояснений. Это НЕ узел графа: движок его не видит, провода к нему не
тянутся. Данные живут в GraphDocument.meta["comments"] (см. document.py) и
переживают round-trip сериализации; элемент лишь зеркалит одну запись оттуда.

Комментарий можно двигать (тянуть за шапку/тело), менять размер (уголок справа
внизу), редактировать текст (двойной клик) и удалять (Del, как и узлы). Лежит
на фоне (z ниже проводов и узлов), поэтому не перехватывает клики по узлам.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSizeF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsItem, QGraphicsObject, QInputDialog

from core.graph import GraphDocument

from . import style


class CommentItem(QGraphicsObject):
    """Аннотация-прямоугольник, привязанная к записи meta["comments"]."""

    # Маркеры вида (как is_frame/is_inner у NodeItem) — сцена различает элементы.
    is_comment = True
    is_inner = False
    is_frame = False

    HEADER_H = 22.0
    GRIP = 16.0
    MIN_W = 120.0
    MIN_H = 70.0

    def __init__(self, doc: GraphDocument, comment_id: str):
        super().__init__()
        self.doc = doc
        self.comment_id = comment_id
        data = self._data()
        self._size = QSizeF(float(data.get("w", 260.0)),
                            float(data.get("h", 160.0)))
        self._resizing = False
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setZValue(-1.0)               # фон: под проводами и узлами
        self.setAcceptHoverEvents(True)
        self.setPos(float(data.get("x", 0.0)), float(data.get("y", 0.0)))

    # ---------- Доступ к записи модели ----------

    def _data(self) -> dict:
        for c in self.doc.comments():
            if c.get("id") == self.comment_id:
                return c
        return {"x": 0, "y": 0, "w": 260, "h": 160, "text": ""}

    def text(self) -> str:
        return str(self._data().get("text", ""))

    def _notify_changed(self) -> None:
        """Сообщить сцене, что документ изменился (история/JSON редактора)."""
        sc = self.scene()
        if sc is not None and hasattr(sc, "changed_doc"):
            sc.changed_doc.emit()

    # ---------- Геометрия ----------

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._size.width(), self._size.height())

    def header_rect(self) -> QRectF:
        return QRectF(0, 0, self._size.width(), self.HEADER_H)

    def grip_rect(self) -> QRectF:
        w, h = self._size.width(), self._size.height()
        return QRectF(w - self.GRIP, h - self.GRIP, self.GRIP, self.GRIP)

    # ---------- Перемещение: пишем позицию обратно в модель ----------

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            self.doc.update_comment(self.comment_id, x=self.x(), y=self.y())
        return super().itemChange(change, value)

    # ---------- Изменение размера уголком ----------

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.grip_rect().contains(event.pos())):
            self._resizing = True
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            w = max(self.MIN_W, event.pos().x())
            h = max(self.MIN_H, event.pos().y())
            self.prepareGeometryChange()
            self._size = QSizeF(w, h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self.doc.update_comment(self.comment_id,
                                    w=self._size.width(), h=self._size.height())
            self._notify_changed()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---------- Редактирование текста ----------

    def mouseDoubleClickEvent(self, event):
        self.edit_text()
        event.accept()

    def edit_text(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            None, "Комментарий", "Текст комментария:", self.text())
        if ok:
            self.doc.update_comment(self.comment_id, text=text)
            self.update()
            self._notify_changed()

    def hoverMoveEvent(self, event):
        # Курсор-диагональ над уголком изменения размера.
        if self.grip_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.unsetCursor()
        super().hoverMoveEvent(event)

    # ---------- Отрисовка ----------

    def paint(self, painter, option, widget=None) -> None:
        rect = self.boundingRect()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body = QPainterPath()
        body.addRoundedRect(rect, 8, 8)
        painter.fillPath(body, QBrush(style.COMMENT_BG))
        border = (style.NODE_BORDER_SEL if self.isSelected()
                  else style.COMMENT_BORDER)
        painter.setPen(QPen(border, 1.6, Qt.PenStyle.DashLine))
        painter.drawPath(body)

        # шапка с текстом
        header = self.header_rect()
        hp = QPainterPath()
        hp.addRoundedRect(header, 8, 8)
        painter.fillPath(hp, QBrush(style.COMMENT_HEADER_BG))

        painter.setPen(QPen(style.COMMENT_TEXT))
        f = painter.font()
        f.setPointSize(9)
        f.setBold(True)
        painter.setFont(f)
        text = self.text() or "Комментарий"
        # первая строка — в шапке, целиком — в теле (с переносом).
        first = text.splitlines()[0] if text else ""
        painter.drawText(header.adjusted(8, 0, -8, 0),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         first)

        f.setBold(False)
        f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(QPen(style.COMMENT_TEXT))
        painter.drawText(
            rect.adjusted(8, self.HEADER_H + 4, -8, -6),
            int(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
                | Qt.TextFlag.TextWordWrap),
            text,
        )

        # уголок изменения размера
        g = self.grip_rect()
        painter.setPen(QPen(style.COMMENT_BORDER, 1.4))
        painter.drawLine(QPointF(g.right() - 3, g.bottom() - 11),
                         QPointF(g.right() - 3, g.bottom() - 3))
        painter.drawLine(QPointF(g.right() - 11, g.bottom() - 3),
                         QPointF(g.right() - 3, g.bottom() - 3))
