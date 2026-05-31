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


# Ключ в ExecContext.extra, под которым map кладёт текущий элемент.
MAP_ITEM_KEY = "__map_item__"

# Типы элемента, которые map_item умеет отдавать в тело.
_ITEM_TYPES = {
    "number": PortType.NUMBER,
    "string": PortType.STRING,
    "block": PortType.BLOCK,
}


class MapItemNode(Node):
    """Текущий элемент коллекции внутри тела map. Источник."""
    type_id = "map_item"
    category = "control"
    display_name = "Элемент (map)"
    PARAMS_SCHEMA = {
        "type": {"type": "enum", "values": list(_ITEM_TYPES), "default": "string"},
    }

    def validate_params(self) -> None:
        t = self.params.get("type", "string")
        if t not in _ITEM_TYPES:
            raise GraphValidationError(
                f"Узел {self.node_id!r}: неизвестный тип элемента {t!r}. "
                f"Допустимы: {list(_ITEM_TYPES)}"
            )

    def output_ports(self):
        return [Port("out", _ITEM_TYPES.get(self.params.get("type", "string"),
                                            PortType.STRING))]

    def compute(self, inputs, ctx: ExecContext):
        v = ctx.extra.get(MAP_ITEM_KEY)
        t = self.params.get("type", "string")
        if t == "number":
            try:
                return {"out": float(v)}
            except (TypeError, ValueError):
                raise RetryGeneration(
                    f"map_item {self.node_id!r}: элемент {v!r} не число."
                )
        if t == "string":
            return {"out": "" if v is None else str(v)}
        return {"out": v}  # block — передаём как есть


class MapNode(Node):
    """
    Применить тело к каждому элементу входного списка, собрать BLOCK-результаты
    в BLOCK_LIST.

    Вход items:LIST — коллекция. Внутри тела доступны map_item (текущий элемент)
    и loop_index (его индекс 0..N-1). Результат итерации — свободный выход тела
    типа BLOCK. Тело хранится в params['body'] (вложенный граф) и исполняется
    отдельным GraphExecutor по образцу repeat.
    """
    type_id = "map"
    category = "control"
    display_name = "Map (по списку)"
    INPUTS = [Port("items", PortType.LIST)]
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {
        "body": {"type": "subgraph", "default": {"nodes": [], "edges": [], "meta": {}}},
    }

    def validate_params(self) -> None:
        body = self.params.get("body")
        if body is not None and not isinstance(body, dict):
            raise GraphValidationError(
                f"Узел {self.node_id!r}: 'body' должен быть вложенным графом (объектом)."
            )

    def compute(self, inputs, ctx: ExecContext):
        from ..executor import GraphExecutor
        from ..spec import GraphSpec

        body = self.params.get("body") or {"nodes": [], "edges": [], "meta": {}}
        spec = GraphSpec.parse(body)

        items = inputs.get("items") or []
        if not isinstance(items, (list, tuple)):
            raise RetryGeneration(
                f"map {self.node_id!r}: на вход items пришёл не список ({type(items).__name__})."
            )

        from . import DEFAULT_REGISTRY
        collected: list = []
        for i, el in enumerate(items):
            ex = GraphExecutor(spec, registry=DEFAULT_REGISTRY)
            result_ep = ex.free_output_of_type(PortType.BLOCK)
            outputs = ex.run_full(extra={MAP_ITEM_KEY: el, LOOP_INDEX_KEY: i})
            if result_ep is not None:
                node_id, port = result_ep
                collected.append(outputs[node_id][port])
        return {"out": collected}
