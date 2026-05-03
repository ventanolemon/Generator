"""
TestExportView — представление теста.

Тест — это собранный список заданий с вариантами. Кнопка генерации
создаёт N вариантов, каждый — большой StaticTask. Кнопка экспорта
сохраняет все варианты в один docx.
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSpinBox, QCheckBox,
    QLabel, QFileDialog, QMessageBox, QScrollArea, QTabWidget
)

from core import Capability, StaticTask, TaskGenerator
from ui.utils import render_blocks, clear_layout
from ui.exporter import export_test_to_docx


class TestExportView(QWidget):
    """Тест: N вариантов, каждый — StaticTask из TestGenerator."""

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        if Capability.EXPORTABLE not in generator.capabilities:
            raise ValueError(
                f"TestExportView требует EXPORTABLE, у {generator.name!r} его нет."
            )
        self.generator = generator
        self.variants: list[StaticTask] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel(self.generator.name, self)
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Вариантов:", self))
        self.variants_spin = QSpinBox(self)
        self.variants_spin.setRange(1, 50)
        self.variants_spin.setValue(4)
        ctrl.addWidget(self.variants_spin)

        self.gen_btn = QPushButton("Сгенерировать варианты", self)
        self.export_btn = QPushButton("Экспорт в Word", self)
        self.show_answers_chk = QCheckBox("С ответами", self)
        ctrl.addWidget(self.gen_btn)
        ctrl.addWidget(self.export_btn)
        ctrl.addWidget(self.show_answers_chk)
        ctrl.addStretch()
        root.addLayout(ctrl)

        # Превью вариантов в табах
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, stretch=1)

        self.gen_btn.clicked.connect(self._on_generate)
        self.export_btn.clicked.connect(self._on_export)
        self.show_answers_chk.stateChanged.connect(self._refresh_tabs)

    def _on_generate(self) -> None:
        n = self.variants_spin.value()
        self.variants = []
        self.tabs.clear()
        for i in range(n):
            task = self.generator.generate()
            if isinstance(task, StaticTask):
                self.variants.append(task)
        self._refresh_tabs()

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
