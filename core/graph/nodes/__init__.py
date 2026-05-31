"""
Реестр узлов по умолчанию. Все типы узлов Фазы 0 регистрируются здесь.

Добавить новый узел = создать класс Node и дописать его в _ALL_NODES.
Палитра редактора и исполнитель подхватят его автоматически.
"""

from __future__ import annotations

from ..registry import NodeRegistry
from .assembly import BlockListNode, StaticTaskNode
from .compute import ConstraintNode, FormulaNode, TemplateNode, VarDictNode
from .content import TextBlockNode
from .control import (
    CompareNode, ConstantBoolNode, NumberCheckNode, SelectNode,
)
from .loop import LoopIndexNode, RepeatNode
from .sources import (
    ConstantNumberNode, RandomNaturalNode, RandomRealNode,
)

_ALL_NODES = [
    # source
    ConstantNumberNode, RandomNaturalNode, RandomRealNode,
    # compute
    VarDictNode, FormulaNode, ConstraintNode, TemplateNode,
    # control
    ConstantBoolNode, CompareNode, NumberCheckNode, SelectNode,
    LoopIndexNode, RepeatNode,
    # content
    TextBlockNode,
    # assembly
    BlockListNode, StaticTaskNode,
]


def build_default_registry() -> NodeRegistry:
    reg = NodeRegistry()
    for cls in _ALL_NODES:
        reg.register(cls)
    return reg


# Готовый реестр для исполнителя и генератора.
DEFAULT_REGISTRY = build_default_registry()

__all__ = ["build_default_registry", "DEFAULT_REGISTRY"]
