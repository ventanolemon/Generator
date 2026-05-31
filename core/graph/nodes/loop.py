"""
Узлы цикла (категория control, scoped-loop).

repeat — агрегатор: исполняет своё ТЕЛО (вложенный граф в params["body"]) N раз
и собирает результаты в список. Тело — это полноценный GraphSpec со своими
узлами; его «результат итерации» — единственный свободный выход типа BLOCK.
Внутри тела доступен узел loop_index, отдающий номер текущей итерации (0..N-1),
что позволяет делать строки таблицы/подзадачи, зависящие от номера.

Реализация не трогает планировщик внешнего графа: repeat — обычная вершина
внешнего DAG (count:NUMBER → out:BLOCK_LIST), а тело исполняется отдельным
GraphExecutor внутри compute(). Так вложенность получается естественно и без
псевдоциклов в основном исполнителе.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


# Ключ в ExecContext.extra, под которым repeat кладёт индекс итерации.
LOOP_INDEX_KEY = "__loop_index__"


class LoopIndexNode(Node):
    """Номер текущей итерации цикла (0-based). Источник внутри тела repeat."""
    type_id = "loop_index"
    category = "control"
    display_name = "Индекс итерации"
    OUTPUTS = [Port("out", PortType.NUMBER)]

    def compute(self, inputs, ctx: ExecContext):
        return {"out": float(ctx.extra.get(LOOP_INDEX_KEY, 0))}


class RepeatNode(Node):
    """
    Повторить тело N раз, собрать BLOCK-результаты итераций в BLOCK_LIST.

    Параметры:
      body         — вложенный граф (dict со spec: nodes/edges/meta);
      max_iterations — потолок N (защита от опечатки в count).
    Вход count (NUMBER) задаёт число повторов; если не подключён — берётся
    параметр count.
    """
    type_id = "repeat"
    category = "control"
    display_name = "Повторить (цикл)"
    INPUTS = [Port("count", PortType.NUMBER, required=False)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "count": {"type": "int", "default": 3},
        "max_iterations": {"type": "int", "default": 1000, "optional": True},
        "body": {"type": "subgraph", "default": {"nodes": [], "edges": [], "meta": {}}},
    }

    def validate_params(self) -> None:
        body = self.params.get("body")
        if body is not None and not isinstance(body, dict):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'body' должен быть вложенным графом (объектом)."
            )

    def _count(self, inputs) -> int:
        raw = inputs.get("count", self.params.get("count", 3))
        try:
            n = int(round(float(raw)))
        except (TypeError, ValueError):
            raise RetryGeneration(f"repeat {self.node_id!r}: count не число ({raw!r}).")
        try:
            cap = int(self.params.get("max_iterations", 1000))
        except (TypeError, ValueError):
            cap = 1000
        return max(0, min(n, cap))

    def compute(self, inputs, ctx: ExecContext):
        # Импорт здесь, чтобы избежать цикла импорта executor↔nodes на загрузке.
        from ..executor import GraphExecutor
        from ..spec import GraphSpec

        body = self.params.get("body") or {"nodes": [], "edges": [], "meta": {}}
        spec = GraphSpec.parse(body)

        n = self._count(inputs)
        collected: list = []
        for i in range(n):
            ex = GraphExecutor(spec, registry=self._registry())
            result_ep = ex.free_output_of_type(PortType.BLOCK)
            outputs = ex.run_full(extra={LOOP_INDEX_KEY: i})
            if result_ep is not None:
                node_id, port = result_ep
                collected.append(outputs[node_id][port])
        return {"out": collected}

    def _registry(self):
        # Тело использует тот же реестр узлов, что и внешний граф.
        from . import DEFAULT_REGISTRY
        return DEFAULT_REGISTRY
