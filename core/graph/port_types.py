"""
Типы портов (проводов) визуального графа.

Каждый вход/выход узла типизирован. Совместимость соединений проверяется
и в редакторе (при попытке протянуть провод), и при загрузке графа из БД.
"""

from __future__ import annotations
from enum import Enum


class PortType(Enum):
    """Тип данных, переносимый проводом между узлами."""

    NUMBER = "number"            # одиночное число (int/float)
    STRING = "string"            # текст
    NUMBER_DICT = "number_dict"  # dict[str, float] — словарь именованных значений
    IMAGE = "image"              # PIL.Image в памяти
    BLOCK = "block"              # объект core.Block любого подтипа
    BLOCK_LIST = "block_list"    # list[Block]
    BOOL = "bool"                # результат проверки
    TASK = "task"                # StaticTask / InteractiveTask — финал графа


def is_compatible(src: PortType, dst: PortType) -> bool:
    """
    Можно ли соединить выход типа `src` со входом типа `dst`.

    На Фазе 0 — строгое равенство типов. Подтипизация (например, авто-сборка
    одиночного BLOCK в BLOCK_LIST) намеренно не вводится: она усложняет
    валидацию и не нужна для существующих пайплайнов.
    """
    return src == dst
