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

Раскладка сюда не входит
------------------------
Что где стоит — заголовки, разрывы страниц, куда уносятся ответы —
описано ОДИН раз в `core/export_api.py` и одинаково для веб-службы и
обоих настольных бэкендов. Здесь остаётся механика письма через
`Selection`, собранная в `_Writer`: три действия, которых раскладке
достаточно.

До этого раскладка была здесь своя, третья по счёту, и отличалась от
обеих остальных: у теста ответы назывались «Эталон ответов», разрывов
страниц между вариантами не было вовсе. Расхождение не проявлялось
никак, кроме как в готовом файле у пользователя Windows.
"""

from __future__ import annotations
from typing import List

from core import StaticTask, FormulaBlock, TextBlock
from core.export_api import build_with
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


class _Writer:
    """
    Писец поверх `Selection` Word. Реализует протокол `DocumentWriter`.

    Заголовки печатаются встроенными стилями Word, а не «жирным
    текстом»: по ним строится навигация документа и оглавление, а это
    ровно то, ради чего преподаватель открывает файл в Word, а не в
    просмотрщике. Уровень 0 — «Заголовок», дальше «Заголовок N».
    """

    #: Уровень раскладки → имя встроенного стиля Word.
    STYLES = {0: "Title", 1: "Heading 1", 2: "Heading 2", 3: "Heading 3"}

    def __init__(self, selection):
        self.selection = selection

    def heading(self, text: str, level: int) -> None:
        style = self.STYLES.get(level, "Heading 3")
        try:
            self.selection.Style = style
        except Exception:                       # noqa: BLE001
            # Локализованный Word может не знать английских имён стилей.
            # Заголовок без стиля — не повод потерять весь документ.
            pass
        _type(self.selection, f"{text}\r")
        try:
            self.selection.Style = "Normal"
        except Exception:                       # noqa: BLE001
            pass

    def page_break(self) -> None:
        # 7 — wdPageBreak. Числом, а не константой win32com: константы
        # приходят из сгенерированного кэша, который этот модуль в начале
        # работы как раз сносит.
        self.selection.InsertBreak(7)

    def blocks(self, blocks) -> None:
        _insert_blocks(self.selection, blocks)
        _type(self.selection, "\r")


def _document(title: str, variants, answers: str, path: str) -> None:
    """Общая обвязка Word: открыть, разложить, сохранить, закрыть."""
    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    doc = word.Documents.Add()
    try:
        build_with(_Writer(word.Selection), variants,
                   title=title, answers=answers)
        doc.SaveAs(_abs(path))
    finally:
        doc.Close()
        # Не закрываем Word целиком — пользователь, возможно, ещё
        # работает с ним.


def export_tasks(
    tasks: List[StaticTask],
    path: str,
    title: str = "Задания",
    answers: str = "file_end",
) -> None:
    """Список заданий — ОДИН вариант из многих заданий."""
    _document(title, [list(tasks)], answers, path)


def export_test(
    variants: List[StaticTask],
    path: str,
    title: str = "Тест",
    answers: str = "hidden",
) -> None:
    """Список вариантов — МНОГО вариантов по одному заданию в каждом."""
    _document(title, [[variant] for variant in variants], answers, path)


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
