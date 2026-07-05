"""
Граф-примеры — отдельный «предмет» с реализациями разных типов заданий на
визуальном граф-языке (constracted=4). Витрина возможностей и одновременно
сквозной регрессионный набор: каждый пример — полный валидный GraphSpec,
который собирается и исполняется движком (см. tests/test_graph_examples.py).

Демонстрируемые приёмы: числовое задание с проверкой результата, пул вариантов
(random_choice), полиморфная подстановка строки/выражения в текст, символьные
производная и предел с авто-переменной, определитель и линейная алгебра,
квадратное уравнение (solve), отбраковка по условию (guard), генерация в цикле
(туннели, list_to_matrix), выбор ветви (case).
"""

from .examples import EXAMPLES, example_graph, example_names
from .series_exam import SERIES_EXAM, generate_variant, series_exam_names
from .complex_exam import (
    COMPLEX_EXAM, complex_exam_names, generate_complex_variant,
)

__all__ = [
    "EXAMPLES", "example_graph", "example_names",
    "SERIES_EXAM", "generate_variant", "series_exam_names",
    "COMPLEX_EXAM", "complex_exam_names", "generate_complex_variant",
]
