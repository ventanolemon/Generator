"""
Клиент домашек (десктоп): выдача заданий группам (teacher) и просмотр
студентом.

Протокол — generator_service (GenerationWeb) через web_layer тем же base_url,
что синк/контур/админка/аналитика:
  POST   /assignments                {partition_id, group_id, due_at?}
  GET    /assignments/teaching       выдачи преподавателя
  GET    /assignments/mine           домашки студента
  DELETE /assignments/{id}
  GET    /groups/mine                группы преподавателя (для формы выдачи)

Права server-authoritative (teacher выдаёт свои задачи своим группам; снять —
автор/admin). Чистый Python без Qt.
"""

from .client import AssignmentsClient, AssignmentsError

__all__ = ["AssignmentsClient", "AssignmentsError"]
