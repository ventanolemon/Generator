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
    CompareNode, NumberCheckNode, SelectNode,
)
from .loop import (
    CaseNode, InputVarNode, LoopIndexNode, MapItemNode, MapNode, RepeatNode,
    ShiftGetNode, ShiftSetNode,
)
from .sources import (
    ConstantBoolNode, ConstantNumberNode, ConstantStringNode,
    NumberRangeNode, RandomNaturalNode, RandomRealNode, StringListNode,
)
from .linalg import (
    CharPolyNode, DeterminantNode, EigenvaluesNode, EigenvectorsNode,
    IdentityNode, InverseNode, LinSolveNode, MatrixAddNode, MatrixBlockNode,
    MatrixConstNode, MatrixMultiplyNode, MatrixPowerNode, NullspaceNode,
    RandomMatrixNode, RankNode, RrefNode, ScalarMultiplyNode, TraceNode,
    TransposeNode,
)
from .symbolic import (
    AbsNode, ApartNode, ArgNode, CancelNode, CollectNode, ConjugateNode,
    DiffNode, EvaluateNode, ExpandComplexNode, ExpandNode, ExprBinaryNode,
    ExprBlockNode, ExprConstNode, FactorNode, ImNode, IntegrateNode,
    IsConvergentNode, LimitNode, ReNode, ResidueNode, SeriesNode, SimplifyNode,
    SolveNode, SubstituteNode, SumDisplayNode, SummationNode, SymbolNode,
    TogetherNode, TrigsimpNode,
)

_ALL_NODES = [
    # source
    ConstantNumberNode, ConstantStringNode, ConstantBoolNode,
    RandomNaturalNode, RandomRealNode,
    StringListNode, NumberRangeNode,
    # compute
    VarDictNode, FormulaNode, ConstraintNode, TemplateNode,
    # control
    CompareNode, NumberCheckNode, SelectNode,
    LoopIndexNode, RepeatNode, MapItemNode, MapNode, InputVarNode, CaseNode,
    ShiftGetNode, ShiftSetNode,
    # symbolic (символьная арифметика)
    SymbolNode, ExprConstNode,
    ExpandNode, FactorNode, SimplifyNode, TogetherNode, CancelNode, TrigsimpNode,
    CollectNode, ApartNode, ExprBinaryNode, SubstituteNode, EvaluateNode,
    DiffNode, IntegrateNode, LimitNode, SeriesNode,
    SummationNode, SumDisplayNode, IsConvergentNode,
    ReNode, ImNode, ArgNode, AbsNode, ConjugateNode, ExpandComplexNode,
    ResidueNode, SolveNode,
    ExprBlockNode,
    # linalg (линейная алгебра)
    MatrixConstNode, RandomMatrixNode, IdentityNode,
    DeterminantNode, InverseNode, TransposeNode, RankNode, TraceNode,
    ScalarMultiplyNode, MatrixPowerNode, MatrixMultiplyNode, MatrixAddNode,
    RrefNode, CharPolyNode, EigenvaluesNode, EigenvectorsNode, NullspaceNode,
    LinSolveNode,
    MatrixBlockNode,
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
