"""
Тесты врезки Фазы 1 (headless, без PyQt6):
  * Repository: маппинги view/editor kind для constracted=4;
  * GraphConstructorGenerator: приём конфига как dict, JSON-строки и {"raw": ...}
    (формы, которые приходят из generation_parametrs БД) и его валидация
    через сборку GraphExecutor.

GUI-часть (GraphEditor, меню окна, bootstrap-регистрация) тянет Qt и проверяется
в среде с PyQt6; здесь — логика, доступная headless.
"""

from __future__ import annotations
import json
import unittest

from core.repository import Partition, Repository
from core.graph import GraphExecutor
from exercises.graph.generators import EXAMPLE_GRAPH, GraphConstructorGenerator


def _part(constracted: int) -> Partition:
    return Partition(id=1, subject_id=1, name="x",
                     constracted=constracted, generation_params={})


class RepositoryMappingTests(unittest.TestCase):
    def setUp(self):
        self.repo = Repository(":memory:")     # путь не используется этими методами

    def test_view_kind_for_graph(self):
        self.assertEqual(self.repo.view_kind_for(_part(4)), "table")

    def test_editor_kind_for_graph(self):
        self.assertEqual(self.repo.editor_kind_for(_part(4)), "graph")

    def test_existing_kinds_unchanged(self):
        self.assertEqual(self.repo.editor_kind_for(_part(1)), "fisic")
        self.assertEqual(self.repo.view_kind_for(_part(3)), "test")
        self.assertIsNone(self.repo.editor_kind_for(_part(0)))


class ConfigFormsTests(unittest.TestCase):
    """GraphConstructorGenerator принимает те же формы конфига, что и fisic."""

    def _assert_buildable(self, gen: GraphConstructorGenerator):
        # Сборка исполнителя = полная структурная валидация графа (без generate()).
        GraphExecutor(gen._spec)

    def test_dict_config(self):
        gen = GraphConstructorGenerator(1, "g", EXAMPLE_GRAPH)
        self._assert_buildable(gen)

    def test_json_string_config(self):
        gen = GraphConstructorGenerator(1, "g", json.dumps(EXAMPLE_GRAPH))
        self._assert_buildable(gen)

    def test_configure_with_raw(self):
        gen = GraphConstructorGenerator(1, "g", {})
        gen.configure({"raw": json.dumps(EXAMPLE_GRAPH)})
        self._assert_buildable(gen)

    def test_configure_with_dict(self):
        gen = GraphConstructorGenerator(1, "g", {})
        gen.configure(EXAMPLE_GRAPH)
        self._assert_buildable(gen)

    def test_example_graph_is_valid(self):
        # Эталонный граф из адаптера должен собираться без ошибок.
        GraphExecutor(GraphConstructorGenerator(1, "g", EXAMPLE_GRAPH)._spec)


if __name__ == "__main__":
    unittest.main()
