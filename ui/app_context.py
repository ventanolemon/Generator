"""
AppContext — контейнер кросс-сквозных зависимостей окон (контракт K2 плана
docs/ui_rework_plan.md).

Собирается один раз в main.py и пробрасывается в окна вместо россыпи
конструкторных аргументов, которая иначе разрасталась бы с каждой новой
подсистемой (sync, контур, …). Держит инфраструктуру и сессию:
  * repo                — доступ к БД;
  * settings            — технические настройки среды (адрес backend, тема);
  * user_id_provider    — текущий user_id (или None у гостя);
  * user_role_provider  — роль сессии (student|teacher|admin); ею гейтятся
                          ролевые действия (например, кнопка контура);
  * sync_client         — клиент офлайн-синхронизации (None, пока не настроен);
  * contour_client      — клиент LLM-контура (None, пока не настроен);
  * admin_client        — клиент администрирования (None, пока не настроен).

Оконно-специфичное (реестр генераторов, хранилище словарной статистики,
каталог слов) остаётся отдельными аргументами конкретных окон — это не
инфраструктура уровня приложения.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from core import Repository
from core.settings import Settings


@dataclass
class AppContext:
    repo: Repository
    settings: Settings
    user_id_provider: Callable[[], Optional[str]]
    user_role_provider: Callable[[], str]
    sync_client: object | None = None
    contour_client: object | None = None
    admin_client: object | None = None
    analytics_client: object | None = None
    assignments_client: object | None = None
