"""
SettingsWindow — диалог технических настроек среды (B1 плана
docs/ui_rework_plan.md).

Единственное место, где пользователь настраивает окружение приложения:
  * Соединение — адрес backend (`web_layer`), общий для синхронизации и
    LLM-контура; кнопка проверки доступности.
  * Оформление — тема (тёмная/светлая), применяется вживую.
  * Аккаунт    — текущий вход; смена пароля появится здесь в волне D.

Читает и пишет через core.settings.Settings; при сохранении обновляет
адрес у клиента синхронизации (AppContext.sync_client), чтобы новый адрес
подхватился без перезапуска.
"""

from __future__ import annotations

import urllib.request

from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from ui.app_context import AppContext
from ui.theme import apply_theme

# Метки тем для комбобокса ↔ внутренние имена палитр.
_THEMES = [("Тёмная", "dark"), ("Светлая", "light")]


class SettingsWindow(QDialog):
    """Модальный диалог настроек с вкладками Соединение/Оформление/Аккаунт."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.ctx = context
        self.settings = context.settings
        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.resize(480, 340)
        self._build()

    # ---------- сборка ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._connection_tab(), "Соединение")
        tabs.addTab(self._appearance_tab(), "Оформление")
        tabs.addTab(self._account_tab(), "Аккаунт")
        root.addWidget(tabs, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _connection_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        hint = QLabel(
            "Адрес сервера (web_layer) — общий для синхронизации и ИИ-контура.", w)
        hint.setProperty("class", "muted")
        hint.setWordWrap(True)
        form.addRow(hint)

        self.base_url_edit = QLineEdit(self.settings.get_base_url(), w)
        self.base_url_edit.setPlaceholderText("https://example.org")
        form.addRow("Адрес backend:", self.base_url_edit)

        row = QHBoxLayout()
        test_btn = QPushButton("Проверить соединение", w)
        test_btn.clicked.connect(self._on_test_connection)
        self.conn_status = QLabel("", w)
        self.conn_status.setProperty("class", "muted")
        row.addWidget(test_btn)
        row.addWidget(self.conn_status, stretch=1)
        form.addRow(row)
        return w

    def _appearance_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        self.theme_combo = QComboBox(w)
        current = self.settings.get_theme()
        for label, name in _THEMES:
            self.theme_combo.addItem(label, name)
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        # Тему применяем вживую при выборе — пользователь сразу видит результат.
        self.theme_combo.currentIndexChanged.connect(self._on_theme_preview)
        form.addRow("Тема оформления:", self.theme_combo)
        note = QLabel("Тема применяется сразу; «Сохранить» запомнит выбор.", w)
        note.setProperty("class", "muted")
        note.setWordWrap(True)
        form.addRow(note)
        return w

    def _account_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        uid = self.ctx.user_id_provider() or "гость"
        form.addRow("Текущий вход:", QLabel(str(uid), w))
        form.addRow("Роль:", QLabel(self.ctx.user_role_provider(), w))
        soon = QLabel("Смена пароля появится здесь в следующем обновлении.", w)
        soon.setProperty("class", "muted")
        soon.setWordWrap(True)
        form.addRow(soon)
        return w

    # ---------- действия ----------

    def _on_theme_preview(self) -> None:
        name = self.theme_combo.currentData()
        app = QApplication.instance()
        if app is not None and name:
            apply_theme(app, name)

    def _on_test_connection(self) -> None:
        url = self.base_url_edit.text().strip()
        if not url:
            self.conn_status.setText("Адрес не задан.")
            return
        self.conn_status.setText("Проверка…")
        QApplication.processEvents()
        try:
            # Лёгкая проверка доступности хоста: короткий таймаут, любой
            # HTTP-ответ считаем «сервер отвечает» (эндпоинт здоровья не
            # оговорён протоколом — важно, что хост достижим).
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.conn_status.setText(f"Отвечает (HTTP {resp.status}).")
        except urllib.error.HTTPError as e:
            # HTTP-ошибка = сервер всё же ответил.
            self.conn_status.setText(f"Отвечает (HTTP {e.code}).")
        except Exception as e:
            self.conn_status.setText(f"Недоступен: {e}")

    def _on_save(self) -> None:
        url = self.base_url_edit.text().strip()
        self.settings.set_base_url(url)
        # Клиенты (синк и контур) подхватывают новый адрес без перезапуска.
        for client in (self.ctx.sync_client, self.ctx.contour_client):
            if client is not None and hasattr(client, "set_base_url"):
                client.set_base_url(url)
        name = self.theme_combo.currentData()
        if name:
            self.settings.set_theme(name)
        self.accept()

    def reject(self) -> None:
        # Отмена: вернуть тему к сохранённой (превью могло её изменить).
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.settings.get_theme())
        super().reject()
