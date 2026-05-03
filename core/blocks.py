"""
Стандартные реализации Block.

TextBlock      — обычный текст
FormulaBlock   — LaTeX-формула, рендерится через matplotlib
ImageBlock     — растровое изображение (PIL.Image, bytes или путь)
CodeBlock      — листинг кода с моноширинным шрифтом
TableBlock     — табличные данные
"""

from __future__ import annotations
import io
from pathlib import Path
from typing import Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QImage, QFont
from PyQt6.QtWidgets import (
    QWidget, QLabel, QPlainTextEdit, QTableWidget, QTableWidgetItem
)

from .content import Block
from .rendering import latex_to_pixmap, latex_to_docx_image, pil_to_qpixmap


class TextBlock(Block):
    """Обычный текстовый абзац."""

    def __init__(self, text: str):
        self.text = text

    def render_qt(self, parent: QWidget) -> QWidget:
        lbl = QLabel(self.text, parent)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lbl

    def render_plain(self) -> str:
        return self.text

    def render_docx(self, doc) -> None:
        doc.add_paragraph(self.text)


class FormulaBlock(Block):
    """LaTeX-формула."""

    def __init__(self, latex: str):
        self.latex = latex

    def render_qt(self, parent: QWidget) -> QWidget:
        pix = latex_to_pixmap(self.latex)
        lbl = QLabel(parent)
        if pix is not None:
            lbl.setPixmap(pix)
        else:
            # fallback: показать как текст с долларами
            lbl.setText(f"${self.latex}$")
            lbl.setWordWrap(True)
        return lbl

    def render_plain(self) -> str:
        return f"${self.latex}$"

    def render_docx(self, doc) -> None:
        # Вставляем формулу как картинку — гарантированно отображается
        latex_to_docx_image(doc, self.latex)


class ImageBlock(Block):
    """Изображение. Принимает PIL.Image, bytes или путь к файлу."""

    def __init__(self, image, caption: str = ""):
        self.image = image
        self.caption = caption

    def render_qt(self, parent: QWidget) -> QWidget:
        pix = pil_to_qpixmap(self.image)
        lbl = QLabel(parent)
        if pix is not None:
            lbl.setPixmap(pix)
        else:
            lbl.setText(f"[{self.caption or 'изображение недоступно'}]")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return lbl

    def render_plain(self) -> str:
        return f"[изображение: {self.caption or 'без подписи'}]"

    def render_docx(self, doc) -> None:
        from PIL import Image as PILImage
        # Приводим к BytesIO, чтобы python-docx был счастлив
        if isinstance(self.image, (str, Path)):
            doc.add_picture(str(self.image))
        elif isinstance(self.image, (bytes, bytearray)):
            doc.add_picture(io.BytesIO(self.image))
        elif isinstance(self.image, PILImage.Image):
            buf = io.BytesIO()
            self.image.save(buf, format="PNG")
            buf.seek(0)
            doc.add_picture(buf)
        else:
            doc.add_paragraph(f"[не удалось вставить изображение: {self.caption}]")


class CodeBlock(Block):
    """Листинг кода."""

    def __init__(self, code: str, language: str = "text"):
        self.code = code
        self.language = language

    def render_qt(self, parent: QWidget) -> QWidget:
        edit = QPlainTextEdit(parent)
        edit.setPlainText(self.code)
        edit.setReadOnly(True)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        edit.setFont(font)
        return edit

    def render_plain(self) -> str:
        return f"```{self.language}\n{self.code}\n```"

    def render_docx(self, doc) -> None:
        p = doc.add_paragraph()
        run = p.add_run(self.code)
        run.font.name = "Consolas"


class TableBlock(Block):
    """Таблица."""

    def __init__(
        self,
        rows: Sequence[Sequence[str]],
        header: Sequence[str] | None = None,
    ):
        self.rows = [list(r) for r in rows]
        self.header = list(header) if header else None

    def render_qt(self, parent: QWidget) -> QWidget:
        cols = len(self.header) if self.header else (len(self.rows[0]) if self.rows else 0)
        tbl = QTableWidget(len(self.rows), cols, parent)
        if self.header:
            tbl.setHorizontalHeaderLabels(self.header)
        for r, row in enumerate(self.rows):
            for c, val in enumerate(row):
                tbl.setItem(r, c, QTableWidgetItem(str(val)))
        tbl.resizeColumnsToContents()
        return tbl

    def render_plain(self) -> str:
        out = []
        if self.header:
            out.append(" | ".join(self.header))
            out.append("-" * len(out[0]))
        for row in self.rows:
            out.append(" | ".join(str(c) for c in row))
        return "\n".join(out)

    def render_docx(self, doc) -> None:
        cols = len(self.header) if self.header else (len(self.rows[0]) if self.rows else 0)
        if cols == 0:
            return
        tbl = doc.add_table(rows=(1 if self.header else 0) + len(self.rows), cols=cols)
        tbl.style = "Light Grid Accent 1"
        ofs = 0
        if self.header:
            for c, h in enumerate(self.header):
                tbl.rows[0].cells[c].text = h
            ofs = 1
        for r, row in enumerate(self.rows):
            for c, val in enumerate(row):
                tbl.rows[r + ofs].cells[c].text = str(val)
