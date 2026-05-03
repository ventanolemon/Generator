"""
Дополнительные блоки контента: динамические и интерактивные.

Эти блоки расширяют систему стандарта без её изменения. Каждый из них —
это обычный Block с тремя методами рендера. Используются модулями,
которым нужны специфические виды контента (например, английский тренажёр
с пропусками в предложении).
"""

from __future__ import annotations
from typing import Callable, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit
)

from core.content import Block


class FillInTheBlankBlock(Block):
    """
    Динамический блок: предложение с пропусками, в которые пользователь
    вписывает слова. Каждый пропуск превращается в отдельное QLineEdit.

    Параметры:
      template — строка с маркерами '___' (три подчёркивания) на местах пропусков
      answers  — список правильных ответов в порядке появления маркеров
      on_change(values, correctness) — опциональный коллбек, вызываемый
        при каждом изменении любого из полей: получает текущий список введённых
        значений и список булеанов (правильно/неправильно для каждого).

    В режиме plain/docx экспорта каждый пропуск замещается своим ответом
    (с подчёркиванием в plain), чтобы документ был осмысленным.
    """

    PLACEHOLDER = "___"

    def __init__(
        self,
        template: str,
        answers: List[str],
        on_change: Callable[[List[str], List[bool]], None] | None = None,
        case_sensitive: bool = False,
    ):
        self.template = template
        self.answers = list(answers)
        self.on_change = on_change
        self.case_sensitive = case_sensitive

        # Сколько маркеров в template должно быть равно len(answers)
        n_blanks = template.count(self.PLACEHOLDER)
        if n_blanks != len(answers):
            raise ValueError(
                f"FillInTheBlankBlock: маркеров {n_blanks}, ответов {len(answers)}"
            )

    # --- Qt ---

    def render_qt(self, parent: QWidget) -> QWidget:
        wrap = QWidget(parent)
        flow = _FlowLayout(wrap)

        line_edits: list[QLineEdit] = []
        # Разбиваем template по маркерам и кладём label-ы и QLineEdit-ы вперемешку
        parts = self.template.split(self.PLACEHOLDER)
        for i, segment in enumerate(parts):
            if segment:
                lbl = QLabel(segment, wrap)
                lbl.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                flow.addWidget(lbl)
            if i < len(self.answers):
                edit = QLineEdit(wrap)
                edit.setMaximumWidth(120)
                edit.setPlaceholderText("...")
                line_edits.append(edit)
                flow.addWidget(edit)

        def emit_change():
            if self.on_change is None:
                return
            values = [e.text() for e in line_edits]
            correctness = [self._check(v, a)
                           for v, a in zip(values, self.answers)]
            self.on_change(values, correctness)

        # Подсветка по мере набора
        def on_text_changed(idx: int):
            text = line_edits[idx].text()
            ok = self._check(text, self.answers[idx]) if text else None
            if ok is None:
                line_edits[idx].setStyleSheet("")
            elif ok:
                line_edits[idx].setStyleSheet(
                    "background: #d8f0d8; color: #1a4d1a;"
                )
            else:
                line_edits[idx].setStyleSheet(
                    "background: #f4d8d8; color: #5a1a1a;"
                )
            emit_change()

        for i, edit in enumerate(line_edits):
            edit.textChanged.connect(lambda _, idx=i: on_text_changed(idx))

        return wrap

    def _check(self, value: str, expected: str) -> bool:
        if self.case_sensitive:
            return value.strip() == expected.strip()
        return value.strip().lower() == expected.strip().lower()

    # --- Plain / Docx ---

    def render_plain(self) -> str:
        # В plain виде заменяем пропуски на ответы в подчёркиваниях
        text = self.template
        for ans in self.answers:
            text = text.replace(self.PLACEHOLDER, f"_{ans}_", 1)
        return text

    def render_docx(self, doc) -> None:
        # В docx — обычный параграф с курсивными ответами
        p = doc.add_paragraph()
        parts = self.template.split(self.PLACEHOLDER)
        for i, segment in enumerate(parts):
            if segment:
                p.add_run(segment)
            if i < len(self.answers):
                run = p.add_run(self.answers[i])
                run.italic = True


# ---------- Лейаут с переносом строк, для FillInTheBlankBlock ----------

from PyQt6.QtWidgets import QLayout, QSizePolicy
from PyQt6.QtCore import QRect, QSize, QPoint


class _FlowLayout(QLayout):
    """Простой flow-layout: располагает виджеты слева направо с переносом."""

    def __init__(self, parent=None, margin=0, spacing=6):
        super().__init__(parent)
        if parent is not None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            wid = item.sizeHint().width()
            hgt = item.sizeHint().height()
            if x + wid > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x += wid + spacing
            line_height = max(line_height, hgt)
        return y + line_height - rect.y()
