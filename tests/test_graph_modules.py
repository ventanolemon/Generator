"""
Тесты организации языка в модули (Этап 1: чистая группировка категорий,
без ограничений в движке — core.graph.modules).

Инвариант: каждая категория, реально используемая узлами в DEFAULT_REGISTRY,
отнесена РОВНО к одному модулю — иначе узел молча пропадёт из палитры при
любом состоянии фильтра. NodePalette (Qt) проверяется отдельно: скрытие
модуля прячет узлы из дерева, но не мешает добавить/исполнить их программно.
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import DEFAULT_REGISTRY, MODULE_ORDER, MODULES, category_module

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


class ModuleDefinitionTests(unittest.TestCase):
    def test_core_module_exists_and_is_marked_core(self):
        self.assertIn("core", MODULES)
        self.assertTrue(MODULES["core"]["core"])

    def test_only_core_is_marked_core(self):
        non_core = [n for n, m in MODULES.items() if m["core"] and n != "core"]
        self.assertEqual(non_core, [])

    def test_module_order_matches_definitions(self):
        self.assertEqual(set(MODULE_ORDER), set(MODULES))

    def test_categories_partition_without_overlap(self):
        seen: dict[str, str] = {}
        for name, mod in MODULES.items():
            for cat in mod["categories"]:
                self.assertNotIn(cat, seen,
                                 f"{cat} в модулях {seen.get(cat)} и {name}")
                seen[cat] = name

    def test_every_registered_node_category_is_mapped(self):
        # Категория без модуля означает: category_module() тихо вернёт 'core',
        # и узел будет виден только пока core виден (что верно, но не нарочно) —
        # этот тест ловит именно "не нарочно": каждая категория ДОЛЖНА быть
        # явно перечислена в каком-то модуле.
        all_mapped = {c for m in MODULES.values() for c in m["categories"]}
        used = {cls.category for cls in DEFAULT_REGISTRY}
        missing = used - all_mapped
        self.assertEqual(missing, set(),
                         f"категории без модуля: {missing}")

    def test_category_module_lookup(self):
        self.assertEqual(category_module("symbolic"), "symbolic")
        self.assertEqual(category_module("linalg"), "linalg")
        self.assertEqual(category_module("source"), "core")
        self.assertEqual(category_module("assembly"), "core")

    def test_unknown_category_falls_back_to_core(self):
        self.assertEqual(category_module("no_such_category_xyz"), "core")

    def test_engine_ignores_modules_entirely(self):
        # Модули не участвуют в сборке/исполнении графа — все type_id доступны
        # реестру независимо от того, какой модуль их "содержит".
        from core.graph import GraphExecutor, GraphSpec
        data = {"nodes": [{"id": "s", "type": "symbol", "params": {"name": "x"}},
                          {"id": "d", "type": "matrix_det"}],
                "edges": []}
        # Узел symbol (модуль symbolic) регистрируется несмотря на то, что
        # модули вообще нигде не переданы в GraphExecutor/NodeRegistry.
        ex = GraphExecutor(GraphSpec.parse(
            {"nodes": [{"id": "s", "type": "symbol", "params": {"name": "x"}}],
             "edges": []}))
        self.assertIn("s", ex.nodes)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class NodePaletteModuleFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _palette(self):
        from ui.editors.graph_canvas.palette import NodePalette
        return NodePalette()

    def _category_headers(self, palette) -> set[str]:
        return {palette.tree.topLevelItem(i).text(0)
               for i in range(palette.tree.topLevelItemCount())}

    def test_all_modules_visible_by_default(self):
        p = self._palette()
        headers = self._category_headers(p)
        self.assertIn("Символьная математика", headers)
        self.assertIn("Линейная алгебра", headers)

    def test_hiding_module_removes_its_categories(self):
        p = self._palette()
        p._toggle_module("linalg", False)
        headers = self._category_headers(p)
        self.assertNotIn("Линейная алгебра", headers)
        # Другие модули не задеты.
        self.assertIn("Символьная математика", headers)

    def test_core_categories_always_present(self):
        p = self._palette()
        for name in ("symbolic", "linalg", "ode", "english", "image", "plot"):
            p._toggle_module(name, False)
        headers = self._category_headers(p)
        self.assertIn("Источники", headers)
        self.assertIn("Управление", headers)
        self.assertIn("Сборка задания", headers)

    def test_toggle_back_on_restores_category(self):
        p = self._palette()
        p._toggle_module("plot", False)
        self.assertNotIn("Графика (ℂ-плоскость)", self._category_headers(p))
        p._toggle_module("plot", True)
        headers = self._category_headers(p)
        self.assertIn("Изображения / ОПВС", headers)  # неизменный модуль image
        self.assertIn("Графика (ℂ-плоскость)", headers)
        # ...и узел из неё снова доступен для добавления двойным кликом.
        found = False
        for i in range(p.tree.topLevelItemCount()):
            head = p.tree.topLevelItem(i)
            for j in range(head.childCount()):
                from PyQt6.QtCore import Qt
                if head.child(j).data(0, Qt.ItemDataRole.UserRole) == "conformal_map_plot":
                    found = True
        self.assertTrue(found)

    def test_hidden_node_still_addable_programmatically(self):
        # Фильтр — только про палитру; GraphDocument.add_node не смотрит на неё.
        from core.graph import GraphDocument
        p = self._palette()
        p._toggle_module("linalg", False)
        doc = GraphDocument(registry=p.registry)
        doc.add_node("matrix_det", node_id="d")   # не бросает, узел из "скрытого" модуля
        self.assertIn("d", doc.nodes)


if __name__ == "__main__":
    unittest.main()
