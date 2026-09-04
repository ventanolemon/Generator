"""
Проверяемое задание на десктопе открывается и «смотреть», и «решать».

Разрыв, который это закрывает, найден вопросом «а почему у статичного
задания нет переключателя в динамический режим». Ответ оказался такой:
на вебе переключатель есть (`CheckableTaskView` в `GeneratorPage.tsx`), а
десктоп смотрел ТОЛЬКО на флаг `INTERACTIVE` и про `CHECKABLE` не знал
вовсе. Одно и то же задание вело себя по-разному в зависимости от того,
откуда его открыли: на вебе физику можно решить с проверкой, на десктопе
ответ можно было лишь подсмотреть.

Проверяется поэтому не «класс существует», а само поведение:
проверяемый генератор попадает в представление с двумя режимами, оба
режима работают, и ни один не отнимает того, что было раньше.

Запуск:
    python -m unittest tests.test_checkable_view
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from core import Capability
from core.interactive import SolvingGenerator, SpecSession, is_solvable
from exercises.fisic import FisicConstructorGenerator
from ui.views import (
    CheckableTaskView, InteractiveTaskView, StaticTaskView, TableTaskView,
)
from ui.windows.generator_window import GeneratorWindow


PHYSICS = {
    "condition": "Тело массой #m# движется с ускорением #a#. "
                 "Найдите действующую на него силу.",
    "result_letter": "F",
    "formula": "m * a",
    "dimension": "Н",
    "variables": {"m": {"min": 1, "max": 9, "kind": "natural"},
                  "a": {"min": 1, "max": 9, "kind": "natural"}},
}


def _generator() -> FisicConstructorGenerator:
    return FisicConstructorGenerator(
        partition_id=2, name="конструктор", config=PHYSICS)


class RoutingTests(unittest.TestCase):
    """Какое представление получает раздел."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_checkable_generator_gets_both_modes(self):
        view = GeneratorWindow._pick_view(None, _generator(), "table")
        self.assertIsInstance(view, CheckableTaskView)

    def test_the_old_routing_would_have_given_only_a_table(self):
        """
        Регрессия наоборот: показываем, что прежнее правило (смотреть
        только на INTERACTIVE) отправило бы физику в табличный вид, где
        отвечать нечем.
        """
        generator = _generator()
        self.assertNotIn(Capability.INTERACTIVE, generator.capabilities)
        self.assertIn(Capability.CHECKABLE, generator.capabilities)

    def test_plain_static_generator_is_untouched(self):
        """Задание без спецификации ответа решать нечем — и не предлагаем."""
        from exercises.linal.generators import Linal2DGenerator
        generator = Linal2DGenerator()
        self.assertFalse(is_solvable(generator))
        view = GeneratorWindow._pick_view(None, generator, "single")
        self.assertIsInstance(view, StaticTaskView)
        self.assertNotIsInstance(view, CheckableTaskView)

    def test_interactive_generator_still_goes_straight_to_the_session(self):
        """У тренажёра слов статической формы нет — переключать нечего."""
        import pathlib

        from exercises.english.generators import WordsTrainerGenerator
        root = pathlib.Path(__file__).resolve().parent.parent
        path = next((root / "resources" / "words").glob("*.json"))
        generator = WordsTrainerGenerator(
            name="Английский", words_path=path, partition_id=1)
        view = GeneratorWindow._pick_view(None, generator, "single")
        self.assertIsInstance(view, InteractiveTaskView)


class ModeTests(unittest.TestCase):
    """Оба режима работают, и переключение между ними тоже."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = CheckableTaskView(_generator())

    def test_it_opens_in_look_mode(self):
        """
        Так раздел вёл себя до появления автопроверки, и её появление не
        должно менять то, что человек уже привык открывать.
        """
        self.assertEqual(self.view.current_mode(), CheckableTaskView.LOOK)
        self.assertIsInstance(self.view.stack.currentWidget(), StaticTaskView)

    def test_solving_view_is_built_only_when_asked(self):
        """
        Решающее представление сразу начинает сессию, то есть генерирует
        задание. Делать это при открытии раздела, который просматривают,
        — лишняя работа.
        """
        self.assertIsNone(self.view.solving_view)
        self.view.set_mode(CheckableTaskView.SOLVE)
        self.assertIsNotNone(self.view.solving_view)

    def test_switching_back_and_forth_works(self):
        self.view.set_mode(CheckableTaskView.SOLVE)
        self.assertEqual(self.view.current_mode(), CheckableTaskView.SOLVE)
        self.view.set_mode(CheckableTaskView.LOOK)
        self.assertEqual(self.view.current_mode(), CheckableTaskView.LOOK)
        self.view.set_mode(CheckableTaskView.SOLVE)
        self.assertEqual(self.view.current_mode(), CheckableTaskView.SOLVE)

    def test_buttons_show_the_current_mode(self):
        self.assertTrue(self.view.look_btn.isChecked())
        self.assertFalse(self.view.solve_btn.isChecked())
        self.view.solve_btn.click()
        self.assertTrue(self.view.solve_btn.isChecked())
        self.assertFalse(self.view.look_btn.isChecked())

    def test_export_stays_available_in_look_mode(self):
        """
        Появление режима «решать» не должно отнимать у преподавателя
        выгрузку — ровно поэтому здесь переключатель, а не замена вида.
        """
        from PyQt6.QtWidgets import QPushButton
        labels = {b.text() for b
                  in self.view.static_view.findChildren(QPushButton)}
        self.assertTrue([t for t in labels if "Word" in t or "спорт" in t],
                        f"кнопки выгрузки нет среди {labels}")


class SolvingGeneratorTests(unittest.TestCase):
    """Обёртка, превращающая проверяемое задание в сессию."""

    def test_it_looks_interactive_from_outside(self):
        wrapper = SolvingGenerator(_generator())
        self.assertIn(Capability.INTERACTIVE, wrapper.capabilities)

    def test_it_keeps_the_name_and_the_section_number(self):
        inner = _generator()
        wrapper = SolvingGenerator(inner)
        self.assertEqual(wrapper.name, inner.name)
        self.assertEqual(wrapper.partition_id, inner.partition_id)

    def test_it_does_not_change_the_wrapped_generator(self):
        """
        Обёртка, а не примесь: генератор не должен узнать, что его
        открыли в решающем виде, — иначе его возможности изменились бы
        для всех вызывающих сразу.
        """
        inner = _generator()
        SolvingGenerator(inner)
        self.assertNotIn(Capability.INTERACTIVE, inner.capabilities)

    def test_it_produces_a_working_session(self):
        session = SolvingGenerator(_generator()).generate()
        self.assertIsInstance(session, SpecSession)
        statement = " ".join(b.render_plain() for b in session.initial_prompt())
        self.assertIn("Найдите", statement)

    def test_a_wrong_answer_is_rejected(self):
        session = SolvingGenerator(_generator()).generate()
        self.assertFalse(session.submit("-999999").correct)

    def test_the_answer_as_shown_is_accepted(self):
        """
        Ответ, переписанный С ЭКРАНА, обязан засчитываться.

        Тонкость, на которой эта проверка сначала и споткнулась:
        `spec.written` — только числовая часть, а на экран идёт число
        ВМЕСТЕ с размерностью («32 Н»), и проверка размерность требует.
        Поэтому сверяться надо с тем, что видит студент, а не с
        внутренним полем.
        """
        session = SolvingGenerator(_generator()).generate()
        spec = session.questions[0].spec
        shown = f"{spec.written} {spec.unit}".strip()
        self.assertTrue(session.submit(shown).correct,
                        f"ответ с экрана {shown!r} не принят")

    def test_a_number_without_the_unit_is_not_accepted(self):
        """
        Обратная сторона того же: размерность — часть ответа физической
        задачи, и «32» вместо «32 Н» это не мелочь формы.
        """
        session = SolvingGenerator(_generator()).generate()
        spec = session.questions[0].spec
        self.assertFalse(session.submit(spec.written).correct)

    def test_a_task_without_a_spec_says_so_plainly(self):
        class Empty:
            name = "без ответа"
            partition_id = None
            capabilities = Capability.STATIC

            def generate(self):
                from core import StaticTask, TextBlock
                return StaticTask(statement=[TextBlock("условие")], answer=[])

        with self.assertRaises(ValueError) as caught:
            SolvingGenerator(Empty()).generate()
        self.assertIn("спецификации", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
