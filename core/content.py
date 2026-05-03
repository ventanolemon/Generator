"""
Block — атомарная единица контента в задании или ответе.

Контракт: каждый блок умеет рендериться в трёх средах.
Чтобы добавить новый тип контента (например, граф), нужно создать
класс, наследующий Block, и реализовать три метода. Все существующие
View и экспортёры подхватят его автоматически.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget
    from docx.document import Document as DocxDoc


class Block(ABC):
    """Базовый класс единицы контента."""

    @abstractmethod
    def render_qt(self, parent: "QWidget") -> "QWidget":
        """Создать виджет PyQt для отображения в интерфейсе."""

    @abstractmethod
    def render_plain(self) -> str:
        """Текстовое представление: буфер обмена, отладка, простой текст."""

    @abstractmethod
    def render_docx(self, doc: "DocxDoc") -> None:
        """Дописать себя в открытый docx-документ при экспорте."""
