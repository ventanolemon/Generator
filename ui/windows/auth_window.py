"""
AuthWindow — простое окно авторизации.

Использует Repository для проверки логина/пароля.
По успеху или по гостевому входу зовёт on_success(user_info).
"""

from __future__ import annotations
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox
)

from core import Repository


class AuthWindow(QWidget):
    """Окно входа. on_success вызывается с tuple (login, fio, group, role) или
    None для гостя. on_register (опционально) открывает экран регистрации."""

    def __init__(
        self,
        repository: Repository,
        on_success: Callable[[Optional[tuple]], None],
        on_register: Optional[Callable[[], None]] = None,
    ):
        super().__init__()
        self.repo = repository
        self.on_success = on_success
        self.on_register = on_register

        self.setWindowTitle("Вход")
        self.resize(360, 260)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel("Генератор заданий", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        root.addWidget(QLabel("Логин:"))
        self.login_edit = QLineEdit(self)
        root.addWidget(self.login_edit)

        root.addWidget(QLabel("Пароль:"))
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        root.addWidget(self.password_edit)

        btns = QHBoxLayout()
        login_btn = QPushButton("Войти", self)
        login_btn.setProperty("class", "primary")
        guest_btn = QPushButton("Гостевой вход", self)
        btns.addWidget(login_btn)
        btns.addWidget(guest_btn)
        root.addLayout(btns)

        # Ссылка на регистрацию — только если вызывающий дал обработчик.
        if self.on_register is not None:
            reg_row = QHBoxLayout()
            reg_row.addWidget(QLabel("Нет аккаунта?", self))
            self.register_btn = QPushButton("Регистрация", self)
            self.register_btn.setProperty("class", "link")
            self.register_btn.clicked.connect(self._on_register)
            reg_row.addWidget(self.register_btn)
            reg_row.addStretch(1)
            root.addLayout(reg_row)

        login_btn.clicked.connect(self._on_login)
        guest_btn.clicked.connect(self._on_guest)
        self.password_edit.returnPressed.connect(self._on_login)

    def _on_login(self) -> None:
        login = self.login_edit.text().strip()
        password = self.password_edit.text()
        if not login or not password:
            QMessageBox.warning(self, "Ошибка", "Введите логин и пароль.")
            return
        try:
            user = self.repo.find_user(login, password)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", str(e))
            return
        if user is None:
            QMessageBox.warning(self, "Ошибка", "Неверный логин или пароль.")
            return
        self.on_success(user)
        self.close()

    def _on_guest(self) -> None:
        self.on_success(None)
        self.close()

    def _on_register(self) -> None:
        if self.on_register is not None:
            self.on_register()
        self.close()
