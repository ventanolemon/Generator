"""
Выбор числа вариантов в экспортёре.

Что здесь закрепляется
----------------------
До этой правки табличный вид давал РОВНО ОДНО задание за нажатие, а
одиночный вид выгружал ровно то, что на экране. Лист на тридцать
вариантов собирался тридцатью кликами — при том что на вебе то же самое
делается числом в поле (`frontend/src/components/ExportDialog.tsx`). Два
клиента расходились в поведении, и расходились молча.

Отдельно проверяется то, без чего счётчик был бы вреден: **прерывание**.
Замер по 89 статическим генераторам поставки: у «Первого замечательного
предела» одна генерация занимает от 3,7 до 13,1 секунды (медиана 9,0), то
есть тридцать вариантов — около четырёх с половиной минут. Кнопка,
замораживающая окно на четыре минуты без возможности отменить, хуже
отсутствующей кнопки.

Запуск:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_variant_count
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication

from core import Capability, StaticTask, TaskGenerator, TextBlock
from core.generator import STATIC_DEFAULT
from ui.variants import generate_variants, was_interrupted
from ui.views.static_view import StaticTaskView
from ui.views.table_view import TableTaskView
from ui.views.test_view import TestExportView

_app = QApplication.instance() or QApplication([])


class _Counting(TaskGenerator):
    """Генератор, считающий обращения. Ничего тяжёлого не делает."""

    capabilities = STATIC_DEFAULT

    def __init__(self, name: str = "Считалка"):
        self.name = name
        self.partition_id = 1
        self.calls = 0

    def generate(self) -> StaticTask:
        self.calls += 1
        return StaticTask(statement=[TextBlock(f"условие {self.calls}")],
                          answer=[TextBlock(f"ответ {self.calls}")])


class _Wrong(_Counting):
    """Генератор, возвращающий не StaticTask."""

    def generate(self):
        self.calls += 1
        return "не задание"


class BatchTests(unittest.TestCase):
    """Общий помощник: сколько просили, столько и породили."""

    def test_it_generates_exactly_what_was_asked(self):
        generator = _Counting()
        produced = generate_variants(None, generator, 7)
        self.assertEqual(len(produced), 7)
        self.assertEqual(generator.calls, 7)

    def test_zero_and_negative_ask_for_nothing(self):
        generator = _Counting()
        self.assertEqual(generate_variants(None, generator, 0), [])
        self.assertEqual(generate_variants(None, generator, -3), [])
        self.assertEqual(generator.calls, 0,
                         "генератор не должен вызываться вовсе")

    def test_a_generator_returning_something_else_yields_nothing(self):
        """
        Пропускается молча — ронять всю пачку из-за одного чужого ответа
        незачем, — но и в результат такое не попадает.
        """
        produced = generate_variants(None, _Wrong(), 4)
        self.assertEqual(produced, [])

    def test_interruption_keeps_what_was_already_made(self):
        """
        Главное свойство прерывания: сделанное не выбрасывается.
        Преподаватель, нажавший «Прервать» на двадцатом варианте из
        пятидесяти, хотел двадцать, а не ноль.
        """
        class _Interrupting(_Counting):
            view = None

            def generate(self):
                task = super().generate()
                if self.calls == 3:
                    # Нажатие «Прервать» изнутри цикла: то же, что делает
                    # пользователь, только без мыши.
                    for widget in _app.topLevelWidgets():
                        if widget.__class__.__name__ == "QProgressDialog":
                            widget.cancel()
                return task

        generator = _Interrupting()
        produced = generate_variants(None, generator, 10)
        self.assertGreater(len(produced), 0, "сделанное выброшено")
        self.assertLess(len(produced), 10, "прерывание не сработало")


class InterruptionMessageTests(unittest.TestCase):
    """О недоборе обязаны сказать — молчание даёт нераспечатанный лист."""

    def test_a_full_batch_says_nothing(self):
        self.assertIsNone(was_interrupted(10, 10))
        self.assertIsNone(was_interrupted(10, 11))

    def test_a_short_batch_names_both_numbers(self):
        note = was_interrupted(30, 12)
        self.assertIsNotNone(note)
        self.assertIn("12", note)
        self.assertIn("30", note)

    def test_an_empty_batch_says_so_plainly(self):
        note = was_interrupted(30, 0)
        self.assertIsNotNone(note)
        self.assertIn("ни одного", note)


class TableViewTests(unittest.TestCase):
    """Табличный вид: счётчик добавляет за одно нажатие."""

    def _view(self):
        generator = _Counting()
        view = TableTaskView(generator)
        self.addCleanup(view.deleteLater)
        return view, generator

    def test_the_default_is_one_so_nothing_changes_for_old_habits(self):
        view, _ = self._view()
        self.assertEqual(view.count_spin.value(), 1)
        view._on_generate()
        self.assertEqual(len(view.tasks), 1)

    def test_a_count_adds_that_many_in_one_click(self):
        view, generator = self._view()
        view.count_spin.setValue(12)
        view._on_generate()
        self.assertEqual(len(view.tasks), 12)
        self.assertEqual(view.table.rowCount(), 12)
        self.assertEqual(generator.calls, 12)

    def test_the_table_accumulates_rather_than_replaces(self):
        """
        Таблица — курируемый список: строки можно удалять поштучно.
        Замещение стёрло бы отобранное предыдущим нажатием.
        """
        view, _ = self._view()
        view.count_spin.setValue(4)
        view._on_generate()
        view.count_spin.setValue(3)
        view._on_generate()
        self.assertEqual(len(view.tasks), 7)
        self.assertEqual(view.table.rowCount(), 7)

    def test_the_running_total_is_shown_and_stays_true(self):
        view, _ = self._view()
        view.count_spin.setValue(5)
        view._on_generate()
        self.assertIn("5", view.count_label.text())
        view._delete_task(view.tasks[0])
        self.assertIn("4", view.count_label.text())

    def test_rows_are_renumbered_after_a_deletion(self):
        view, _ = self._view()
        view.count_spin.setValue(3)
        view._on_generate()
        view._delete_task(view.tasks[1])
        numbers = [view.table.item(r, 0).text()
                   for r in range(view.table.rowCount())]
        self.assertEqual(numbers, ["1", "2"])

    def test_the_upper_bound_is_declared(self):
        view, _ = self._view()
        self.assertEqual(view.count_spin.minimum(), 1)
        self.assertGreaterEqual(view.count_spin.maximum(), 30)


class StaticViewTests(unittest.TestCase):
    """Одиночный вид: счётчик управляет ВЫГРУЗКОЙ, а не показом."""

    def _view(self):
        generator = _Counting()
        view = StaticTaskView(generator)
        self.addCleanup(view.deleteLater)
        return view, generator

    def test_the_default_exports_what_is_on_screen(self):
        """
        Единица означает «выгрузить показанное», а не «породить ещё
        одно». Иначе преподаватель, посмотревший задание и нажавший
        «Экспорт», получил бы в файле ДРУГОЕ задание — и заметил бы это
        не сразу.
        """
        view, generator = self._view()
        view._on_generate()
        shown = view.current_task
        self.assertEqual(view.variants_spin.value(), 1)
        exported = self._export(view)
        self.assertEqual(exported, [shown])
        self.assertEqual(generator.calls, 1, "лишняя генерация при выгрузке")

    def test_a_count_above_one_generates_that_many(self):
        view, generator = self._view()
        view._on_generate()
        view.variants_spin.setValue(9)
        exported = self._export(view)
        self.assertEqual(len(exported), 9)
        self.assertEqual(generator.calls, 1 + 9)

    def test_the_path_is_asked_before_the_long_work(self):
        """
        Отменённый диалог сохранения не должен стоить минут ожидания:
        на медленном разделе девять вариантов — это минуты.
        """
        view, generator = self._view()
        view._on_generate()
        view.variants_spin.setValue(9)
        calls_before = generator.calls
        self._export(view, path="")            # пользователь отменил выбор
        self.assertEqual(generator.calls, calls_before,
                         "генерация пошла до выбора файла")

    def _export(self, view, path=None):
        """Нажать «Экспорт», подменив выбор файла и сам экспорт."""
        import ui.views.static_view as module

        captured = []
        if path is None:
            handle = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
            handle.close()
            path = handle.name
            self.addCleanup(lambda: pathlib.Path(path).exists()
                            and pathlib.Path(path).unlink())

        original_dialog = module.QFileDialog.getSaveFileName
        original_export = module.export_tasks_to_docx
        original_box = module.QMessageBox.information
        module.QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (path, ""))
        module.export_tasks_to_docx = lambda tasks, *a, **k: captured.extend(tasks)
        module.QMessageBox.information = staticmethod(lambda *a, **k: None)
        try:
            view._on_export()
        finally:
            module.QFileDialog.getSaveFileName = original_dialog
            module.export_tasks_to_docx = original_export
            module.QMessageBox.information = original_box
        return captured


class TestViewTests(unittest.TestCase):
    """У теста счётчик был и раньше — проверяется, что он не сломан."""

    def test_it_still_generates_the_requested_number(self):
        generator = _Counting()
        view = TestExportView(generator)
        self.addCleanup(view.deleteLater)
        view.variants_spin.setValue(6)
        view._on_generate()
        self.assertEqual(len(view.variants), 6)
        self.assertEqual(view.tabs.count(), 6)

    def test_regeneration_replaces_rather_than_accumulates(self):
        """
        В отличие от таблицы, тест — цельный комплект: второе нажатие
        собирает НОВЫЙ комплект, а не дописывает к старому.
        """
        view = TestExportView(_Counting())
        self.addCleanup(view.deleteLater)
        view.variants_spin.setValue(3)
        view._on_generate()
        view._on_generate()
        self.assertEqual(len(view.variants), 3)


class ParityTests(unittest.TestCase):
    """Десктоп и веб должны спрашивать одно и то же."""

    def test_every_exporting_view_can_ask_for_a_count(self):
        """
        Проверка от обратного: если появится четвёртое представление с
        выгрузкой и без счётчика, разойдутся не два клиента, а три.
        """
        generator = _Counting()
        for cls, attribute in ((TableTaskView, "count_spin"),
                               (StaticTaskView, "variants_spin"),
                               (TestExportView, "variants_spin")):
            with self.subTest(view=cls.__name__):
                view = cls(generator)
                self.addCleanup(view.deleteLater)
                spin = getattr(view, attribute, None)
                self.assertIsNotNone(
                    spin, f"{cls.__name__} выгружает, но числа не спрашивает")
                self.assertEqual(spin.minimum(), 1)
                self.assertGreaterEqual(spin.maximum(), 30)

    def test_the_web_dialog_offers_the_same_upper_bound(self):
        """
        Верхняя граница названа в обоих клиентах и должна совпадать:
        преподаватель, привыкший к пятидесяти на вебе, не должен
        упираться в другое число на десктопе.
        """
        from ui.views.static_view import MAX_VARIANTS
        from ui.views.table_view import MAX_AT_ONCE

        self.assertEqual(MAX_VARIANTS, 50)
        self.assertEqual(MAX_AT_ONCE, 50)


if __name__ == "__main__":
    unittest.main()
