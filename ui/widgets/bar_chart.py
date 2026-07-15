"""
BarChart — лёгкая столбчатая диаграмма на QPainter (без QtCharts, которого
нет в окружении).

Один переиспользуемый виджет для двух сцен дашборда:
  * динамика по дням — столбец = попытки, тёмная часть снизу = верные;
  * распределение студентов по личной доле верных — просто высота столбца.

Цвета берутся из палитры темы (ui.theme.Palette), чтобы диаграмма
совпадала с остальным приложением в тёмной и светлой теме. Значения и
подписи задаются set_data; перекраска — по paintEvent. Данные и вычисленная
геометрия доступны для проверки в тестах (headless), сама отрисовка —
best-effort визуальная.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget


@dataclass
class Bar:
    label: str          # подпись под столбцом (может быть пустой)
    total: float        # высота столбца
    filled: Optional[float] = None   # «верная» часть снизу (None — весь столбец)


class BarChart(QWidget):
    """Столбчатая диаграмма: список Bar, нормируется по максимуму total."""

    def __init__(self, parent: QWidget | None = None, *,
                 accent="#8A8FF8", filled_color="#57C793",
                 text_muted="#A2A7B4", track="#2E3036"):
        super().__init__(parent)
        self._bars: list[Bar] = []
        self._accent = QColor(accent)
        self._filled = QColor(filled_color)
        self._muted = QColor(text_muted)
        self._track = QColor(track)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set_colors(self, *, accent: str, filled: str, text_muted: str,
                   track: str) -> None:
        self._accent = QColor(accent)
        self._filled = QColor(filled)
        self._muted = QColor(text_muted)
        self._track = QColor(track)
        self.update()

    def set_data(self, bars: list[Bar]) -> None:
        self._bars = list(bars)
        self.update()

    @property
    def bars(self) -> list[Bar]:
        return self._bars

    def _max_total(self) -> float:
        return max((b.total for b in self._bars), default=0.0)

    def paintEvent(self, _event) -> None:  # noqa: N802 — контракт Qt
        if not self._bars:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        w = self.width()
        h = self.height()
        pad = 8
        label_h = 14 if any(b.label for b in self._bars) else 0
        plot_h = max(1, h - 2 * pad - label_h)
        top = pad
        n = len(self._bars)
        slot = (w - 2 * pad) / n
        bar_w = max(1.0, min(slot * 0.68, 42.0))
        vmax = self._max_total() or 1.0

        painter.setPen(Qt.PenStyle.NoPen)
        for i, bar in enumerate(self._bars):
            cx = pad + slot * (i + 0.5)
            x = cx - bar_w / 2
            bh = plot_h * (bar.total / vmax)
            y = top + (plot_h - bh)
            # трек-фон столбца
            painter.setBrush(self._track)
            painter.drawRoundedRect(QRectF(x, top, bar_w, plot_h), 3, 3)
            # столбец (всего)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(QRectF(x, y, bar_w, bh), 3, 3)
            # «верная» часть снизу
            if bar.filled is not None and bar.total > 0:
                fh = bh * (max(0.0, min(bar.filled, bar.total)) / bar.total)
                painter.setBrush(self._filled)
                painter.drawRoundedRect(
                    QRectF(x, top + plot_h - fh, bar_w, fh), 3, 3)

        # подписи (только если помещаются: показываем каждую k-ю)
        if label_h:
            painter.setPen(self._muted)
            step = max(1, n // 8)
            for i in range(0, n, step):
                bar = self._bars[i]
                if not bar.label:
                    continue
                cx = pad + slot * (i + 0.5)
                rect = QRectF(cx - slot / 2, h - label_h, slot, label_h)
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, bar.label)
        painter.end()
