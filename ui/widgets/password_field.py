"""
Поле пароля с переключателем видимости «показать/скрыть».

Мелкое удобство входа/регистрации/смены пароля: рядом с полем — кнопка,
которая временно раскрывает введённый пароль (echo mode Normal ↔ Password).
Возвращается виджет-строка (поле + кнопка); само поле доступно как `.edit`,
кнопка — как `.toggle` (для тестов и подписок вроде returnPressed).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QToolButton, QWidget


def make_password_field(parent: QWidget | None = None, *,
                        placeholder: str = "") -> QWidget:
    """Строка «поле пароля + переключатель видимости». Поле — `row.edit`."""
    row = QWidget(parent)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    edit = QLineEdit(row)
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    if placeholder:
        edit.setPlaceholderText(placeholder)
    lay.addWidget(edit, stretch=1)

    toggle = QToolButton(row)
    toggle.setCheckable(True)
    toggle.setAutoRaise(True)
    toggle.setCursor(Qt.CursorShape.PointingHandCursor)
    toggle.setText("Показать")
    toggle.setToolTip("Показать пароль")
    toggle.setProperty("class", "reveal")
    # Кнопку ОБЯЗАТЕЛЬНО кладём в лейаут, иначе она остаётся дочерней к row
    # в позиции (0,0) и наезжает на поле ввода (визуальный баг наложения).
    lay.addWidget(toggle)

    def _on_toggle(shown: bool) -> None:
        edit.setEchoMode(QLineEdit.EchoMode.Normal if shown
                         else QLineEdit.EchoMode.Password)
        toggle.setText("Скрыть" if shown else "Показать")
        toggle.setToolTip("Скрыть пароль" if shown else "Показать пароль")

    toggle.toggled.connect(_on_toggle)

    row.edit = edit        # type: ignore[attr-defined]
    row.toggle = toggle    # type: ignore[attr-defined]
    return row
