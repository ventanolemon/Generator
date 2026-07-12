"""
TopBar — верхняя панель действий главного окна (контракт K2 плана
docs/ui_rework_plan.md).

Единая точка расширения: каждая подсистема (статистика, настройки, sync,
контур) добавляет свою кнопку через `add_action`, а не встраивает виджеты
в лейаут главного окна руками. Ролевые действия скрываются по роли сессии
(`add_action(..., roles={"teacher", "admin"})`). Правая зона — статус-бейджи
(состояние синхронизации и т.п.), обновляемые по ключу через `set_badge`.

Стилизуется темой через QSS-классы (K1): сама панель — класс `toolbar`,
кнопки — `toolbtn`, бейджи — `badge`/`badge-warn`/`badge-error`. Пока тема
не подключена (A3), панель просто рисуется системным стилем — это не мешает
работе.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QToolButton, QWidget,
)


class TopBar(QWidget):
    """Горизонтальная панель действий с левой (кнопки) и правой (бейджи) зонами."""

    def __init__(self, role_provider: Callable[[], str], parent: QWidget | None = None):
        super().__init__(parent)
        self._role_provider = role_provider
        # Кнопки с ролевым ограничением: пересматриваем видимость при refresh_roles.
        self._role_gated: list[tuple[QToolButton, set[str]]] = []
        self._badges: dict[str, QLabel] = {}
        self.setProperty("class", "toolbar")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(6)
        # Растяжка разделяет левую зону кнопок и правую зону бейджей.
        self._layout.addStretch(1)

    # ---------- Кнопки действий ----------

    def add_action(
        self,
        text: str,
        tooltip: str,
        callback: Callable[[], None],
        *,
        roles: Optional[set[str]] = None,
    ) -> QToolButton:
        """
        Добавить кнопку слева. Если задан roles — кнопка видна только этим
        ролям (гейтинг по роли сессии). Возвращает кнопку для донастройки
        (иконка, чекабельность и т.п.).
        """
        btn = QToolButton(self)
        btn.setText(text)
        btn.setToolTip(tooltip)
        btn.setProperty("class", "toolbtn")
        btn.clicked.connect(callback)
        # Вставляем перед растяжкой (индекс растяжки — последний элемент слева).
        self._layout.insertWidget(self._layout.count() - 1 - len(self._badges), btn)
        if roles is not None:
            self._role_gated.append((btn, roles))
            btn.setVisible(self._role_provider() in roles)
        return btn

    def refresh_roles(self) -> None:
        """Пересмотреть видимость ролевых кнопок (после входа/перелогина)."""
        role = self._role_provider()
        for btn, roles in self._role_gated:
            btn.setVisible(role in roles)

    # ---------- Статус-бейджи (правая зона) ----------

    def add_badge(self, key: str, text: str = "") -> QLabel:
        """Зарегистрировать бейдж-статус в правой зоне (например, состояние sync)."""
        label = QLabel(text, self)
        label.setProperty("class", "badge")
        label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        label.setVisible(bool(text))
        self._layout.addWidget(label)
        self._badges[key] = label
        return label

    def set_badge(self, key: str, text: str, level: str = "") -> None:
        """
        Обновить бейдж по ключу. level ∈ {"", "warn", "error"} — задаёт
        QSS-класс badge/badge-warn/badge-error. Пустой text прячет бейдж.
        """
        label = self._badges.get(key)
        if label is None:
            label = self.add_badge(key, text)
        cls = "badge" if not level else f"badge-{level}"
        label.setProperty("class", cls)
        label.setText(text)
        label.setVisible(bool(text))
        # Перечитать стиль после смены property class.
        label.style().unpolish(label)
        label.style().polish(label)
