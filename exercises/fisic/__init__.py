"""
Публичный API модуля физики.

Импорт `FisicConstructorGenerator` ленивый: сам класс тянет Qt (через
`core.TextBlock`), но чистые подмодули (`expression`, `generation`,
`constraints`, `formatting`) от Qt не зависят и используются headless —
в том числе движком визуального графа (`core.graph`). Ленивость позволяет
импортировать эти подмодули, не поднимая Qt.
"""

from __future__ import annotations
import importlib
from typing import Any

__all__ = ["FisicConstructorGenerator"]


def __getattr__(name: str) -> Any:
    if name == "FisicConstructorGenerator":
        module = importlib.import_module(".generators", __name__)
        value = module.FisicConstructorGenerator
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
