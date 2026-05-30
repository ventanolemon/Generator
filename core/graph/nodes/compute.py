"""
Узлы вычисления — самая богатая категория. Тела — чистые функции движка физики.

var_dict   — коллектор именованных значений → NUMBER_DICT.
formula    — обёртка над expression.evaluate_formula (безопасный AST, без eval).
constraint — ResultConstraint.check/.normalize; при отказе → RetryGeneration.
template   — подстановка #имя# (как fisic_generater._build_task).
"""

from __future__ import annotations
import math

from exercises.fisic.constraints import ResultConstraint
from exercises.fisic.expression import (
    FormulaError, evaluate_formula, extract_variable_names, parse_formula,
)
from exercises.fisic.formatting import format_number

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class VarDictNode(Node):
    """Собрать N именованных чисел в словарь dict[str, float]."""
    type_id = "var_dict"
    category = "compute"
    display_name = "Словарь переменных"
    OUTPUTS = [Port("out", PortType.NUMBER_DICT)]
    PARAMS_SCHEMA = {"names": {"type": "list", "default": []}}

    def validate_params(self) -> None:
        names = self.params.get("names")
        if not isinstance(names, list) or not names:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'names' должен быть непустым списком имён."
            )
        if len(set(names)) != len(names):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: имена переменных не уникальны."
            )

    def input_ports(self):
        return [Port(str(n), PortType.NUMBER) for n in self.params["names"]]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": {str(n): float(inputs[str(n)]) for n in self.params["names"]}}


class FormulaNode(Node):
    """Вычислить формулу в контексте словаря переменных."""
    type_id = "formula"
    category = "compute"
    display_name = "Формула"
    INPUTS = [Port("vars", PortType.NUMBER_DICT)]
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {"expr": {"type": "string", "default": ""}}

    def validate_params(self) -> None:
        expr = self.params.get("expr")
        if not expr:
            raise GraphValidationError(f"Узел {self.node_id!r}: пустая формула.")
        try:
            parse_formula(expr)
        except FormulaError as e:
            raise GraphValidationError(f"Узел {self.node_id!r}: ошибка формулы — {e}")

    def required_names(self) -> set[str]:
        """Имена переменных, нужные формуле (для подсказок редактора)."""
        return extract_variable_names(self.params["expr"])

    def compute(self, inputs, ctx: ExecContext):
        variables = inputs.get("vars", {}) or {}
        try:
            value = evaluate_formula(self.params["expr"], variables)
        except (OverflowError, ValueError, ZeroDivisionError) as e:
            # Числовая ошибка — как `continue` в fisic_generater.generate_task.
            raise RetryGeneration(f"Формула {self.node_id!r}: {e}")
        if math.isinf(value) or math.isnan(value):
            raise RetryGeneration(f"Формула {self.node_id!r}: результат inf/nan.")
        return {"out": float(value)}


class ConstraintNode(Node):
    """Проверка результата. Пропускает значение или просит пере-генерацию."""
    type_id = "constraint"
    category = "compute"
    display_name = "Проверка результата"
    INPUTS = [Port("in", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.NUMBER)]
    PARAMS_SCHEMA = {
        "kind": {"type": "enum", "values": ["real", "natural", "integer"], "default": "real"},
        "min": {"type": "number", "optional": True},
        "max": {"type": "number", "optional": True},
        "tolerance": {"type": "number", "default": 1e-9, "optional": True},
    }

    def validate_params(self) -> None:
        try:
            self._constraint()
        except Exception as e:
            raise GraphValidationError(f"Узел {self.node_id!r}: {e}")

    def _constraint(self) -> ResultConstraint:
        return ResultConstraint.parse(self.params or None)

    def compute(self, inputs, ctx: ExecContext):
        rc = self._constraint()
        value = inputs["in"]
        if not rc.check(value):
            raise RetryGeneration(
                f"Проверка {self.node_id!r}: {value} не прошло (kind={rc.kind})."
            )
        return {"out": rc.normalize(value)}


class TemplateNode(Node):
    """Подставить значения словаря в текстовый шаблон с маркерами #имя#."""
    type_id = "template"
    category = "compute"
    display_name = "Текстовый шаблон"
    INPUTS = [Port("vars", PortType.NUMBER_DICT)]
    OUTPUTS = [Port("out", PortType.STRING)]
    PARAMS_SCHEMA = {"text": {"type": "text", "default": ""}}

    def compute(self, inputs, ctx: ExecContext):
        text = str(self.params.get("text", ""))
        variables = inputs.get("vars", {}) or {}
        for name, value in variables.items():
            text = text.replace(f"#{name}#", self._format(value))
        return {"out": text}

    @staticmethod
    def _format(value) -> str:
        # Целые значения — без научной нотации (87000, а не 8.7×10^4),
        # как делает fisic для натуральных/целых.
        try:
            v = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(v - round(v)) < 1e-9:
            return format_number(v, scientific_threshold_high=float("inf"))
        return format_number(v)
