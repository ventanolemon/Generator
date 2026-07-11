"""
RegisterWindow — экран регистрации нового аккаунта (E2 плана
docs/ui_rework_plan.md).

Композиция волны E: та же брендовая hero-панель, что и на входе (единый
«вестибюль» приложения), справа — форма с маленькими надписями полей,
плашкой ошибки и парой действий: тихий «Ко входу» и primary-CTA.

Поверх repo.create_user (D1: пароль сразу хэшируется PBKDF2). Валидация на
стороне UI: непустые логин/пароль, совпадение повтора, длина пароля. По
успеху зовёт on_success(login) — вызывающий (main.py) обычно авто-логинит
и открывает главное окно.
"""

from __future__ import annotations
from typing import Callable, Optional

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import Repository
from ui.windows.auth_window import build_hero_panel, _field_label

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
        self.setWindowTitle("Регистрация — Генератор заданий")
        self.resize(760, 560)
        self.setMinimumSize(660, 520)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- слева: бренд (единый с окном входа) ----
        root.addWidget(build_hero_panel(
            self, "Аккаунт хранит ваши предметы,\nразделы и статистику."))

        # ---- справа: форма ----
        right = QWidget(self)
        col = QVBoxLayout(right)
        col.setContentsMargins(48, 36, 48, 24)
        col.setSpacing(6)

        col.addStretch(1)

        title = QLabel("Создание аккаунта", right)
        title.setProperty("class", "title")
        col.addWidget(title)

        subtitle = QLabel("Пара полей — и можно работать.", right)
        subtitle.setProperty("class", "subtitle")
        col.addWidget(subtitle)
        col.addSpacing(14)

        col.addWidget(_field_label("Логин", right))
        self.login_edit = QLineEdit(right)
        self.login_edit.setPlaceholderText("придумайте логин")
        col.addWidget(self.login_edit)
        col.addSpacing(6)

        # ФИО и группа — необязательные, в одну строку по колонкам.
        opt_row = QHBoxLayout()
        opt_row.setSpacing(14)
        fio_col = QVBoxLayout()
        fio_col.setSpacing(6)
        fio_col.addWidget(_field_label("ФИО · необязательно", right))
        self.fio_edit = QLineEdit(right)
        self.fio_edit.setPlaceholderText("Иванов И. И.")
        fio_col.addWidget(self.fio_edit)
        opt_row.addLayout(fio_col, 3)
        grp_col = QVBoxLayout()
        grp_col.setSpacing(6)
        grp_col.addWidget(_field_label("Группа", right))
        self.group_edit = QLineEdit(right)
        self.group_edit.setPlaceholderText("Б-21")
        grp_col.addWidget(self.group_edit)
        opt_row.addLayout(grp_col, 2)
        col.addLayout(opt_row)
        col.addSpacing(6)

        pw_row = QHBoxLayout()
        pw_row.setSpacing(14)
        pw_col = QVBoxLayout()
        pw_col.setSpacing(6)
        pw_col.addWidget(_field_label("Пароль", right))
        self.password_edit = QLineEdit(right)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(f"от {MIN_PASSWORD_LEN} символов")
        pw_col.addWidget(self.password_edit)
        pw_row.addLayout(pw_col, 1)
        rp_col = QVBoxLayout()
        rp_col.setSpacing(6)
        rp_col.addWidget(_field_label("Повтор пароля", right))
        self.repeat_edit = QLineEdit(right)
        self.repeat_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.repeat_edit.setPlaceholderText("ещё раз")
        rp_col.addWidget(self.repeat_edit)
        pw_row.addLayout(rp_col, 1)
        col.addLayout(pw_row)

        col.addSpacing(10)
        self.error_label = QLabel("", right)
        self.error_label.setProperty("class", "error-banner")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        col.addWidget(self.error_label)

        col.addStretch(2)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.back_btn = QPushButton("← Ко входу", right)
        self.back_btn.setProperty("class", "ghost")
        self.back_btn.clicked.connect(self._on_back)
        buttons.addWidget(self.back_btn)
        buttons.addStretch(1)
        self.create_btn = QPushButton("Зарегистрироваться", right)
        self.create_btn.setProperty("class", "primary")
        self.create_btn.setMinimumHeight(36)
        self.create_btn.clicked.connect(self._on_create)
        buttons.addWidget(self.create_btn)
        col.addLayout(buttons)

        root.addWidget(right, 1)

        self.repeat_edit.returnPressed.connect(self._on_create)
        self.login_edit.setFocus()

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
