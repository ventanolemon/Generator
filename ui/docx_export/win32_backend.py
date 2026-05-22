"""
Экспорт через win32com — нативный путь для Windows.

Формулы (FormulaBlock) вставляются как объекты OMath в Word: пользователь
видит их как редактируемые формулы (через Equation Editor), а не как
картинки. Подход взят из исходных export.py / export_2.py пользователя:

    selection.OMaths.Add(selection.Range)
    selection.TypeText(formula)
    selection.OMaths.BuildUp()

Перед вставкой LaTeX проходит через _sanitize_latex, чтобы кастомные
команды матана (tg, ctg, arctg) превратились в стандартные LaTeX,
понятные Word.

Остальные блоки вставляются как plain text (через render_plain).
Для модулей, где это критично (изображения схем opvs), при необходимости
можно расширить отдельной обработкой ImageBlock — но в текущей реализации
матан — главный потребитель формул, и текст для остальных блоков достаточен.
"""

from __future__ import annotations
from typing import List

from core import StaticTask, FormulaBlock, TextBlock
from core.latex import for_word_omath

import shutil
import win32com

try:
    # Получить путь к gen_py
    gen_path = win32com.__gen_path__
    shutil.rmtree(gen_path)
    print(f"Кэш очищен: {gen_path}")
except Exception as e:
    print(f"Ошибка: {e}")


def export_tasks(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    with_answers: bool = True,
) -> None:
    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    doc = word.Documents.Add()
    selection = word.Selection

    try:
        _type(selection, f"{title}\n\n")
        for i, task in enumerate(tasks, 1):
            _type(selection, f"Задание {i}\n")
            _insert_blocks(selection, task.statement)
            _type(selection, "\n")

        if with_answers and tasks:
            _type(selection, "\n\nОтветы\n\n")
            for i, task in enumerate(tasks, 1):
                _type(selection, f"Ответ {i}\n")
                _insert_blocks(selection, task.answer)
                _type(selection, "\n")

        doc.SaveAs(_abs(path))
    finally:
        doc.Close()
        # Не закрываем Word целиком — пользователь, возможно, ещё работает с ним.


def export_test(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    with_answers: bool = False,
) -> None:
    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    doc = word.Documents.Add()
    selection = word.Selection

    try:
        _type(selection, f"{title}\n\n")
        for i, variant in enumerate(variants, 1):
            _type(selection, f"Вариант {i}\n")
            _insert_blocks(selection, variant.statement)
            _type(selection, "\n\n")

        if with_answers:
            _type(selection, "\nЭталон ответов\n\n")
            for i, variant in enumerate(variants, 1):
                _type(selection, f"Вариант {i}\n")
                _insert_blocks(selection, variant.answer)
                _type(selection, "\n\n")

        doc.SaveAs(_abs(path))
    finally:
        doc.Close()


# ---------- Вставка блоков ----------

def _insert_blocks(selection, blocks) -> None:
    """Вставить список блоков последовательно в текущее место документа."""
    for block in blocks:
        _insert_one(selection, block)


def _insert_one(selection, block) -> None:
    """
    Вставка одного блока.

    FormulaBlock → OMath (нативная формула Word).
    Все остальные блоки — как текст (через render_plain).
    """
    if isinstance(block, FormulaBlock):
        _insert_formula(selection, block.latex)
        _type(selection, "\n")
        return

    if isinstance(block, TextBlock):
        _type(selection, block.text)
        _type(selection, "\n")
        return

    # Fallback: для других блоков (CodeBlock, TableBlock, ImageBlock,
    # FillInTheBlankBlock, WordCorrectionBlock) — текстовое представление.
    text = block.render_plain()
    _type(selection, text)
    _type(selection, "\n")


def _insert_formula(selection, latex: str) -> None:
    """
    Вставить LaTeX-формулу как нативный объект OMath.

    Применяет _prepare_for_word_omath — точную копию clean_latex_for_word
    из оригинального проекта (fh.py/teylor.py/parametric_task.py):
      * убирает \left/\right
      * исправляет ^ { → ^{ (критично, ошибка -2147467263)
      * сохраняет tg/arctg (Word их понимает)
    """
    formula = for_word_omath(latex)
    # Python-строка содержит \\, Word в LaTeX-режиме ожидает одинарный \
    formula = formula.replace("\\\\", "\\")
    print(formula)
    selection.OMaths.Add(selection.Range)
    selection.TypeText(formula)
    # selection.OMaths(1).LinearFormat = 1   # ← вот эта строка: 1 = wdOMathLinearFormatLatex
    selection.OMaths.BuildUp()


def _type(selection, text: str) -> None:
    """selection.TypeText, но устойчив к переводам строки."""
    # В Word \r — это новый параграф, \n — новая строка внутри параграфа.
    # Для наглядности используем \r везде.
    selection.TypeText(text.replace("\n", "\r"))


def _abs(path: str) -> str:
    """Word нужен абсолютный путь."""
    import os
    return os.path.abspath(path)
