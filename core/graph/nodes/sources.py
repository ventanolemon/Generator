"""
Узлы-источники: производят значения, не имея входов.

random_natural / random_real переиспользуют движок физики как тело:
VariableSpec + generation.generate_value. Никакой новой логики генерации.
"""

from __future__ import annotations

from exercises.fisic.generation import generate_value, parse_variable_spec

from ..errors import GraphValidationError
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class ConstantNumberNode(Node):
    """Литерал-число."""
    type_id = "constant_number"
    category = "source"
    display_name = "Константа (число)"
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {"value": {"type": "number", "default": 0}}

    def validate_params(self) -> None:
        try:
            float(self.params.get("value", 0))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'value' должен быть числом."
            )

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(self.params.get("value", 0))}


class _RandomVarNode(Node):
    """Общая база для случайных источников. KIND задаёт тип значения."""
    KIND = "real"
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def _spec(self):
        # parse_variable_spec нормализует строки/формулы в min/max/step/forbidden.
        cfg = {**self.params, "kind": self.KIND}
        return parse_variable_spec(self.node_id, cfg)

    def validate_params(self) -> None:
        try:
            self._spec()
        except Exception as e:                       # ValueError из VariableSpec
            raise GraphValidationError(
                f"Узел {self.node_id!r}: некорректные параметры — {e}"
            )

    def compute(self, inputs, ctx: ExecContext):
        return {"out": generate_value(self._spec())}


class RandomNaturalNode(_RandomVarNode):
    """Случайное натуральное число (≥1)."""
    type_id = "random_natural"
    category = "source"
    display_name = "Случайное натуральное"
    KIND = "natural"
    PARAMS_SCHEMA = {
        "min": {"type": "number", "default": 1},
        "max": {"type": "number", "default": 10},
        "step": {"type": "number", "default": 1, "optional": True},
        "forbidden": {"type": "list", "default": [], "optional": True},
    }


class RandomRealNode(_RandomVarNode):
    """Случайное вещественное число."""
    type_id = "random_real"
    category = "source"
    display_name = "Случайное вещественное"
    KIND = "real"
    PARAMS_SCHEMA = {
        "min": {"type": "number", "default": 0},
        "max": {"type": "number", "default": 1},
        "decimals": {"type": "int", "default": 2, "optional": True},
        "step": {"type": "number", "optional": True},
        "forbidden": {"type": "list", "default": [], "optional": True},
    }
