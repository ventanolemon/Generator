"""
AuthWindow — окно авторизации, «входная дверь» приложения.

Композиция волны E: слева брендовая hero-панель (знак-логотип, wordmark,
слоган на ирисовом градиенте темы), справа — колонка формы с ясной
иерархией: заголовок, поля с маленькими надписями, крупный primary-CTA,
тихий гостевой вход и ссылка на регистрацию.

Использует Repository для проверки логина/пароля.
По успеху или по гостевому входу зовёт on_success(user_info).
"""

from __future__ import annotations
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QMessageBox
)

from core import Repository


def _field_label(text: str, parent: QWidget) -> QLabel:
    """Маленькая надпись над полем (разреженный трекинг, верхний регистр)."""
    lab = QLabel(text.upper(), parent)
    lab.setProperty("class", "field-label")
    return lab


def build_hero_panel(parent: QWidget, tagline: str) -> QWidget:
    """Брендовая hero-панель (общая для входа и регистрации)."""
    panel = QWidget(parent)
    panel.setProperty("class", "hero")
    panel.setFixedWidth(280)

    lay = QVBoxLayout(panel)
    lay.setContentsMargins(28, 32, 28, 24)
    lay.setSpacing(14)

    logo = QLabel("Σ", panel)
    logo.setProperty("class", "logo-badge")
    logo.setFixedSize(52, 52)
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(logo)

    brand = QLabel("Генератор\nзаданий", panel)
    brand.setProperty("class", "hero-brand")
    lay.addWidget(brand)

    sub = QLabel(tagline, panel)
    sub.setProperty("class", "hero-sub")
    sub.setWordWrap(True)
    lay.addWidget(sub)

    lay.addStretch(1)

    foot = QLabel("Локальная работа · синхронизация · ИИ-контур", panel)
    foot.setProperty("class", "muted")
    foot.setWordWrap(True)
    lay.addWidget(foot)
    return panel


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

        self.setWindowTitle("Вход — Генератор заданий")
        self.resize(720, 440)
        self.setMinimumSize(620, 400)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- слева: бренд ----
        root.addWidget(build_hero_panel(
            self, "Генерация учебных заданий\nпо предметам и разделам."))

        # ---- справа: форма ----
        right = QWidget(self)
        col = QVBoxLayout(right)
        col.setContentsMargins(48, 40, 48, 28)
        col.setSpacing(8)

        col.addStretch(2)

        title = QLabel("С возвращением", right)
        title.setProperty("class", "title")
        col.addWidget(title)

        subtitle = QLabel("Войдите, чтобы продолжить работу.", right)
        subtitle.setProperty("class", "subtitle")
        col.addWidget(subtitle)
        col.addSpacing(18)

        col.addWidget(_field_label("Логин", right))
        self.login_edit = QLineEdit(right)
        self.login_edit.setPlaceholderText("ваш логин")
        col.addWidget(self.login_edit)
        col.addSpacing(8)

        col.addWidget(_field_label("Пароль", right))
        self.password_edit = QLineEdit(right)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("••••••••")
        col.addWidget(self.password_edit)
        col.addSpacing(18)

        login_btn = QPushButton("Войти", right)
        login_btn.setProperty("class", "primary")
        login_btn.setMinimumHeight(36)
        col.addWidget(login_btn)

        guest_btn = QPushButton("Продолжить как гость", right)
        guest_btn.setProperty("class", "ghost")
        col.addWidget(guest_btn)

        col.addStretch(3)

        # Ссылка на регистрацию — только если вызывающий дал обработчик.
        if self.on_register is not None:
            reg_row = QHBoxLayout()
            reg_row.addStretch(1)
            ask = QLabel("Нет аккаунта?", right)
            ask.setProperty("class", "muted")
            reg_row.addWidget(ask)
            self.register_btn = QPushButton("Создать аккаунт", right)
            self.register_btn.setProperty("class", "link")
            self.register_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.register_btn.clicked.connect(self._on_register)
            reg_row.addWidget(self.register_btn)
            reg_row.addStretch(1)
            col.addLayout(reg_row)

        root.addWidget(right, 1)

        login_btn.clicked.connect(self._on_login)
        guest_btn.clicked.connect(self._on_guest)
        self.password_edit.returnPressed.connect(self._on_login)
        self.login_edit.setFocus()

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
