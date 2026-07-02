"""
Узлы графики на комплексной плоскости (категория plot).

Для контрольных по ТФКП: «изобразить область/точки на комплексной плоскости».
Выход — PortType.IMAGE (PIL.Image), дальше стандартный путь to_block/image_block.

  complex_points_plot — точки (LIST комплексных значений) → IMAGE;
  complex_region_plot — область по системе неравенств (LIST строк-условий
                        от z, И-логика) → IMAGE.

matplotlib/numpy импортируются лениво (движок графа headless и не должен
падать на загрузке без них — как с sympy). Условия областей разбираются
безопасно: AST-whitelist (имена/вызовы/сравнения/арифметика), никакого
доступа к атрибутам — политика та же, что у формул физики.
"""

from __future__ import annotations

import ast

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


def _matplotlib():
    """Ленивый импорт matplotlib (Agg) с понятной ошибкой."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return plt
    except Exception as e:  # pragma: no cover — окружение без matplotlib
        raise GraphValidationError(
            f"Для узлов графики нужен пакет matplotlib (pip install matplotlib): {e}"
        )


def _fig_to_image(fig):
    """Снять фигуру matplotlib в PIL.Image (PNG в памяти)."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    buf.seek(0)
    img = Image.open(buf)
    img.load()
    return img


def _axes_cross(ax, lim):
    """Оси через начало координат + сетка (стиль «комплексная плоскость»)."""
    ax.axhline(0, color="#555555", linewidth=1)
    ax.axvline(0, color="#555555", linewidth=1)
    ax.set_xlim(-lim[0], lim[0]) if isinstance(lim, tuple) else None
    ax.grid(True, linestyle=":", linewidth=0.6, alpha=0.6)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Re z")
    ax.set_ylabel("Im z")


def _to_complex(value):
    """Элемент списка точек → python complex (sympy/чисто числовые/пары)."""
    if isinstance(value, (tuple, list)) and len(value) == 2:
        return complex(float(value[0]), float(value[1]))
    if isinstance(value, complex):
        return value
    if isinstance(value, (int, float)):
        return complex(value, 0.0)
    # sympy-значение: должно вычисляться в число.
    try:
        return complex(value.evalf())
    except Exception:
        raise RetryGeneration(f"Точка {value!r} не вычисляется в комплексное число.")


class ComplexPointsPlotNode(Node):
    """
    Точки на комплексной плоскости → картинка. Вход points:LIST — комплексные
    значения (sympy-числа, python complex, пары (x, y) или вещественные).
    unit_circle='yes' добавляет единичную окружность (полезно для корней).
    """
    type_id = "complex_points_plot"
    category = "plot"
    display_name = "Точки на ℂ-плоскости"
    description = ("Изобразить точки на комплексной плоскости. Вход: LIST "
                   "комплексных значений. Выход: IMAGE.")
    INPUTS = [Port("points", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.IMAGE)]
    PARAMS_SCHEMA = {
        "title": {"type": "string", "default": "", "optional": True},
        "unit_circle": {"type": "enum", "values": ["no", "yes"],
                        "default": "no", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        plt = _matplotlib()
        raw = inputs.get("points")
        if not isinstance(raw, (list, tuple)) or not raw:
            raise RetryGeneration(
                f"complex_points_plot {self.node_id!r}: пустой список точек."
            )
        pts = [_to_complex(v) for v in raw]

        fig, ax = plt.subplots(figsize=(4.6, 4.6))
        xs = [p.real for p in pts]
        ys = [p.imag for p in pts]
        lim = max([abs(v) for v in xs + ys] + [1.0]) * 1.25
        if str(self.params.get("unit_circle", "no")) == "yes":
            import numpy as np
            t = np.linspace(0, 2 * np.pi, 200)
            ax.plot(np.cos(t), np.sin(t), color="#999999",
                    linewidth=0.9, linestyle="--")
        ax.scatter(xs, ys, color="#C0392B", zorder=3)
        for p in pts:
            ax.annotate(f"({p.real:.3g}; {p.imag:.3g})", (p.real, p.imag),
                        textcoords="offset points", xytext=(5, 5), fontsize=7)
        _axes_cross(ax, None)
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
        title = str(self.params.get("title", "")).strip()
        if title:
            ax.set_title(title, fontsize=10)
        img = _fig_to_image(fig)
        plt.close(fig)
        return {"out": img}


# ---------- Безопасная оценка условий области ----------

# Разрешённые узлы AST в условии (имена/числа/арифметика/сравнения/логика).
_ALLOWED_AST = (
    ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.USub,
    ast.UAdd, ast.Not, ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
    ast.Pow, ast.Mod, ast.Compare, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Eq, ast.NotEq, ast.Call, ast.Name, ast.Load, ast.Constant,
)


def _region_namespace(z):
    """Имена, доступные в условиях области (векторизованы по сетке numpy)."""
    import numpy as np
    return {
        "z": z,
        "abs": np.abs, "Abs": np.abs,
        "re": np.real, "Re": np.real, "im": np.imag, "Im": np.imag,
        "arg": np.angle, "conj": np.conj,
        "sqrt": np.sqrt, "exp": np.exp, "log": np.log, "ln": np.log,
        "pi": np.pi, "e": np.e, "i": 1j, "I": 1j, "j": 1j,
    }


def eval_region_condition(cond: str, z):
    """
    Вычислить булево условие от z на numpy-сетке. AST-whitelist: только
    арифметика, сравнения, логика и вызовы разрешённых имён (abs/re/im/arg/…).
    """
    src = str(cond).replace("^", "**")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise GraphValidationError(f"Условие области {cond!r}: {e}")
    ns = _region_namespace(z)
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST):
            raise GraphValidationError(
                f"Условие области {cond!r}: конструкция "
                f"{type(node).__name__} не разрешена."
            )
        if isinstance(node, ast.Name) and node.id not in ns:
            raise GraphValidationError(
                f"Условие области {cond!r}: неизвестное имя {node.id!r}. "
                f"Допустимы: {sorted(k for k in ns if len(k) > 0)}"
            )
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise GraphValidationError(
                f"Условие области {cond!r}: разрешены только вызовы имён."
            )
    return eval(compile(tree, "<region>", "eval"), {"__builtins__": {}}, ns)


class ComplexRegionPlotNode(Node):
    """
    Область на комплексной плоскости по системе неравенств → картинка.

    Вход conds:LIST — строки-условия от z в python-нотации («abs(z-2)<3»,
    «re(z)>0», «arg(z)<pi/3», «abs(z-1)+abs(z+1)<8»); область — их И-пересечение.
    Считается по numpy-сетке (тонкая штриховка), границы отдаёт сама маска.
    """
    type_id = "complex_region_plot"
    category = "plot"
    display_name = "Область на ℂ-плоскости"
    description = ("Заштриховать область {z: все условия верны}. Вход: LIST "
                   "строк-условий от z (abs/re/im/arg…). Выход: IMAGE.")
    INPUTS = [Port("conds", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.IMAGE)]
    PARAMS_SCHEMA = {
        "span": {"type": "number", "default": 6, "optional": True},
        "resolution": {"type": "int", "default": 500, "optional": True},
        "title": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        import numpy as np
        plt = _matplotlib()
        conds = inputs.get("conds")
        if not isinstance(conds, (list, tuple)) or not conds:
            raise RetryGeneration(
                f"complex_region_plot {self.node_id!r}: нет условий области."
            )
        try:
            span = float(self.params.get("span", 6))
        except (TypeError, ValueError):
            span = 6.0
        try:
            n = max(100, int(self.params.get("resolution", 500)))
        except (TypeError, ValueError):
            n = 500

        xs = np.linspace(-span, span, n)
        ys = np.linspace(-span, span, n)
        X, Y = np.meshgrid(xs, ys)
        Z = X + 1j * Y
        with np.errstate(all="ignore"):
            mask = np.ones_like(X, dtype=bool)
            for cond in conds:
                val = eval_region_condition(str(cond), Z)
                mask &= np.asarray(val, dtype=bool)
        if not mask.any():
            raise RetryGeneration(
                f"complex_region_plot {self.node_id!r}: область пуста "
                f"в окне ±{span} — проверьте условия."
            )

        fig, ax = plt.subplots(figsize=(4.8, 4.8))
        ax.imshow(mask, extent=(-span, span, -span, span), origin="lower",
                  cmap="Blues", alpha=0.55, interpolation="nearest",
                  vmin=0, vmax=1.6)
        _axes_cross(ax, None)
        ax.set_xlim(-span, span)
        ax.set_ylim(-span, span)
        title = str(self.params.get("title", "")).strip()
        if title:
            ax.set_title(title, fontsize=10)
        img = _fig_to_image(fig)
        plt.close(fig)
        return {"out": img}
