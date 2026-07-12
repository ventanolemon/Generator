"""
Настройки десктопа поверх QSettings (контракт K3 плана docs/ui_rework_plan.md).

Единственное место, где приложение хранит пользовательские технические
настройки среды: адрес backend (`web_layer` — общий для sync и контура),
тема оформления, вспомогательные account-поля. QSettings выбран сознательно:
кроссплатформенный, встроен в Qt, не требует своей схемы или файла-конфига.

Backend инжектируем — тесты передают QSettings поверх временного ini-файла,
чтобы не трогать пользовательский реестр/plist.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

_ORG = "Generator"
_APP = "Desktop"

DEFAULT_THEME = "dark"


class Settings:
    """Тонкая типизированная обёртка над QSettings."""

    def __init__(self, backend: QSettings | None = None):
        self._s = backend or QSettings(_ORG, _APP)

    # ---------- Соединение (web_layer) ----------

    def get_base_url(self) -> str:
        return str(self._s.value("net/base_url", "", type=str))

    def set_base_url(self, url: str) -> None:
        self._s.setValue("net/base_url", url.strip())

    # ---------- Оформление ----------

    def get_theme(self) -> str:
        return str(self._s.value("ui/theme", DEFAULT_THEME, type=str))

    def set_theme(self, name: str) -> None:
        self._s.setValue("ui/theme", name)

    # ---------- Аккаунт ----------

    def get_last_login(self) -> str:
        return str(self._s.value("account/last_login", "", type=str))

    def set_last_login(self, login: str) -> None:
        self._s.setValue("account/last_login", login)
