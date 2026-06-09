"""
Тесты правил финального узла (Этап A улучшения циклов).

Движок:
  * понятные ошибки: несколько свободных TASK-выходов (с именами узлов),
    отсутствие финала при run();
  * запрет узлов-заданий (выход TASK) внутри тел repeat/map и ветвей case,
    включая вложенные тела, с путём до нарушителя в сообщении.

Модель (GraphDocument): вычисление кандидатов в финал для живой подсветки.

UI (Qt offscreen): сцена помечает финал бейджем "result", конфликты —
"conflict", узлы-задания внутри открытого тела цикла — "forbidden".
"""

from __future__ import annotations
import os
import unittest

from core.graph import (
    GraphDocument, GraphExecutor, GraphSpec, GraphValidationError,
)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


def _exec(data: dict) -> GraphExecutor:
    return GraphExecutor(GraphSpec.parse(data))


def _task_chain(suffix: str) -> tuple[list, list]:
    """Полноценный static_task с запитанными обязательными входами."""
    return (
        [
            {"id": f"lc{suffix}", "type": "block_list", "params": {"count": 1}},
            {"id": f"la{suffix}", "type": "block_list", "params": {"count": 1}},
            {"id": f"t{suffix}", "type": "static_task"},
        ],
        [
            {"from": f"lc{suffix}:out", "to": f"t{suffix}:statement"},
            {"from": f"la{suffix}:out", "to": f"t{suffix}:answer"},
        ],
    )


class FinalNodeErrorTests(unittest.TestCase):
    def test_multiple_sinks_error_names_nodes(self):
        n1, e1 = _task_chain("_a")
        n2, e2 = _task_chain("_b")
        with self.assertRaisesRegex(GraphValidationError, "t_a.*t_b") as cm:
            _exec({"nodes": n1 + n2, "edges": e1 + e2})
        # Сообщение объясняет правило и способ исправления.
        self.assertIn("Финальным может быть только один", str(cm.exception))

    def test_run_without_sink_suggests_task_node(self):
        ex = _exec({
            "nodes": [{"id": "c", "type": "constant_number",
                       "params": {"value": 1}}],
            "edges": [],
        })
        with self.assertRaisesRegex(GraphValidationError, "узел-задание"):
            ex.run()


class TaskInsideBodyTests(unittest.TestCase):
    def test_task_inside_repeat_body_rejected(self):
        body = {"nodes": [{"id": "t", "type": "static_task"}], "edges": []}
        data = {
            "nodes": [{"id": "rep", "type": "repeat",
                       "params": {"count": 2, "body": body}}],
            "edges": [],
        }
        with self.assertRaisesRegex(GraphValidationError, r"rep\.body › t"):
            _exec(data)

    def test_task_inside_map_body_rejected(self):
        body = {"nodes": [{"id": "t", "type": "simple_task"}], "edges": []}
        data = {
            "nodes": [
                {"id": "sl", "type": "string_list",
                 "params": {"items": ["a", "b"]}},
                {"id": "mp", "type": "map", "params": {"body": body}},
            ],
            "edges": [{"from": "sl:out", "to": "mp:items"}],
        }
        with self.assertRaisesRegex(GraphValidationError, r"mp\.body › t"):
            _exec(data)

    def test_task_inside_case_branch_rejected(self):
        branch = {"nodes": [{"id": "t", "type": "static_task"}], "edges": []}
        data = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 0}},
                {"id": "cs", "type": "case",
                 "params": {"cases": 2, "case_1": branch}},
            ],
            "edges": [{"from": "n:out", "to": "cs:selector"}],
        }
        with self.assertRaisesRegex(GraphValidationError, r"cs\.case_1 › t"):
            _exec(data)

    def test_task_inside_case_default_rejected(self):
        branch = {"nodes": [{"id": "t", "type": "static_task"}], "edges": []}
        data = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 0}},
                {"id": "cs", "type": "case",
                 "params": {"cases": 1, "default": branch}},
            ],
            "edges": [{"from": "n:out", "to": "cs:selector"}],
        }
        with self.assertRaisesRegex(GraphValidationError, r"cs\.default › t"):
            _exec(data)

    def test_task_inside_nested_repeat_rejected(self):
        inner_body = {"nodes": [{"id": "t", "type": "static_task"}], "edges": []}
        outer_body = {
            "nodes": [{"id": "inner", "type": "repeat",
                       "params": {"count": 1, "body": inner_body}}],
            "edges": [],
        }
        data = {
            "nodes": [{"id": "outer", "type": "repeat",
                       "params": {"count": 1, "body": outer_body}}],
            "edges": [],
        }
        with self.assertRaisesRegex(
            GraphValidationError, r"outer\.body › inner\.body › t"
        ):
            _exec(data)

    def test_select_with_task_type_inside_body_rejected(self):
        # Динамический TASK-выход (select c value_type=task) тоже запрещён.
        body = {
            "nodes": [{"id": "sel", "type": "select",
                       "params": {"value_type": "task"}}],
            "edges": [],
        }
        data = {
            "nodes": [{"id": "rep", "type": "repeat",
                       "params": {"count": 1, "body": body}}],
            "edges": [],
        }
        with self.assertRaisesRegex(GraphValidationError, r"rep\.body › sel"):
            _exec(data)

    def test_block_body_still_allowed(self):
        # Обычное тело со свободным BLOCK-выходом валидируется как раньше,
        # а финал внешнего графа — static_task.
        ex = _exec(_GRAPH_WITH_BLOCK_BODY)
        self.assertEqual(ex.result, ("task", "out"))


# Корректный граф: цикл с BLOCK-телом, финал — static_task снаружи.
_GRAPH_WITH_BLOCK_BODY = {
    "nodes": [
        {"id": "rep", "type": "repeat", "params": {"count": 2, "body": {
            "nodes": [
                {"id": "tpl", "type": "template", "params": {"text": "строка"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [{"from": "tpl:out", "to": "tb:text"}],
        }}},
        {"id": "ans", "type": "template", "params": {"text": "ответ"}},
        {"id": "tba", "type": "text_block"},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "rep:out", "to": "task:statement"},
        {"from": "ans:out", "to": "tba:text"},
        {"from": "tba:out", "to": "task:answer"},
    ],
}


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — пропуск исполнения блоков")
class TaskBodyRunTests(unittest.TestCase):
    def test_block_body_runs(self):
        task = _exec(_GRAPH_WITH_BLOCK_BODY).run()
        self.assertEqual(len(task.statement), 2)


class DocumentSinkTests(unittest.TestCase):
    def test_single_sink_detected(self):
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        self.assertEqual(doc.task_sink_ids(), ["t1"])
        self.assertEqual(doc.task_node_ids(), ["t1"])

    def test_two_free_sinks_conflict(self):
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        doc.add_node("simple_task", node_id="t2")
        self.assertEqual(sorted(doc.task_sink_ids()), ["t1", "t2"])

    def test_consumed_task_output_is_not_sink(self):
        # static_task → select(task): потреблённый TASK не финал,
        # финал — свободный выход самого select.
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        doc.add_node("select", params={"value_type": "task"}, node_id="sel")
        doc.add_edge("t1", "out", "sel", "on_true")
        self.assertEqual(doc.task_sink_ids(), ["sel"])
        self.assertEqual(sorted(doc.task_node_ids()), ["sel", "t1"])

    def test_type_has_task_output(self):
        doc = GraphDocument()
        self.assertTrue(doc.type_has_task_output("static_task"))
        self.assertTrue(doc.type_has_task_output("simple_task"))
        self.assertFalse(doc.type_has_task_output("constant_number"))
        self.assertFalse(doc.type_has_task_output("no_such_type"))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SceneResultMarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _scene(self, doc):
        from ui.editors.graph_canvas.scene import GraphScene
        return GraphScene(doc)

    def test_single_task_marked_as_result(self):
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        doc.add_node("constant_number", node_id="c1")
        scene = self._scene(doc)
        self.assertEqual(scene.node_items["t1"].result_role, "result")
        self.assertIsNone(scene.node_items["c1"].result_role)

    def test_two_tasks_marked_as_conflict(self):
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        doc.add_node("simple_task", node_id="t2")
        scene = self._scene(doc)
        self.assertEqual(scene.node_items["t1"].result_role, "conflict")
        self.assertEqual(scene.node_items["t2"].result_role, "conflict")

    def test_marks_follow_edits(self):
        from PyQt6.QtCore import QPointF
        doc = GraphDocument()
        doc.add_node("static_task", node_id="t1")
        scene = self._scene(doc)
        self.assertEqual(scene.node_items["t1"].result_role, "result")
        # Добавили второй TASK-узел — оба становятся конфликтом.
        scene.add_node("simple_task", QPointF(50, 50))
        self.assertEqual(scene.node_items["t1"].result_role, "conflict")

    def test_subgraph_marks_task_as_forbidden(self):
        doc = GraphDocument()
        doc.is_subgraph = True
        doc.add_node("static_task", node_id="t1")
        scene = self._scene(doc)
        self.assertEqual(scene.node_items["t1"].result_role, "forbidden")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class EditorSubgraphFlagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _editor(self):
        from ui.editors.graph_editor import GraphEditor

        class FakeRepo:
            def get_partition(self, *a, **k):
                return None

        ed = GraphEditor(FakeRepo(), subject_id=3, partition_id=None)
        ed._load_doc(GraphDocument())
        return ed

    def test_enter_subgraph_sets_flag(self):
        from PyQt6.QtCore import QPointF
        ed = self._editor()
        rep = ed.scene.add_node("repeat", QPointF(100, 100))
        self.assertFalse(ed.doc.is_subgraph)
        ed._enter_subgraph(rep.node_id, "body")
        self.assertTrue(ed.doc.is_subgraph)
        ed._exit_subgraph()
        self.assertFalse(ed.doc.is_subgraph)

    def test_check_reports_final_node(self):
        from exercises.graph.generators import EXAMPLE_GRAPH
        ed = self._editor()
        ed._load_doc(GraphDocument.from_spec_dict(EXAMPLE_GRAPH))
        ed._on_check()
        self.assertIn("Финальный узел: task", ed.preview.toPlainText())

    def test_check_warns_when_no_final_node(self):
        ed = self._editor()
        doc = GraphDocument()
        doc.add_node("constant_number", node_id="c1")
        ed._load_doc(doc)
        ed._on_check()
        self.assertIn("финального узла нет", ed.preview.toPlainText())


if __name__ == "__main__":
    unittest.main()
