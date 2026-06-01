"""
Узлы символьной арифметики (категория symbolic).

Выражения переносятся между узлами через PortType.EXPR как объекты sympy —
без сериализации в LaTeX и обратно, поэтому преобразования точны и без потерь.
Рендер в задание — узлом expr_block (EXPR → BLOCK через FormulaBlock).

PR-1 (ядро + алгебра): источники (symbol, expr_const), алгебраические операции
(expand/factor/simplify/collect/apart/together/cancel/trigsimp), подстановка
и численная оценка, сборка выражений в формулу. Мат. анализ, ряды и ТФКП —
следующими PR (узлы строятся по тому же образцу).

sympy импортируется лениво (см. core.graph.symbolic): движок графа headless и
не должен падать на загрузке, если пакет отсутствует.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType
from ..symbolic import (
    as_expr, build_symbols, guard_numeric, parse_expr, sympy, to_latex,
)


# ---------- Источники ----------

_ASSUMPTIONS = ["complex", "real", "positive"]


class SymbolNode(Node):
    """Символьная переменная (x, y, z, …). Источник EXPR."""
    type_id = "symbol"
    category = "symbolic"
    display_name = "Символ"
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "name": {"type": "string", "default": "x"},
        "assumptions": {"type": "enum", "values": _ASSUMPTIONS, "default": "complex"},
    }

    def validate_params(self) -> None:
        name = str(self.params.get("name", "")).strip()
        if not name:
            raise GraphValidationError(f"Узел {self.node_id!r}: пустое имя символа.")

    def compute(self, inputs, ctx: ExecContext):
        name = str(self.params.get("name", "x")).strip()
        syms = build_symbols([name], self.params.get("assumptions", "complex"))
        return {"out": syms[name]}


class ExprConstNode(Node):
    """
    Символьное выражение из текста (например, '(x+1)^2/(x-1)'). Источник EXPR.

    Имена переменных и их предположения берутся из параметров: vars — список
    имён, assumptions — общий режим (complex/real/positive).
    """
    type_id = "expr_const"
    category = "symbolic"
    display_name = "Выражение"
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "expr": {"type": "string", "default": "x"},
        "vars": {"type": "list", "default": [], "optional": True},
        "assumptions": {"type": "enum", "values": _ASSUMPTIONS, "default": "complex"},
    }

    def validate_params(self) -> None:
        # Разбираем на этапе валидации, чтобы поймать опечатки в редакторе.
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        parse_expr(self.params.get("expr", ""), syms)

    def compute(self, inputs, ctx: ExecContext):
        names = self.params.get("vars") or []
        syms = build_symbols([str(n) for n in names],
                             self.params.get("assumptions", "complex"))
        return {"out": parse_expr(self.params.get("expr", ""), syms)}


# ---------- Алгебраические преобразования (EXPR → EXPR) ----------

class _UnaryExprNode(Node):
    """База для операций над одним выражением. SYMPY_OP задаёт sympy-функцию."""
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    SYMPY_OP = "expand"   # имя метода/функции sympy

    def _apply(self, sp, expr):
        return getattr(sp, self.SYMPY_OP)(expr)

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        try:
            result = self._apply(sp, expr)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class ExpandNode(_UnaryExprNode):
    type_id = "expand"; display_name = "Раскрыть скобки"; SYMPY_OP = "expand"


class FactorNode(_UnaryExprNode):
    type_id = "factor"; display_name = "Разложить на множители"; SYMPY_OP = "factor"


class SimplifyNode(_UnaryExprNode):
    type_id = "simplify"; display_name = "Упростить"; SYMPY_OP = "simplify"


class TogetherNode(_UnaryExprNode):
    type_id = "together"; display_name = "Привести к общему знаменателю"
    SYMPY_OP = "together"


class CancelNode(_UnaryExprNode):
    type_id = "cancel"; display_name = "Сократить дробь"; SYMPY_OP = "cancel"


class TrigsimpNode(_UnaryExprNode):
    type_id = "trigsimp"; display_name = "Упростить тригонометрию"
    SYMPY_OP = "trigsimp"


class _ExprWithVarNode(Node):
    """База для операций «выражение + переменная» (collect, apart)."""
    category = "symbolic"
    INPUTS = [Port("in", PortType.EXPR), Port("var", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    SYMPY_OP = "collect"

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        var = as_expr(inputs["var"])
        try:
            result = getattr(sp, self.SYMPY_OP)(expr, var)
        except Exception as e:
            raise RetryGeneration(f"{self.type_id} {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class CollectNode(_ExprWithVarNode):
    type_id = "collect"; display_name = "Сгруппировать по степеням"
    SYMPY_OP = "collect"


class ApartNode(_ExprWithVarNode):
    type_id = "apart"; display_name = "Разложить на простейшие"; SYMPY_OP = "apart"


# ---------- Арифметика выражений ----------

_BINARY_OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b,
    "pow": lambda a, b: a ** b,
}


class ExprBinaryNode(Node):
    """Бинарная операция над двумя выражениями (+, −, ×, ÷, ^)."""
    type_id = "expr_binop"
    category = "symbolic"
    display_name = "Операция (выражения)"
    INPUTS = [Port("a", PortType.EXPR), Port("b", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.EXPR)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": list(_BINARY_OPS), "default": "add"},
    }

    def validate_params(self) -> None:
        op = self.params.get("op", "add")
        if op not in _BINARY_OPS:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестная операция {op!r}. "
                f"Допустимы: {list(_BINARY_OPS)}"
            )

    def compute(self, inputs, ctx: ExecContext):
        a = as_expr(inputs["a"])
        b = as_expr(inputs["b"])
        try:
            result = _BINARY_OPS[self.params.get("op", "add")](a, b)
        except Exception as e:
            raise RetryGeneration(f"expr_binop {self.node_id!r}: {e}")
        return {"out": guard_numeric(result)}


class SubstituteNode(Node):
    """
    Подстановка значений в выражение: subs из NUMBER_DICT (имя→число).

    Выход — EXPR (символьный результат). Для финального числа используйте
    evaluate (EXPR → NUMBER).
    """
    type_id = "expr_subs"
    category = "symbolic"
    display_name = "Подстановка"
    INPUTS = [Port("in", PortType.EXPR), Port("values", PortType.NUMBER_DICT)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        values = inputs.get("values", {}) or {}
        mapping = {sp.Symbol(str(k)): v for k, v in values.items()}
        try:
            result = expr.subs(mapping)
        except Exception as e:
            raise RetryGeneration(f"expr_subs {self.node_id!r}: {e}")
        return {"out": result}


class EvaluateNode(Node):
    """
    Численная оценка выражения → NUMBER. Бросает RetryGeneration, если результат
    не вещественное число (остались символы, или вышло комплексное/inf/nan).
    """
    type_id = "expr_eval"
    category = "symbolic"
    display_name = "Вычислить (число)"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        expr = as_expr(inputs["in"])
        try:
            val = sp.N(expr)
            if not val.is_number or val.is_real is False:
                raise ValueError(f"не вещественное число: {val}")
            f = float(val)
        except (TypeError, ValueError, AttributeError) as e:
            raise RetryGeneration(f"expr_eval {self.node_id!r}: {e}")
        import math
        if math.isinf(f) or math.isnan(f):
            raise RetryGeneration(f"expr_eval {self.node_id!r}: inf/nan.")
        return {"out": f}


# ---------- Рендер ----------

class ExprBlockNode(Node):
    """
    Формульный блок из символьного выражения (EXPR → BLOCK).

    Опционально оборачивает выражение в равенство 'prefix = expr' (например,
    'f(x) = ...'), если задан параметр prefix.
    """
    type_id = "expr_block"
    category = "symbolic"
    display_name = "Формульный блок"
    INPUTS = [Port("in", PortType.EXPR)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {"prefix": {"type": "string", "default": "", "optional": True}}

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        expr = as_expr(inputs["in"])
        latex = to_latex(expr)
        prefix = str(self.params.get("prefix", "")).strip()
        if prefix:
            latex = f"{prefix} = {latex}"
        return {"out": FormulaBlock(latex)}
