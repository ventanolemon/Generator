"""
Session — единая идентичность текущего пользователя приложения (пункт 1
«унификация идентичности» плана docs/ui_rework_plan.md).

Раньше идентичность жила ad-hoc словарём `current_user` в main.py. Теперь —
один явный источник правды, из которого читают все потребители: провайдеры
AppContext (user_id/role), клиент синка (X-User-Id/X-User-Role), клиент
контура, атрибуция попыток, ключ WordStats.

Канонический идентификатор — **строка-логин**. Это сознательное решение:
именно логином оперирует весь уже связанный путь системы —
  * серверная request-идентичность: generator_service/contour_service
    держат `current_user_id: ContextVar[str]`, web_layer шлёт X-User-Id
    строкой, статистика ключуется по login;
  * десктоп: find_user→login, ключ WordStats, owner_user_id (TEXT).
Числовой `users.id` и `owner_user_id INTEGER` из новой RBAC-схемы сервера —
выбросы: их следует свести к логину (ничего их пока не читает). См.
docs/ui_rework_plan.md, раздел «Владение и роли».

Гость — login=None, роль 'student'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GUEST_ROLE = "student"
# Роль по умолчанию для входа без явной роли (аккаунты десктопа — авторы).
DEFAULT_USER_ROLE = "teacher"


@dataclass
class Session:
    """Мутабельная идентичность сессии: переживает перелогин без пересоздания."""

    login: Optional[str] = None
    role: str = GUEST_ROLE
    #: Токен серверной сессии, если вход на сервере состоялся. None —
    #: работаем офлайн или сервер нас не знает: приложение при этом
    #: полностью функционально локально, а сервер сам решает, пускать ли
    #: такого к общему каталогу.
    token: Optional[str] = None

    @property
    def user_id(self) -> Optional[str]:
        """Канонический id пользователя (= login). None у гостя."""
        return self.login

    @property
    def is_guest(self) -> bool:
        return self.login is None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def set_user(self, login: str, role: Optional[str],
                 token: Optional[str] = None) -> None:
        self.login = login
        self.role = (role or DEFAULT_USER_ROLE)
        self.token = token

    def set_guest(self) -> None:
        self.login = None
        self.role = GUEST_ROLE
        self.token = None
