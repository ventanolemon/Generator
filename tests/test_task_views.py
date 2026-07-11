"""
Smoke-тесты 4 представлений заданий после консолидации на BaseTaskView
(контракт K4 плана docs/ui_rework_plan.md, задача A4).

Генераторы — фейки (без bootstrap/exercises): проверяем, что хром общий,
а уникальное поведение каждого view (ответ/таблица/сессия/варианты) не
изменилось.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_task_views
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core import (
        Capability, InteractiveTask, StaticTask, TaskGenerator, TextBlock,
        TurnResult,
    )
    from ui.views import (
        BaseTaskView, InteractiveTaskView, StaticTaskView, TableTaskView,
        TestExportView,
    )

    class FakeStaticGen(TaskGenerator):
        name = "Фейк-статик"
        capabilities = (Capability.STATIC | Capability.EXPORTABLE
                        | Capability.GROUPABLE)

        def generate(self):
            return StaticTask([TextBlock("условие")], [TextBlock("ответ")])

    class FakeSession(InteractiveTask):
        """Сессия из 2 вопросов; 'ok' — правильный ответ."""

        def __init__(self):
            self.turns = 0

        def initial_prompt(self):
            return [TextBlock("вопрос 1")]

        def submit(self, user_input: str) -> TurnResult:
            self.turns += 1
            nxt = [TextBlock("вопрос 2")] if self.turns < 2 else None
            return TurnResult(correct=(user_input == "ok"),
                              feedback=[TextBlock("фидбек")],
                              next_prompt=nxt)

        def is_finished(self) -> bool:
            return self.turns >= 2

    class FakeInteractiveGen(TaskGenerator):
        name = "Фейк-сессия"
        capabilities = Capability.INTERACTIVE

        def generate(self):
            return FakeSession()

    class NoCapGen(TaskGenerator):
        name = "Пустой"
        capabilities = Capability.NONE

        def generate(self):  # pragma: no cover — не должен вызываться
            raise AssertionError


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_all_views_share_base_and_title_class(self):
        views = [
            StaticTaskView(FakeStaticGen()),
            TableTaskView(FakeStaticGen()),
            InteractiveTaskView(FakeInteractiveGen()),
            TestExportView(FakeStaticGen()),
        ]
        for v in views:
            self.assertIsInstance(v, BaseTaskView)
            self.assertEqual(v.title_label.text(), v.generator.name)
            self.assertEqual(v.title_label.property("class"), "title")

    def test_capability_check_raises(self):
        for cls in (StaticTaskView, TableTaskView,
                    InteractiveTaskView, TestExportView):
            with self.assertRaises(ValueError):
                cls(NoCapGen())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class StaticViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_and_toggle_answer(self):
        v = StaticTaskView(FakeStaticGen())
        self.assertFalse(v.answer_btn.isEnabled())
        v.generate_btn.click()
        self.assertIsNotNone(v.current_task)
        self.assertTrue(v.answer_btn.isEnabled())
        self.assertTrue(v.export_btn.isEnabled())  # EXPORTABLE у фейка есть
        v.answer_btn.click()
        self.assertTrue(v.showing_answer)
        self.assertEqual(v.answer_btn.text(), "Показать условие")
        v.answer_btn.click()
        self.assertFalse(v.showing_answer)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class TableViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_rows_and_delete(self):
        v = TableTaskView(FakeStaticGen())
        v.gen_btn.click()
        v.gen_btn.click()
        self.assertEqual(len(v.tasks), 2)
        self.assertEqual(v.table.rowCount(), 2)
        v._delete_task(v.tasks[0])
        self.assertEqual(len(v.tasks), 1)
        self.assertEqual(v.table.rowCount(), 1)
        self.assertEqual(v.table.item(0, 0).text(), "1")  # перенумерация


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class InteractiveViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_session_flow_and_finish(self):
        v = InteractiveTaskView(FakeInteractiveGen())
        self.assertTrue(v.input_field.isEnabled())

        v.input_field.setText("ok")
        v.submit_btn.click()
        self.assertEqual((v.score_correct, v.score_total), (1, 1))

        v.input_field.setText("мимо")
        v.submit_btn.click()
        self.assertEqual((v.score_correct, v.score_total), (1, 2))
        # Сессия из 2 вопросов закончилась — ввод выключен
        self.assertFalse(v.input_field.isEnabled())
        self.assertFalse(v.submit_btn.isEnabled())

        v.restart_btn.click()                     # новая сессия
        self.assertTrue(v.input_field.isEnabled())
        self.assertEqual((v.score_correct, v.score_total), (0, 0))


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class TestExportViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_generate_variants_tabs(self):
        v = TestExportView(FakeStaticGen())
        v.variants_spin.setValue(3)
        v.gen_btn.click()
        self.assertEqual(len(v.variants), 3)
        self.assertEqual(v.tabs.count(), 3)
        # Переключение «С ответами» перестраивает вкладки без падений
        v.show_answers_chk.setChecked(True)
        self.assertEqual(v.tabs.count(), 3)


if __name__ == "__main__":
    unittest.main()
