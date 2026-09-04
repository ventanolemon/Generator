"""
Кросс-платформенный экспорт через python-docx.

Формулы вставляются как картинки (через FormulaBlock.render_docx, который
рендерит latex в PNG через matplotlib и встраивает изображение). Все
остальные блоки (текст, код, таблицы, изображения) — также через
render_docx.

Раскладка сюда не входит
------------------------
Что где стоит — заголовки, разрывы страниц, куда уносятся ответы —
описано ОДИН раз в `core/export_api.py` и одинаково для веб-службы и
обоих настольных бэкендов. Здесь остаётся только механика письма
python-docx, и её берёт на себя готовый писец `PythonDocxWriter`.

До этого раскладка была здесь своя: ответы всегда в конце файла, и
никаких других размещений. Веб при этом предлагал четыре, и «в конце
варианта» — тот единственный вид, при котором ключ отрывается вместе с
концом варианта, — на десктопе получить было нельзя.
"""

from __future__ import annotations
from typing import List

from docx import Document

from core import StaticTask
from core.export_api import build_document


def export_tasks(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    answers: str = "file_end",
) -> None:
    """
    Список заданий — ОДИН вариант из многих заданий.

    Умолчание `file_end` не случайно: именно так этот бэкенд и раскладывал
    ответы до появления размещений, и менять поведение молча нельзя.
    """
    doc = Document()
    build_document(doc, [list(tasks)], title=title, answers=answers)
    doc.save(path)


def export_test(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    answers: str = "hidden",
) -> None:
    """
    Список вариантов — МНОГО вариантов по одному заданию в каждом.

    Разница с `export_tasks` не в оформлении, а в том, что считать
    вариантом; отсюда и «Вариант N» в заголовках вместо «Задание N».
    """
    doc = Document()
    build_document(doc, [[variant] for variant in variants],
                   title=title, answers=answers)
    doc.save(path)
