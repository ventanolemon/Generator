"""
Утилиты для UI-слоя. Не содержат знаний о предметах.
"""

from __future__ import annotations
from typing import Iterable

from PyQt6.QtWidgets import QWidget, QVBoxLayout

from core import Block


def render_blocks(blocks: Iterable[Block], parent: QWidget) -> QWidget:
    """
    Сложить блоки в вертикальный контейнер. Каждый блок сам рисуется
    через render_qt — view не знает их типов.
    """
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    for block in blocks:
        widget = block.render_qt(container)
        layout.addWidget(widget)
    layout.addStretch()
    return container


def clear_layout(layout) -> None:
    """Удалить все виджеты из layout."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def blocks_to_plain(blocks: Iterable[Block]) -> str:
    """Текстовое представление списка блоков (для буфера обмена)."""
    return "\n".join(b.render_plain() for b in blocks)
