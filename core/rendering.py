"""
Инфраструктурные функции рендеринга.

Вся логика нормализации LaTeX вынесена в core/latex.py. Здесь только
конкретные пайплайны рендера: matplotlib mathtext, PIL → Qt, и т.п.
"""

from __future__ import annotations
import io
from pathlib import Path
from typing import Optional

from PyQt6.QtGui import QPixmap, QImage

from .latex import canonical_latex


# ============================================================
# Рендер LaTeX в QPixmap (Qt-предпросмотр)
# ============================================================

def latex_to_pixmap(latex: str, fontsize: int = 14, dpi: int = 130) -> Optional[QPixmap]:
    """
    Отрендерить LaTeX-формулу в QPixmap через matplotlib.mathtext.
    Возвращает None при ошибке (формула некорректна или matplotlib недоступен).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext
        from matplotlib import font_manager
    except Exception:
        return None

    try:
        buf = io.BytesIO()
        prop = font_manager.FontProperties(size=fontsize)
        s = canonical_latex(latex)
        mathtext.math_to_image(f"${s}$", buf, prop=prop, dpi=dpi, format="png")
        buf.seek(0)
        img = QImage()
        img.loadFromData(buf.getvalue(), "PNG")
        return QPixmap.fromImage(img)
    except Exception:
        return None


def latex_to_docx_image(doc, latex: str, fontsize: int = 14, dpi: int = 200) -> None:
    """
    Вставить LaTeX-формулу в docx-документ как изображение.
    При ошибке рендера — вставляем как текст с долларами (визуально видно
    пользователю, что именно сломалось).
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import mathtext
        from matplotlib import font_manager

        buf = io.BytesIO()
        prop = font_manager.FontProperties(size=fontsize)
        s = canonical_latex(latex)
        mathtext.math_to_image(f"${s}$", buf, prop=prop, dpi=dpi, format="png")
        buf.seek(0)
        doc.add_picture(buf)
    except Exception:
        doc.add_paragraph(f"${latex}$")


# ============================================================
# Конвертация PIL.Image / bytes / путь → QPixmap
# ============================================================

def pil_to_qpixmap(image) -> Optional[QPixmap]:
    """Конвертировать PIL.Image / bytes / путь в QPixmap."""
    from PIL import Image as PILImage

    try:
        if isinstance(image, (str, Path)):
            pix = QPixmap(str(image))
            return pix if not pix.isNull() else None

        if isinstance(image, (bytes, bytearray)):
            img = QImage()
            img.loadFromData(bytes(image))
            return QPixmap.fromImage(img) if not img.isNull() else None

        if isinstance(image, PILImage.Image):
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            buf.seek(0)
            qimg = QImage()
            qimg.loadFromData(buf.getvalue(), "PNG")
            return QPixmap.fromImage(qimg) if not qimg.isNull() else None
    except Exception:
        pass
    return None
