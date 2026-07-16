"""
Клиент администрирования (десктоп): пользователи/роли и группы.

Протокол — generator_service (GenerationWeb) через web_layer тем же base_url,
что синк и контур (system_topology §5: клиенты не ходят мимо web_layer):
  GET  /admin/users                       список пользователей
  POST /admin/users/{login}/role          смена роли
  GET  /admin/groups                      список групп (состав + преподаватели)
  POST /admin/groups                      создать группу
  POST/DELETE /admin/groups/{id}/members  состав
  POST/DELETE /admin/groups/{id}/teachers назначение преподавателей
  GET  /groups/mine                       свои группы (read-view преподавателя)

Управление доступно только admin и только при заданном адресе сервера
(правка ролей/групп в локальной БД без сервера бессмысленна и небезопасна —
права server-authoritative, см. docs/ui_rework_plan.md).

Чистый Python без Qt (транспорт — urllib или инжектируемый callable).
"""

from .client import AdminClient, AdminError

__all__ = ["AdminClient", "AdminError"]
