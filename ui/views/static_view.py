"""
StaticTaskView — представление одного статичного задания.

Кнопка 'Сгенерировать' создаёт новый таск, кнопка 'Показать ответ'
переключает между условием и ответом. Если генератор объявил флаг
EXPORTABLE — появляется кнопка прямого экспорта текущего задания в Word.
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QScrollArea, QLabel,
    QFileDialog, QMessageBox
)

from core import Capability, StaticTask, TaskGenerator
from ui.utils import render_blocks, clear_layout
from ui.exporter import export_tasks_to_docx


class StaticTaskView(QWidget):
    """Один таск + кнопка показа ответа. Подходит для всех STATIC-генераторов."""

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        if Capability.STATIC not in generator.capabilities:
            raise ValueError(
                f"StaticTaskView не работает с {generator.name!r}: "
                "у него нет флага STATIC."
            )

        self.generator = generator
        self.current_task: StaticTask | None = None
        self.showing_answer = False
        self.is_exportable = Capability.EXPORTABLE in generator.capabilities

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel(self.generator.name, self)
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        btns = QHBoxLayout()
        self.generate_btn = QPushButton("Сгенерировать", self)
        self.answer_btn = QPushButton("Показать ответ", self)
        self.answer_btn.setEnabled(False)
        btns.addWidget(self.generate_btn)
        btns.addWidget(self.answer_btn)

        if self.is_exportable:
            self.export_btn = QPushButton("Экспорт в Word", self)
            self.export_btn.setEnabled(False)
            self.export_btn.clicked.connect(self._on_export)
            btns.addWidget(self.export_btn)

        btns.addStretch()
        root.addLayout(btns)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.content_holder = QWidget(self.scroll)
        self.content_layout = QVBoxLayout(self.content_holder)
        self.scroll.setWidget(self.content_holder)
        root.addWidget(self.scroll, stretch=1)

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
        self._show_blocks(task.statement)

    def _on_toggle_answer(self) -> None:
        if self.current_task is None:
            return
        self.showing_answer = not self.showing_answer
        if self.showing_answer:
            self.answer_btn.setText("Показать условие")
            self._show_blocks(self.current_task.answer)
        else:
            self.answer_btn.setText("Показать ответ")
            self._show_blocks(self.current_task.statement)

    def _on_export(self) -> None:
        if self.current_task is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в Word",
            f"{self.generator.name}.docx", "Word (*.docx)"
        )
        if not path:
            return
        try:
            export_tasks_to_docx(
                [self.current_task], path,
                title=self.generator.name,
                with_answers=True,
            )
            QMessageBox.information(self, "Экспорт", "Готово.")
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Ошибка: {e}")

    def _show_blocks(self, blocks) -> None:
        clear_layout(self.content_layout)
        widget = render_blocks(blocks, self.content_holder)
        self.content_layout.addWidget(widget)
