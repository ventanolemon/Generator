"""
Task — единица результата генерации.

Существует в двух формах:
  * StaticTask      — готовое задание формата 'условие → ответ'
  * InteractiveTask — сессия с собственным циклом 'спроси → проверь → продолжи'

Любой генератор возвращает один из этих типов.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional

from .content import Block


class Task(ABC):
    """Маркерный базовый класс для типизации."""
    meta: dict


@dataclass
class StaticTask(Task):
    """
    Задание формата 'условие → ответ'.

    statement — список блоков условия
    answer    — список блоков ответа
    meta      — служебные данные (partition_id, исходные параметры и т.п.)
    """
    statement: List[Block]
    answer: List[Block]
    meta: dict = field(default_factory=dict)


@dataclass
class TurnResult:
    """Результат одного хода в интерактивной сессии."""
    correct: bool
    feedback: List[Block]
    next_prompt: Optional[List[Block]]   # None — если сессия завершилась


class InteractiveTask(Task, ABC):
    """
    Задание-сессия. Сам по себе обладает состоянием.
    """

    meta: dict = {}

    @abstractmethod
    def initial_prompt(self) -> List[Block]:
        """Что показать пользователю в самом начале."""

    @abstractmethod
    def submit(self, user_input: str) -> TurnResult:
        """Принять ответ пользователя и вернуть результат хода."""

    @abstractmethod
    def is_finished(self) -> bool:
        """Закончилась ли сессия."""
