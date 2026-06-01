"""
Символьная арифметика поверх sympy — общие помощники.

Здесь сосредоточены: ленивый импорт sympy (движок графа в остальном headless и
не должен падать на этапе загрузки, если sympy не установлен), безопасный разбор
пользовательских выражений и единая обёртка ошибок.

Узлы символьной арифметики (core/graph/nodes/symbolic.py) переносят между собой
объекты sympy через PortType.EXPR — это чистый round-trip без потерь (в отличие
от сериализации в LaTeX и обратно). Рендер в задание — через FormulaBlock(latex).
"""

from __future__ import annotations

from .errors import GraphValidationError, RetryGeneration


# Имена sympy-функций, разрешённые в пользовательском вводе выражений. Этого
# набора достаточно для алгебры, мат. анализа, рядов и ТФКП.
_ALLOWED_FUNCS = (
    "sin cos tan cot sec csc asin acos atan acot sinh cosh tanh "
    "exp log ln sqrt Abs sign factorial gamma "
    "re im arg conjugate Heaviside DiracDelta"
).split()


def sympy():
    """Ленивый импорт sympy с понятной ошибкой, если он не установлен."""
    try:
        import sympy  # noqa: F401
    except Exception as e:  # pragma: no cover - окружение без sympy
        raise GraphValidationError(
            "Для символьной арифметики нужен пакет sympy (pip install sympy). "
            f"Импорт не удался: {e}"
        )
    return sympy


def build_symbols(names, assumptions: str = "complex") -> dict:
    """
    Создать словарь sympy-символов с заданными предположениями.

    assumptions: 'complex' (по умолчанию — без ограничений), 'real', 'positive'.
    Предположения важны для ТФКП и упрощений (например, re(x)=x при real).
    """
    sp = sympy()
    kw = {}
    if assumptions == "real":
        kw = {"real": True}
    elif assumptions == "positive":
        kw = {"positive": True}
    return {n: sp.Symbol(n, **kw) for n in names}


def parse_expr(text: str, symbols: dict | None = None):
    """
    Безопасно разобрать строку в sympy-выражение.

    Используется sympify с локальным словарём символов (с предположениями) и
    запретом на eval-конструкции. Степень принимает и '^', и '**'.
    """
    sp = sympy()
    if text is None or str(text).strip() == "":
        raise GraphValidationError("Пустое символьное выражение.")
    src = str(text).replace("^", "**")
    local = dict(symbols or {})
    try:
        from sympy.parsing.sympy_parser import (
            parse_expr as _pe, standard_transformations,
            implicit_multiplication_application,
        )
        transforms = standard_transformations + (
            implicit_multiplication_application,
        )
        return _pe(src, local_dict=local, transformations=transforms,
                   evaluate=True)
    except GraphValidationError:
        raise
    except Exception as e:
        raise GraphValidationError(f"Не удалось разобрать выражение {text!r}: {e}")


def to_latex(expr) -> str:
    """LaTeX-представление sympy-выражения (через core.latex.canonical_latex)."""
    sp = sympy()
    raw = sp.latex(expr)
    try:
        from core.latex import canonical_latex
        return canonical_latex(raw)
    except Exception:
        return raw


def as_expr(value, symbols: dict | None = None):
    """
    Привести произвольное входное значение к sympy-выражению.

    EXPR-порт несёт sympy-объект как есть; число превращаем в sympy-число;
    строку разбираем parse_expr. Удобно для узлов, принимающих смешанные входы.
    """
    sp = sympy()
    if isinstance(value, sp.Basic):
        return value
    if isinstance(value, (int, float)):
        return sp.nsimplify(value) if isinstance(value, int) else sp.Float(value)
    return parse_expr(str(value), symbols)


def guard_numeric(expr):
    """
    Если выражение после операции стало нечисловым из-за деления на ноль и т.п.
    (sympy.zoo/oo/nan) — попросить пере-генерацию (как делает FormulaNode).
    """
    sp = sympy()
    if expr in (sp.zoo, sp.oo, -sp.oo, sp.nan):
        raise RetryGeneration(f"Символьный результат не определён: {expr}.")
    return expr
