"""
docx_export — пакет экспорта заданий в Word с двумя бэкендами.

  * docx_backend  — кросс-платформенный, через python-docx. Формулы
                    вставляются как картинки (matplotlib mathtext → PNG).
  * win32_backend — только Windows, через win32com.client.
                    Формулы вставляются как НАТИВНЫЕ объекты OMath,
                    которые в Word можно редактировать.

При вызове export_tasks_to_docx / export_test_to_docx из ui.exporter
автоматически выбирается лучший доступный бэкенд: win32 на Windows
(если установлен pywin32), иначе — кросс-платформенный.

Чтобы пользователь мог явно выбрать формат, есть параметр `mode`:
  'auto'       — выбор по платформе (по умолчанию)
  'image'      — всегда картинки (docx_backend)
  'native'     — нативные формулы (win32_backend); ValueError, если недоступно
"""

from __future__ import annotations
import sys
from typing import List, Literal

from core import StaticTask
from core.export_api import ANSWER_PLACEMENTS, normalise_placement

ExportMode = Literal["auto", "image", "native"]

#: Размещения ответов — те же, что на вебе, и из того же места.
#: Перечислять их здесь заново значило бы завести второй список, который
#: однажды разойдётся с первым.
PLACEMENTS = ANSWER_PLACEMENTS


def _placement(answers: str | None, with_answers: bool | None,
               default: str = "file_end") -> str:
    """
    Свести две настройки к одной.

    Правило то же, что на сервере (`normalise_placement`), с одной
    поправкой: там прежним поведением было «под заданием», здесь — «в
    конце файла», потому что настольный бэкенд всегда раскладывал так.
    Совместимость означает не «как у соседа», а «как было ЗДЕСЬ».
    """
    if answers:
        return normalise_placement(answers, None)
    if with_answers is False:
        return "hidden"
    if with_answers is True:
        return default
    return default


def _can_use_native() -> bool:
    """Доступен ли win32-бэкенд?"""
    if sys.platform != "win32":
        return False
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def export_tasks_to_docx(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    with_answers: bool | None = None,
    mode: ExportMode = "auto",
    answers: str | None = None,
) -> None:
    """
    Экспорт списка задач в Word. Использует доступный бэкенд.

    `answers` — размещение ответов: under / variant_end / file_end /
    hidden. `with_answers` оставлен ради вызывающих, написанных до
    появления размещений: `True` означает прежнее поведение этого
    бэкенда — ответы в конце файла.
    """
    backend = _pick_backend(mode)
    backend.export_tasks(tasks, path, title=title,
                         answers=_placement(answers, with_answers))


def export_test_to_docx(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    with_answers: bool | None = None,
    mode: ExportMode = "auto",
    answers: str | None = None,
) -> None:
    """Экспорт нескольких вариантов теста в Word."""
    backend = _pick_backend(mode)
    backend.export_test(variants, path, title=title,
                        answers=_placement(answers, with_answers,
                                           default="hidden"))


def _pick_backend(mode: ExportMode):
    """Выбрать бэкенд по запрошенному режиму и платформе."""
    if mode == "image":
        from . import docx_backend
        return docx_backend
    if mode == "native":
        if not _can_use_native():
            raise ValueError(
                "Нативный экспорт через Word недоступен. "
                "Требуется Windows с установленным pywin32."
            )
        from . import win32_backend
        return win32_backend
    # auto
    if _can_use_native():
        from . import win32_backend
        return win32_backend
    from . import docx_backend
    return docx_backend


__all__ = [
    "export_tasks_to_docx",
    "export_test_to_docx",
    "ExportMode",
    "PLACEMENTS",
]
