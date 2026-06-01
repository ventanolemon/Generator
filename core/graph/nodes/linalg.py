"""
Узлы линейной алгебры (категория linalg).

Матрицы переносятся между узлами через PortType.MATRIX как объекты sympy.Matrix
(round-trip без потерь). Вектор — это матрица-столбец n×1 (то же значение типа
MATRIX), так что матричные операции (например, A·v) работают с векторами без
конверсий. Рендер в задание — узлом matrix_block (MATRIX→BLOCK через FormulaBlock
с окружением pmatrix).

PR-1 (ядро + алгебра): источники (matrix_const, random_matrix, identity),
операции (det/inverse/transpose/rank/mul/add/scalar/power), рендер. Системы и
операторы (rref/solve/eigen/nullspace) и вектор-геометрия (dot/cross/нормы,
прямые/плоскости) — следующими PR того же образца.

sympy импортируется лениво (см. core.graph.symbolic): движок графа headless.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType
from ..symbolic import as_matrix, is_matrix, parse_matrix, sympy, to_latex


# ---------- Источники ----------

class MatrixConstNode(Node):
    """
    Матрица-литерал из текста. Строки разделяются ';', элементы — ','.
    Например '1,2;3,4'. Вектор-столбец: '1;2;3'. Источник MATRIX.
    """
    type_id = "matrix_const"
    category = "linalg"
    display_name = "Матрица"
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"data": {"type": "string", "default": "1,0;0,1"}}

    def validate_params(self) -> None:
        parse_matrix(self.params.get("data", ""))

    def compute(self, inputs, ctx: ExecContext):
        return {"out": parse_matrix(self.params.get("data", ""))}


class RandomMatrixNode(Node):
    """
    Случайная «красивая» целочисленная матрица. Источник MATRIX.

    Параметры: rows, cols; min/max — диапазон элементов; invertible — требовать
    квадратную невырожденную матрицу с небольшим определителем (для обратимых
    задач). Воспроизводимость — через ctx.rng (как у random_natural).
    """
    type_id = "random_matrix"
    category = "linalg"
    display_name = "Случайная матрица"
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {
        "rows": {"type": "int", "default": 3},
        "cols": {"type": "int", "default": 3},
        "min": {"type": "int", "default": -3, "optional": True},
        "max": {"type": "int", "default": 3, "optional": True},
        "invertible": {"type": "enum", "values": ["no", "yes"], "default": "no",
                       "optional": True},
        "max_det": {"type": "int", "default": 12, "optional": True},
    }

    def validate_params(self) -> None:
        for k in ("rows", "cols"):
            try:
                if int(self.params.get(k, 3)) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                raise GraphValidationError(
                    f"Узел {self.node_id!r}: {k} должно быть целым ≥ 1."
                )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        rows = int(self.params.get("rows", 3))
        cols = int(self.params.get("cols", 3))
        lo = int(self.params.get("min", -3))
        hi = int(self.params.get("max", 3))
        invertible = str(self.params.get("invertible", "no")) == "yes"
        try:
            cap = int(self.params.get("max_det", 12))
        except (TypeError, ValueError):
            cap = 12
        rng = ctx.rng

        def draw():
            return sp.Matrix([[rng.randint(lo, hi) for _ in range(cols)]
                              for _ in range(rows)])

        if not invertible:
            return {"out": draw()}
        if rows != cols:
            raise RetryGeneration(
                f"random_matrix {self.node_id!r}: обратимая матрица должна быть квадратной."
            )
        for _ in range(300):
            M = draw()
            d = M.det()
            if d != 0 and abs(int(d)) <= cap:
                return {"out": M}
        raise RetryGeneration(
            f"random_matrix {self.node_id!r}: не удалось подобрать обратимую матрицу."
        )


class IdentityNode(Node):
    """Единичная матрица n×n. Источник MATRIX."""
    type_id = "identity"
    category = "linalg"
    display_name = "Единичная матрица"
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"size": {"type": "int", "default": 3}}

    def validate_params(self) -> None:
        try:
            if int(self.params.get("size", 3)) < 1:
                raise ValueError
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: size должно быть целым ≥ 1."
            )

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        return {"out": sp.eye(int(self.params.get("size", 3)))}


# ---------- Операции над одной матрицей (MATRIX → …) ----------

class DeterminantNode(Node):
    """Определитель квадратной матрицы (MATRIX → EXPR)."""
    type_id = "matrix_det"
    category = "linalg"
    display_name = "Определитель"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_det {self.node_id!r}: матрица не квадратная.")
        return {"out": M.det()}


class InverseNode(Node):
    """Обратная матрица (MATRIX → MATRIX). Для вырожденной — пере-генерация."""
    type_id = "matrix_inv"
    category = "linalg"
    display_name = "Обратная матрица"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_inv {self.node_id!r}: матрица не квадратная.")
        try:
            if M.det() == 0:
                raise RetryGeneration(f"matrix_inv {self.node_id!r}: матрица вырождена.")
            return {"out": M.inv()}
        except RetryGeneration:
            raise
        except Exception as e:
            raise RetryGeneration(f"matrix_inv {self.node_id!r}: {e}")


class TransposeNode(Node):
    """Транспонирование (MATRIX → MATRIX)."""
    type_id = "matrix_transpose"
    category = "linalg"
    display_name = "Транспонирование"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": as_matrix(inputs["in"]).T}


class RankNode(Node):
    """Ранг матрицы (MATRIX → NUMBER)."""
    type_id = "matrix_rank"
    category = "linalg"
    display_name = "Ранг"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(as_matrix(inputs["in"]).rank())}


class TraceNode(Node):
    """След (сумма диагонали) квадратной матрицы (MATRIX → EXPR)."""
    type_id = "matrix_trace"
    category = "linalg"
    display_name = "След"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.EXPR)]

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_trace {self.node_id!r}: матрица не квадратная.")
        return {"out": M.trace()}


class ScalarMultiplyNode(Node):
    """Умножение матрицы на скаляр (MATRIX × NUMBER → MATRIX)."""
    type_id = "matrix_scalar"
    category = "linalg"
    display_name = "Умножить на число"
    INPUTS = [Port("in", PortType.MATRIX), Port("k", PortType.NUMBER)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        sp = sympy()
        M = as_matrix(inputs["in"])
        k = sp.nsimplify(inputs.get("k", 1))
        return {"out": M * k}


class MatrixPowerNode(Node):
    """Возведение квадратной матрицы в целую степень (MATRIX → MATRIX)."""
    type_id = "matrix_power"
    category = "linalg"
    display_name = "Степень матрицы"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {"exponent": {"type": "int", "default": 2}}

    def compute(self, inputs, ctx: ExecContext):
        M = as_matrix(inputs["in"])
        if M.rows != M.cols:
            raise RetryGeneration(f"matrix_power {self.node_id!r}: матрица не квадратная.")
        n = int(self.params.get("exponent", 2))
        try:
            return {"out": M ** n}
        except Exception as e:
            raise RetryGeneration(f"matrix_power {self.node_id!r}: {e}")


# ---------- Операции над двумя матрицами ----------

class MatrixMultiplyNode(Node):
    """Произведение матриц A·B (MATRIX × MATRIX → MATRIX). Включает A·v."""
    type_id = "matrix_mul"
    category = "linalg"
    display_name = "Произведение матриц"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]

    def compute(self, inputs, ctx: ExecContext):
        A = as_matrix(inputs["a"])
        B = as_matrix(inputs["b"])
        if A.cols != B.rows:
            raise RetryGeneration(
                f"matrix_mul {self.node_id!r}: несогласованные размеры "
                f"{A.shape}·{B.shape}."
            )
        return {"out": A * B}


class MatrixAddNode(Node):
    """Сумма/разность матриц (MATRIX × MATRIX → MATRIX)."""
    type_id = "matrix_add"
    category = "linalg"
    display_name = "Сумма матриц"
    INPUTS = [Port("a", PortType.MATRIX), Port("b", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.MATRIX)]
    PARAMS_SCHEMA = {
        "op": {"type": "enum", "values": ["add", "sub"], "default": "add"},
    }

    def compute(self, inputs, ctx: ExecContext):
        A = as_matrix(inputs["a"])
        B = as_matrix(inputs["b"])
        if A.shape != B.shape:
            raise RetryGeneration(
                f"matrix_add {self.node_id!r}: разные размеры {A.shape} и {B.shape}."
            )
        return {"out": A - B if self.params.get("op") == "sub" else A + B}


# ---------- Рендер ----------

_MATRIX_ENVS = {"pmatrix": "p", "bmatrix": "b", "vmatrix": "v", "Vmatrix": "V"}


class MatrixBlockNode(Node):
    """
    Формульный блок из матрицы (MATRIX → BLOCK через FormulaBlock).

    env — окружение LaTeX: pmatrix (круглые), bmatrix (квадратные),
    vmatrix (определитель |·|), Vmatrix (норма ‖·‖). Опц. префикс 'A = …'.
    """
    type_id = "matrix_block"
    category = "linalg"
    display_name = "Матричный блок"
    INPUTS = [Port("in", PortType.MATRIX)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "env": {"type": "enum", "values": list(_MATRIX_ENVS), "default": "pmatrix"},
        "prefix": {"type": "string", "default": "", "optional": True},
    }

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import FormulaBlock          # ленивый: тянет Qt
        sp = sympy()
        M = as_matrix(inputs["in"])
        env = self.params.get("env", "pmatrix")
        latex = sp.latex(M, mat_delim="", mat_str=env)
        prefix = str(self.params.get("prefix", "")).strip()
        if prefix:
            latex = f"{prefix} = {latex}"
        return {"out": FormulaBlock(latex)}
