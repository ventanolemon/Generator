"""
TestExportView — представление теста.

Тест — это собранный список заданий с вариантами. Кнопка генерации
создаёт N вариантов, каждый — большой StaticTask. Кнопка экспорта
сохраняет все варианты в один docx.

Хром (заголовок + строка кнопок) — из BaseTaskView (контракт K4);
центральная зона своя: вкладки с превью вариантов.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox, QCheckBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTabWidget
)

from core import Capability, StaticTask
from ui.utils import render_blocks
from ui.exporter import export_test_to_docx
from ui.variants import generate_variants, was_interrupted
from .base_view import BaseTaskView


class TestExportView(BaseTaskView):
    """Тест: N вариантов, каждый — StaticTask из TestGenerator."""

    REQUIRED_CAPABILITY = Capability.EXPORTABLE

    def _init_state(self) -> None:
        self.variants: list[StaticTask] = []

    def build_controls(self, row: QHBoxLayout) -> None:
        row.addWidget(QLabel("Вариантов:", self))
        self.variants_spin = QSpinBox(self)
        self.variants_spin.setRange(1, 50)
        self.variants_spin.setValue(4)
        row.addWidget(self.variants_spin)

        self.gen_btn = QPushButton("Сгенерировать варианты", self)
        self.export_btn = QPushButton("Экспорт в Word", self)
        self.show_answers_chk = QCheckBox("С ответами", self)
        row.addWidget(self.gen_btn)
        row.addWidget(self.export_btn)
        row.addWidget(self.show_answers_chk)
        row.addStretch()

        self.gen_btn.clicked.connect(self._on_generate)
        self.export_btn.clicked.connect(self._on_export)
        self.show_answers_chk.stateChanged.connect(self._refresh_tabs)

    def build_center(self, root: QVBoxLayout) -> None:
        # Превью вариантов в табах
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, stretch=1)

    def _on_generate(self) -> None:
        asked = self.variants_spin.value()
        # Через общий помощник: счётчик здесь был с самого начала, а вот
        # показа хода и отмены не было — пятьдесят вариантов медленного
        # раздела замораживали окно на минуты без признаков жизни.
        produced = generate_variants(self, self.generator, asked)
        self.variants = produced
        self.tabs.clear()
        self._refresh_tabs()
        note = was_interrupted(asked, len(produced))
        if note:
            QMessageBox.information(self, "Генерация", note)

    def _refresh_tabs(self) -> None:
        self.tabs.clear()
        for i, task in enumerate(self.variants, 1):
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            blocks = task.statement[:]
            if self.show_answers_chk.isChecked():
                blocks.append(__import__("core").TextBlock("\n— ОТВЕТЫ —\n"))
                blocks.extend(task.answer)
            scroll.setWidget(render_blocks(blocks, scroll))
            self.tabs.addTab(scroll, f"Вариант {i}")

    def _on_export(self) -> None:
        if not self.variants:
            QMessageBox.information(self, "Экспорт",
                                    "Сначала сгенерируйте варианты.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт теста", f"{self.generator.name}.docx", "Word (*.docx)"
        )
        if not path:
            return
        try:
            export_test_to_docx(
                self.variants, path,
                title=self.generator.name,
                with_answers=self.show_answers_chk.isChecked(),
            )
            QMessageBox.information(self, "Экспорт", "Готово.")
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Ошибка: {e}")
