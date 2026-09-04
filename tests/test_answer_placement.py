"""
Размещение ответов на десктопе: те же четыре, что на вебе.

Что здесь закрепляется
----------------------
До этой правки настольная выгрузка знала одну настройку — `with_answers`,
и раскладка была **своя в каждом из трёх мест**:

* веб-служба — четыре размещения;
* `docx_backend` — ответы всегда в конце файла;
* `win32_backend` — то же, но заголовок «Эталон ответов» и без разрывов
  страниц между вариантами.

Три копии одного понятия, и расхождение между ними не проявлялось никак,
кроме как в готовом файле у пользователя. Теперь раскладка описана один
раз (`core/export_api.build_with`), а платформы приносят только МЕХАНИКУ
письма — три действия протокола `DocumentWriter`.

Отсюда и содержание проверок: не «красиво ли получилось», а
**одинаково ли** и **отличаются ли размещения друг от друга по существу**.

Запуск:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_answer_placement
"""

from __future__ import annotations

import pathlib
import tempfile
import unittest
import zipfile

from PyQt6.QtWidgets import QApplication

from core import StaticTask, TextBlock
from core.export_api import ANSWER_PLACEMENTS, build_with
from ui.docx_export import PLACEMENTS
from ui.exporter import export_tasks_to_docx, export_test_to_docx
from ui.widgets.answer_placement import CHOICES, AnswerPlacementBox

_app = QApplication.instance() or QApplication([])


def _task(n: int) -> StaticTask:
    return StaticTask(statement=[TextBlock(f"условие {n}")],
                      answer=[TextBlock(f"ответ {n}")])


class _Recorder:
    """Писец, который ничего не пишет, а запоминает. Реализует протокол."""

    def __init__(self):
        self.events: list[tuple] = []

    def heading(self, text, level):
        self.events.append(("h", text, level))

    def page_break(self):
        self.events.append(("break",))

    def blocks(self, blocks):
        for block in blocks:
            # `content` — имя в сериализации, в объекте поле зовётся
            # `text`. Берём из to_dict, чтобы не зависеть от того,
            # как блок устроен внутри.
            self.events.append(("b", block.to_dict().get("content", "")))

    def headings(self):
        return [e[1] for e in self.events if e[0] == "h"]

    def texts(self):
        return [e[1] for e in self.events if e[0] == "b"]


class LayoutIsSharedTests(unittest.TestCase):
    """Раскладка описана один раз и доступна десктопу."""

    def test_the_desktop_takes_the_placements_from_core(self):
        """
        Не свой список, а тот же самый объект. Второй список рано или
        поздно разошёлся бы с первым, и разошёлся бы молча.
        """
        self.assertIs(PLACEMENTS, ANSWER_PLACEMENTS)

    def test_every_placement_has_a_label_and_a_warning(self):
        for code in ANSWER_PLACEMENTS:
            with self.subTest(code=code):
                self.assertIn(code, CHOICES)
                label, hint = CHOICES[code]
                self.assertTrue(label and hint)

    def test_the_dangerous_placement_says_it_is_dangerous(self):
        """
        «Под заданием» — единственное размещение, при котором лист нельзя
        раздать. Об этом обязана говорить подсказка, а не общее знание.
        """
        _label, hint = CHOICES["under"]
        self.assertIn("раздавать", hint.lower())


class PlacementSemanticsTests(unittest.TestCase):
    """Четыре размещения обязаны отличаться по существу, а не подписью."""

    def _events(self, placement, variants):
        writer = _Recorder()
        build_with(writer, variants, title="Работа", answers=placement)
        return writer

    def test_under_puts_each_answer_after_its_task(self):
        writer = self._events("under", [[_task(1), _task(2)]])
        self.assertEqual(writer.texts(),
                         ["условие 1", "ответ 1", "условие 2", "ответ 2"])

    def test_hidden_prints_no_answers_at_all(self):
        writer = self._events("hidden", [[_task(1), _task(2)]])
        self.assertEqual(writer.texts(), ["условие 1", "условие 2"])

    def test_variant_end_gathers_answers_after_the_variant(self):
        """
        Ключ отрывается вместе с концом варианта — ради этого размещение
        и существует. Значит все условия идут до всех ответов ЭТОГО
        варианта, а перед ключом стоит разрыв страницы.
        """
        writer = self._events("variant_end", [[_task(1), _task(2)]])
        self.assertEqual(writer.texts(),
                         ["условие 1", "условие 2", "ответ 1", "ответ 2"])
        kinds = [e[0] for e in writer.events]
        first_answer = writer.texts().index("ответ 1")
        self.assertIn("break", kinds[:len(kinds) - first_answer])

    def test_file_end_gathers_every_answer_at_the_very_end(self):
        writer = self._events("file_end",
                              [[_task(1)], [_task(2)]])
        self.assertEqual(writer.texts(),
                         ["условие 1", "условие 2", "ответ 1", "ответ 2"])

    def test_file_end_names_the_variant_each_answer_belongs_to(self):
        """
        Пачка ответов в конце бесполезна, если непонятно, к какому
        варианту какой относится.
        """
        writer = self._events("file_end", [[_task(1)], [_task(2)]])
        captions = " ".join(writer.headings())
        self.assertIn("Вариант 1", captions)
        self.assertIn("Вариант 2", captions)

    def test_a_single_variant_is_not_called_a_variant(self):
        """Заголовок «Вариант 1» сообщал бы о структуре, которой нет."""
        writer = self._events("under", [[_task(1)]])
        self.assertNotIn("Вариант 1", writer.headings())


class DocxFileTests(unittest.TestCase):
    """Сквозная проверка: размещение доходит до файла."""

    def _export(self, placement, *, test=False):
        tasks = [_task(1), _task(2), _task(3)]
        path = pathlib.Path(tempfile.mkdtemp()) / "out.docx"
        if test:
            export_test_to_docx(tasks, str(path), title="Тест",
                                answers=placement)
        else:
            export_tasks_to_docx(tasks, str(path), title="Работа",
                                 answers=placement)
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode("utf-8", "replace")

    def test_hidden_really_has_no_answers_in_the_file(self):
        xml = self._export("hidden")
        self.assertNotIn("ответ 1", xml)
        self.assertIn("условие 1", xml)

    def test_under_has_them(self):
        xml = self._export("under")
        self.assertIn("ответ 1", xml)

    def test_every_placement_produces_a_readable_file(self):
        for placement in ANSWER_PLACEMENTS:
            with self.subTest(placement=placement):
                xml = self._export(placement)
                self.assertIn("условие 1", xml)

    def test_the_test_export_honours_placement_too(self):
        self.assertNotIn("ответ 1", self._export("hidden", test=True))
        self.assertIn("ответ 1", self._export("file_end", test=True))


class BackwardCompatibilityTests(unittest.TestCase):
    """Прежний булев параметр обязан работать как раньше."""

    def _export(self, **kwargs):
        path = pathlib.Path(tempfile.mkdtemp()) / "out.docx"
        export_tasks_to_docx([_task(1)], str(path), title="Работа", **kwargs)
        with zipfile.ZipFile(path) as archive:
            return archive.read("word/document.xml").decode("utf-8", "replace")

    def test_with_answers_false_still_hides_them(self):
        self.assertNotIn("ответ 1", self._export(with_answers=False))

    def test_with_answers_true_still_shows_them(self):
        self.assertIn("ответ 1", self._export(with_answers=True))

    def test_the_default_is_unchanged(self):
        """
        Умолчание настольного бэкенда — ответы В КОНЦЕ ФАЙЛА, а не под
        заданием: именно так он раскладывал их всегда. Совместимость
        означает «как было ЗДЕСЬ», а не «как у соседа».
        """
        xml = self._export()
        self.assertIn("ответ 1", xml)
        self.assertLess(xml.index("условие 1"), xml.index("ответ 1"))


class PlacementBoxTests(unittest.TestCase):
    """Виджет выбора."""

    def test_it_offers_every_placement_in_the_declared_order(self):
        box = AnswerPlacementBox()
        self.addCleanup(box.deleteLater)
        codes = [box.itemData(i) for i in range(box.count())]
        self.assertEqual(codes, list(ANSWER_PLACEMENTS))

    def test_the_default_is_honoured(self):
        for code in ANSWER_PLACEMENTS:
            with self.subTest(code=code):
                box = AnswerPlacementBox(default=code)
                self.addCleanup(box.deleteLater)
                self.assertEqual(box.placement(), code)

    def test_an_unknown_default_does_not_break_it(self):
        box = AnswerPlacementBox(default="нет-такого")
        self.addCleanup(box.deleteLater)
        self.assertIn(box.placement(), ANSWER_PLACEMENTS)

    def test_the_hint_follows_the_selection(self):
        box = AnswerPlacementBox(default="hidden")
        self.addCleanup(box.deleteLater)
        hidden_hint = box.toolTip()
        box.set_placement("under")
        self.assertNotEqual(box.toolTip(), hidden_hint)
        self.assertTrue(box.toolTip())


class ViewWiringTests(unittest.TestCase):
    """Каждое выгружающее представление спрашивает размещение."""

    def _generator(self):
        from tests.test_variant_count import _Counting
        return _Counting()

    def test_all_three_views_have_a_placement_control(self):
        from ui.views.static_view import StaticTaskView
        from ui.views.table_view import TableTaskView
        from ui.views.test_view import TestExportView

        generator = self._generator()
        for cls in (TableTaskView, StaticTaskView, TestExportView):
            with self.subTest(view=cls.__name__):
                view = cls(generator)
                self.addCleanup(view.deleteLater)
                box = getattr(view, "placement_box", None)
                self.assertIsNotNone(
                    box, f"{cls.__name__} выгружает, но размещения не спрашивает")
                self.assertIn(box.placement(), ANSWER_PLACEMENTS)

    def test_the_screen_checkbox_no_longer_decides_the_file(self):
        """
        Галочка «Показывать ответы» — про ЭКРАН. Раньше она же решала,
        попадут ли ответы в файл: преподаватель, скрывший ответы от
        заглядывающего студента, получал лист без ключа.
        """
        from ui.views.table_view import TableTaskView

        view = TableTaskView(self._generator())
        self.addCleanup(view.deleteLater)
        view.show_answers_chk.setChecked(False)
        view.placement_box.set_placement("under")
        captured = self._capture_export(view)
        self.assertEqual(captured, "under")

    def _capture_export(self, view):
        import ui.views.table_view as module

        seen = []
        path = pathlib.Path(tempfile.mkdtemp()) / "out.docx"
        original_dialog = module.QFileDialog.getSaveFileName
        original_export = module.export_tasks_to_docx
        original_box = module.QMessageBox.information
        module.QFileDialog.getSaveFileName = staticmethod(
            lambda *a, **k: (str(path), ""))
        module.export_tasks_to_docx = lambda *a, **k: seen.append(k.get("answers"))
        module.QMessageBox.information = staticmethod(lambda *a, **k: None)
        try:
            view._on_generate()
            view._on_export()
        finally:
            module.QFileDialog.getSaveFileName = original_dialog
            module.export_tasks_to_docx = original_export
            module.QMessageBox.information = original_box
        return seen[0] if seen else None


if __name__ == "__main__":
    unittest.main()
