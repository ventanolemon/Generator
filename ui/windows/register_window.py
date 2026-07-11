"""
RegisterWindow — экран регистрации нового аккаунта (E2 плана
docs/ui_rework_plan.md).

Поверх repo.create_user (D1: пароль сразу хэшируется PBKDF2). Валидация на
стороне UI: непустые логин/пароль, совпадение повтора, длина пароля. По
успеху зовёт on_success(login) — вызывающий (main.py) обычно авто-логинит
и открывает главное окно.

Структура и логика — Opus; визуальную композицию (hero-оформление) шлифует
Fable в творческом заходе волны E. Функциональные элементы (поля, кнопки,
контракт on_success/on_back) при редизайне сохраняются.
"""

from __future__ import annotations
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)

from core import Repository

MIN_PASSWORD_LEN = 4


class RegisterWindow(QWidget):
    """Окно регистрации. on_success(login) — по созданию аккаунта."""

    def __init__(
        self,
        repository: Repository,
        on_success: Callable[[str], None],
        on_back: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.repo = repository
        self.on_success = on_success
        self.on_back = on_back
        self.setWindowTitle("Регистрация")
        self.resize(420, 380)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        brand = QLabel("Генератор заданий", self)
        brand.setProperty("class", "brand")
        root.addWidget(brand)
        subtitle = QLabel("Создание аккаунта", self)
        subtitle.setProperty("class", "subtitle")
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(10)
        self.login_edit = QLineEdit(self)
        self.login_edit.setPlaceholderText("логин")
        form.addRow("Логин:", self.login_edit)

        self.fio_edit = QLineEdit(self)
        self.fio_edit.setPlaceholderText("ФИО (необязательно)")
        form.addRow("ФИО:", self.fio_edit)

        self.group_edit = QLineEdit(self)
        self.group_edit.setPlaceholderText("группа (необязательно)")
        form.addRow("Группа:", self.group_edit)

        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Пароль:", self.password_edit)

        self.repeat_edit = QLineEdit(self)
        self.repeat_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat_edit.setPlaceholderText("ещё раз")
        form.addRow("Повтор:", self.repeat_edit)
        root.addLayout(form)

        self.error_label = QLabel("", self)
        self.error_label.setProperty("class", "danger")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        root.addStretch(1)

        buttons = QHBoxLayout()
        self.back_btn = QPushButton("← Ко входу", self)
        self.back_btn.setProperty("class", "link")
        self.back_btn.clicked.connect(self._on_back)
        buttons.addWidget(self.back_btn)
        buttons.addStretch(1)
        self.create_btn = QPushButton("Зарегистрироваться", self)
        self.create_btn.setProperty("class", "primary")
        self.create_btn.clicked.connect(self._on_create)
        buttons.addWidget(self.create_btn)
        root.addLayout(buttons)

        self.repeat_edit.returnPressed.connect(self._on_create)

    # ---------- действия ----------

    def _fail(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _on_create(self) -> None:
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        repeat = self.repeat_edit.text()
        if not login:
            self._fail("Введите логин.")
            return
        if len(password) < MIN_PASSWORD_LEN:
            self._fail(f"Пароль не короче {MIN_PASSWORD_LEN} символов.")
            return
        if password != repeat:
            self._fail("Пароли не совпадают.")
            return
        try:
            created = self.repo.create_user(
                login, password,
                fio=self.fio_edit.text().strip(),
                group=self.group_edit.text().strip(),
                role="teacher",
            )
        except Exception as e:
            self._fail(f"Ошибка БД: {e}")
            return
        if not created:
            self._fail("Логин уже занят.")
            return
        self.on_success(login)
        self.close()

    def _on_back(self) -> None:
        if self.on_back is not None:
            self.on_back()
        self.close()
