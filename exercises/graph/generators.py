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

EXAMPLE_GRAPH = {
    "version": 1,
    "nodes": [
        {"id": "v",     "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "t",     "type": "random_natural", "params": {"min": 1, "max": 50}},
        {"id": "vars",  "type": "var_dict",       "params": {"names": ["v", "t"]}},
        {"id": "f",     "type": "formula",        "params": {"expr": "v * t"}},
        {"id": "chk",   "type": "constraint",     "params": {"kind": "natural", "min": 1, "max": 500}},
        {"id": "res",   "type": "var_dict",       "params": {"names": ["N"]}},
        {"id": "cond",  "type": "template",       "params": {"text": "Пройдено #v# м за #t# с. Найдите путь N."}},
        {"id": "ans",   "type": "template",       "params": {"text": "N = #N# м"}},
        {"id": "tb_c",  "type": "text_block"},
        {"id": "tb_a",  "type": "text_block"},
        {"id": "lc",    "type": "block_list",     "params": {"count": 1}},
        {"id": "la",    "type": "block_list",     "params": {"count": 1}},
        {"id": "task",  "type": "static_task"},
    ],
    "edges": [
        {"from": "v:out",   "to": "vars:v"},
        {"from": "t:out",   "to": "vars:t"},
        {"from": "vars:out", "to": "f:vars"},
        {"from": "f:out",   "to": "chk:in"},
        {"from": "chk:out", "to": "res:N"},
        {"from": "vars:out", "to": "cond:vars"},
        {"from": "res:out", "to": "ans:vars"},
        {"from": "cond:out", "to": "tb_c:text"},
        {"from": "ans:out", "to": "tb_a:text"},
        {"from": "tb_c:out", "to": "lc:in0"},
        {"from": "tb_a:out", "to": "la:in0"},
        {"from": "lc:out",  "to": "task:statement"},
        {"from": "la:out",  "to": "task:answer"},
    ],
    "meta": {"max_attempts": 100, "seed": None},
}


if __name__ == "__main__":
    gen = GraphConstructorGenerator(partition_id=0, name="demo", config=EXAMPLE_GRAPH)
    task = gen.generate()
    print("Условие:", task.statement[0].render_plain())
    print("Ответ:  ", task.answer[0].render_plain())
