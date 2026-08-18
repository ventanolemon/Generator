"""
CheckableTaskView — раздел, который умеет и «смотреть», и «решать».

Зачем он есть
-------------
У части заданий есть ОБЕ формы. Физическая задача, задача матана со
спецификацией ответа, граф с проверяемым слотом — преподаватель
генерирует из них варианты и выгружает в Word, а студент решает то же
самое с автоматической проверкой.

До этого представления десктоп различал только два случая: генератор
объявил `INTERACTIVE` — открываем сессию, иначе показываем задание и
кнопку «Показать ответ». Флаг `CHECKABLE` десктоп не смотрел вовсе.
Итог: на вебе у физики есть переключатель «Смотреть / Решать», а на
десктопе ответ можно было только подсмотреть. Одно и то же задание вело
себя по-разному в зависимости от того, откуда его открыли.

Почему переключатель, а не выбор за систему
-------------------------------------------
Насильно уводить раздел на тренажёр нельзя: это отняло бы у
преподавателя генерацию вариантов и выгрузку. Оставлять только просмотр
— отнять у студента проверку. Кто открыл раздел, тот и решает, зачем;
система этого знать не может.

Умолчание — «Смотреть»: так раздел вёл себя до появления автопроверки, и
её появление не должно менять то, что человек уже привык открывать.

Устройство
----------
Это НЕ `BaseTaskView`: хром (заголовок, кнопки) приносит вложенное
представление, и вкладывать один каркас в другой значило бы показать
заголовок дважды. Здесь только полоска переключателя над обычным
представлением.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from core import TaskGenerator
from core.interactive import SolvingGenerator

from .interactive_view import InteractiveTaskView
from .static_view import StaticTaskView


class CheckableTaskView(QWidget):
    """Переключатель «Смотреть / Решать» над двумя представлениями."""

    #: Порядок вкладок в стопке — он же порядок кнопок.
    LOOK, SOLVE = 0, 1

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        self.generator = generator

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        switch = QHBoxLayout()
        self.look_btn = QPushButton("Смотреть", self)
        self.solve_btn = QPushButton("Решать", self)
        for button in (self.look_btn, self.solve_btn):
            button.setCheckable(True)
            button.setMaximumWidth(140)
            switch.addWidget(button)
        switch.addStretch()
        root.addLayout(switch)

        self.stack = QStackedWidget(self)
        self.static_view = StaticTaskView(generator, self.stack)
        self.stack.addWidget(self.static_view)
        # Решающее представление строится ЛЕНИВО: оно сразу начинает
        # сессию, то есть генерирует задание. Делать это при открытии
        # раздела, который человек, может быть, только просматривает, —
        # лишняя работа, а у графов ещё и заметная.
        self.solving_view: InteractiveTaskView | None = None
        root.addWidget(self.stack, stretch=1)

        self.look_btn.clicked.connect(lambda: self.set_mode(self.LOOK))
        self.solve_btn.clicked.connect(lambda: self.set_mode(self.SOLVE))
        self.set_mode(self.LOOK)

    # ---------- Режим ----------

    def set_mode(self, mode: int) -> None:
        """Переключить режим. Идемпотентно."""
        if mode == self.SOLVE and self.solving_view is None:
            self.solving_view = InteractiveTaskView(
                SolvingGenerator(self.generator), self.stack)
            self.stack.addWidget(self.solving_view)
        self.stack.setCurrentIndex(
            self.stack.indexOf(self.solving_view) if mode == self.SOLVE else 0)
        self.look_btn.setChecked(mode == self.LOOK)
        self.solve_btn.setChecked(mode == self.SOLVE)

    def current_mode(self) -> int:
        return (self.SOLVE
                if self.solving_view is not None
                and self.stack.currentWidget() is self.solving_view
                else self.LOOK)
