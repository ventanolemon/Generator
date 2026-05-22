"""
Кросс-платформенный экспорт через python-docx.

Формулы вставляются как картинки (через FormulaBlock.render_docx, который
рендерит latex в PNG через matplotlib и встраивает изображение). Все
остальные блоки (текст, код, таблицы, изображения) — также через render_docx.
"""

from __future__ import annotations
from typing import List

from docx import Document

from core import StaticTask


def export_tasks(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    with_answers: bool = True,
) -> None:
    doc = Document()
    doc.add_heading(title, level=0)

    for i, task in enumerate(tasks, 1):
        doc.add_heading(f"Задание {i}", level=2)
        for block in task.statement:
            block.render_docx(doc)

    if with_answers and tasks:
        doc.add_page_break()
        doc.add_heading("Ответы", level=1)
        for i, task in enumerate(tasks, 1):
            doc.add_heading(f"Ответ {i}", level=2)
            for block in task.answer:
                block.render_docx(doc)

    doc.save(path)


def export_test(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    with_answers: bool = False,
) -> None:
    doc = Document()
    doc.add_heading(title, level=0)

    for i, variant in enumerate(variants, 1):
        doc.add_heading(f"Вариант {i}", level=1)
        for block in variant.statement:
            block.render_docx(doc)
        if i < len(variants):
            doc.add_page_break()

    if with_answers:
        doc.add_page_break()
        doc.add_heading("Эталон ответов", level=1)
        for i, variant in enumerate(variants, 1):
            doc.add_heading(f"Вариант {i}", level=2)
            for block in variant.answer:
                block.render_docx(doc)

    doc.save(path)
