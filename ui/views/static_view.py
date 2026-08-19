"""
StaticTaskView — представление одного статичного задания.

Кнопка 'Сгенерировать' создаёт новый таск, кнопка 'Показать ответ'
переключает между условием и ответом. Если генератор объявил флаг
EXPORTABLE — появляется кнопка прямого экспорта текущего задания в Word.

Хром (заголовок + строка кнопок + прокручиваемый контейнер блоков) —
из BaseTaskView (контракт K4).
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox, QSpinBox
)

from core import Capability, StaticTask, TaskGenerator
from ui.exporter import export_tasks_to_docx
from ui.variants import generate_variants, was_interrupted
from .base_view import BaseTaskView

#: Верхняя граница счётчика вариантов при выгрузке.
MAX_VARIANTS = 50


class StaticTaskView(BaseTaskView):
    """Один таск + кнопка показа ответа. Подходит для всех STATIC-генераторов."""

    REQUIRED_CAPABILITY = Capability.STATIC

    def _capability_error(self, generator: TaskGenerator) -> str:
        return (
            f"StaticTaskView не работает с {generator.name!r}: "
            "у него нет флага STATIC."
        )

    def _init_state(self) -> None:
        self.current_task: StaticTask | None = None
        self.showing_answer = False
        self.is_exportable = Capability.EXPORTABLE in self.generator.capabilities

    def build_controls(self, row: QHBoxLayout) -> None:
        self.generate_btn = QPushButton("Сгенерировать", self)
        self.answer_btn = QPushButton("Показать ответ", self)
        self.answer_btn.setEnabled(False)
        row.addWidget(self.generate_btn)
        row.addWidget(self.answer_btn)

        if self.is_exportable:
            self.export_btn = QPushButton("Экспорт в Word", self)
            self.export_btn.setEnabled(False)
            self.export_btn.clicked.connect(self._on_export)
            row.addWidget(self.export_btn)

            # Сколько вариантов положить в файл. До этого выгружалось
            # ровно то, что на экране, — один вариант, — и собрать лист
            # на группу было нечем: приходилось жать «Экспорт» тридцать
            # раз в тридцать файлов и сшивать их вручную.
            row.addWidget(QLabel("вариантов:", self))
            self.variants_spin = QSpinBox(self)
            self.variants_spin.setRange(1, MAX_VARIANTS)
            self.variants_spin.setValue(1)
            self.variants_spin.setToolTip(
                "1 — выгрузить то, что показано на экране. Больше — "
                "породить столько же новых вариантов и положить их в один "
                "файл. Показанное на экране в этом случае не участвует: "
                "варианты порождаются заново, чтобы их было ровно столько, "
                "сколько запрошено."
            )
            row.addWidget(self.variants_spin)

        row.addStretch()

        self.generate_btn.clicked.connect(self._on_generate)
        self.answer_btn.clicked.connect(self._on_toggle_answer)

    def _on_generate(self) -> None:
        task = self.generator.generate()
        if not isinstance(task, StaticTask):
            raise TypeError(
                f"{self.generator.name!r} вернул {type(task).__name__}, "
                "ожидался StaticTask"
            )
        self.current_task = task
        self.showing_answer = False
        self.answer_btn.setEnabled(True)
        self.answer_btn.setText("Показать ответ")
        if self.is_exportable:
            self.export_btn.setEnabled(True)
        self.show_blocks(task.statement)

    def _on_toggle_answer(self) -> None:
        if self.current_task is None:
            return
        self.showing_answer = not self.showing_answer
        if self.showing_answer:
            self.answer_btn.setText("Показать условие")
            self.show_blocks(self.current_task.answer)
        else:
            self.answer_btn.setText("Показать ответ")
            self.show_blocks(self.current_task.statement)

    def _on_export(self) -> None:
        if self.current_task is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в Word",
            f"{self.generator.name}.docx", "Word (*.docx)"
        )
        if not path:
            return

        # Путь к файлу спрашивается ДО генерации: отменённый диалог
        # сохранения не должен стоить пользователю четырёх минут ожидания
        # на медленном разделе.
        asked = self.variants_spin.value()
        if asked == 1:
            tasks = [self.current_task]
        else:
            tasks = generate_variants(self, self.generator, asked,
                                      label="Готовим варианты для выгрузки")
            note = was_interrupted(asked, len(tasks))
            if note:
                QMessageBox.information(self, "Экспорт", note)
            if not tasks:
                return

        try:
            export_tasks_to_docx(
                tasks, path,
                title=self.generator.name,
                with_answers=True,
            )
            QMessageBox.information(
                self, "Экспорт",
                "Готово." if len(tasks) == 1
                else f"Готово: {len(tasks)} вариантов.")
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Ошибка: {e}")
