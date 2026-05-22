"""
ui.exporter — единая точка входа экспорта.

Подбирает бэкенд автоматически:
  * Windows + pywin32 → win32-бэкенд: формулы вставляются как редактируемые
    объекты OMath (Equation Editor в Word).
  * Иначе              → docx-бэкенд: формулы вставляются как PNG-картинки.

Логика выбора и сам экспорт — в пакете ui.docx_export. Этот модуль —
тонкий прокси для обратной совместимости с прежним API.

Если нужно явно выбрать бэкенд, используйте параметр `mode`:
  'auto'   — выбор по платформе (по умолчанию)
  'image'  — всегда картинки (полезно, если нужен переносимый docx)
  'native' — нативные формулы (требует Windows + Word + pywin32)
"""

from __future__ import annotations
from typing import List

from core import StaticTask
from ui.docx_export import (
    export_tasks_to_docx as _export_tasks,
    export_test_to_docx as _export_test,
    ExportMode,
)


def export_tasks_to_docx(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    with_answers: bool = True,
    mode: ExportMode = "auto",
) -> None:
    _export_tasks(tasks, path, title=title,
                  with_answers=with_answers, mode=mode)


def export_test_to_docx(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    with_answers: bool = False,
    mode: ExportMode = "auto",
) -> None:
    _export_test(variants, path, title=title,
                 with_answers=with_answers, mode=mode)
