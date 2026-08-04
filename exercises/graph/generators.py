"""
Адаптер визуального графа — калька с FisicConstructorGenerator.

Один GraphConstructorGenerator обслуживает раздел типа «граф» (constracted=4):
раздел хранит описание графа в generation_parametrs, адаптер исполняет его
и возвращает Task. Движок (core.graph) делает всю работу.

Регистрация в bootstrap — задача Фазы 1; здесь только сам генератор.
"""

from __future__ import annotations
import json

from core import STATIC_DEFAULT, Task, TaskGenerator
from core.graph import GraphExecutor, GraphSpec


class GraphConstructorGenerator(TaskGenerator):
    """Универсальный генератор для разделов-графов из БД."""

    name = "Визуальный граф"
    capabilities = STATIC_DEFAULT

    def __init__(self, partition_id: int, name: str, config: "str | dict"):
        self.partition_id = partition_id
        self.name = name
        self._spec = self._to_spec(config)
        self._executor: GraphExecutor | None = None

    def configure(self, params: dict) -> None:
        """Обновить описание графа из БД (зовётся реестром при выдаче)."""
        if not params:
            return
        if "raw" in params:
            self._spec = self._to_spec(params["raw"])
        else:
            self._spec = self._to_spec(params)
        self._executor = None

    def generate(self) -> Task:
        # Сборка/валидация графа кэшируется: spec статичен между configure().
        if self._executor is None:
            self._executor = GraphExecutor(self._spec)
        return self._executor.run()

    @staticmethod
    def _to_spec(config: "str | dict") -> GraphSpec:
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (json.JSONDecodeError, TypeError):
                config = {}
        return GraphSpec.parse(config if isinstance(config, dict) else {})


# ---------- Пример графа (физика v*t, для ручного запуска) ----------

# Пример по умолчанию — нарочно простой, на новых «умных» узлах: формула сама
# заводит входы v,t по своей записи; финальный узел «Задание» принимает текст
# условия с маркерами #имя# и значение ответа прямо в слот — узлы «Текст» на
# условие и на ответ больше не нужны.
#
# Счёт: тринадцать узлов в первой версии языка, шесть после «умных» узлов,
# четыре сейчас. Причём это задание ещё и проверяемое: слот объявил
# размерность, и `task.is_checkable` — True, чего в шестиузловой версии не
# было вовсе.
EXAMPLE_GRAPH = {
    "version": 1,
    "nodes": [
        {"id": "v",    "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "t",    "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "f",    "type": "formula",        "params": {"expr": "v * t"}},
        {"id": "task", "type": "task", "params": {
            "statement": "Пройдено #v# м за #t# с. Найдите путь.",
            "slots": ["s:number:unit=м:label=S"],
        }},
    ],
    "edges": [
        {"from": "v:out", "to": "f:v"},
        {"from": "t:out", "to": "f:t"},
        {"from": "v:out", "to": "task:v"},
        {"from": "t:out", "to": "task:t"},
        {"from": "f:out", "to": "task:s"},
    ],
    "meta": {"max_attempts": 100, "seed": None},
}


# Ещё проще — всё задание в одном узле (для палитры «Готовые задания»).
EXAMPLE_SIMPLE_TASK = {
    "version": 1,
    "nodes": [
        {"id": "task", "type": "simple_task", "params": {
            "variables": ["v:1:50", "t:1:50"],
            "statement": "Пройдено #v# м за #t# с. Найдите путь.",
            "answer_formula": "v * t",
            "answer": "S = #result# м",
        }},
    ],
    "edges": [],
    "meta": {"max_attempts": 100, "seed": None},
}


if __name__ == "__main__":
    gen = GraphConstructorGenerator(partition_id=0, name="demo", config=EXAMPLE_GRAPH)
    task = gen.generate()
    print("Условие:", task.statement[0].render_plain())
    print("Ответ:  ", task.answer[0].render_plain())
