"""
TableTaskView — табличное представление: накапливает N сгенерированных
заданий, показывает условия и ответы рядом, можно удалять отдельные строки
и экспортировать всё в Word.

Содержимое ячеек строится через render_qt каждого блока — поэтому формулы
показываются как картинки, текст как текст, а изображения как изображения.
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QSizePolicy
)

from core import Capability, StaticTask, TaskGenerator
from ui.utils import render_blocks
from ui.exporter import export_tasks_to_docx


class TableTaskView(QWidget):
    """
    Табличный вид: каждая строка — одно задание.
    Колонки: №, Условие, Ответ, Удалить.

    Принимает любой STATIC-генератор. В частности, GroupGenerator
    (тогда задания в таблице будут разных типов).
    """

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        if Capability.STATIC not in generator.capabilities:
            raise ValueError(
                f"TableTaskView требует STATIC, у {generator.name!r} его нет."
            )

        self.generator = generator
        self.tasks: list[StaticTask] = []

        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel(self.generator.name, self)
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        btns = QHBoxLayout()
        self.gen_btn = QPushButton("Сгенерировать", self)
        self.export_btn = QPushButton("Экспорт в Word", self)
        self.show_answers_chk = QCheckBox("Показывать ответы", self)
        btns.addWidget(self.gen_btn)
        btns.addWidget(self.export_btn)
        btns.addWidget(self.show_answers_chk)
        btns.addStretch()
        root.addLayout(btns)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["№", "Условие", "Ответ", ""])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(3, 60)
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        # Сами ячейки нельзя редактировать
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, stretch=1)

        self.gen_btn.clicked.connect(self._on_generate)
        self.export_btn.clicked.connect(self._on_export)
        self.show_answers_chk.stateChanged.connect(self._refresh_answers_column)

    def _on_generate(self) -> None:
        task = self.generator.generate()
        if not isinstance(task, StaticTask):
            QMessageBox.warning(self, "Ошибка",
                                f"Генератор вернул {type(task).__name__}.")
            return
        self.tasks.append(task)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))

        # Условие — рендерим через render_qt каждого блока в один виджет
        cond_widget = self._build_cell_widget(task.statement)
        self.table.setCellWidget(row, 1, cond_widget)

        # Ответ — отдельный виджет, видимость зависит от чекбокса
        self._set_answer_cell(row, task)

        # Кнопка удаления
        del_btn = QPushButton("✕", self)
        del_btn.clicked.connect(lambda _, t=task: self._delete_task(t))
        self.table.setCellWidget(row, 3, del_btn)

        self.table.resizeRowsToContents()

    def _build_cell_widget(self, blocks) -> QWidget:
        """
        Сделать виджет для ячейки таблицы из списка блоков.
        Каждый блок рисуется через свой render_qt — формулы как картинки,
        текст как текст, изображения как изображения.
        """
        widget = render_blocks(blocks, self.table)
        widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        return widget

    def _set_answer_cell(self, row: int, task: StaticTask) -> None:
        """Поставить виджет ответа в ячейку, учитывая режим показа."""
        if self.show_answers_chk.isChecked():
            widget = self._build_cell_widget(task.answer)
        else:
            widget = QLabel("Нажмите, чтобы показать", self.table)
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setStyleSheet("color: #888; font-style: italic;")
            # Делаем clickable: при клике — показать ответ для этой строки
            def show_for_row(event, _t=task, _r=row):
                self._show_answer_popup(_t)
            widget.mousePressEvent = show_for_row
        self.table.setCellWidget(row, 2, widget)

    def _show_answer_popup(self, task: StaticTask) -> None:
        """
        Показать ответ во всплывающем окне (если в таблице ответы скрыты).
        Делаем простое модальное окно с render_blocks ответа.
        """
        from PyQt6.QtWidgets import QDialog
        dlg = QDialog(self)
        dlg.setWindowTitle("Ответ")
        layout = QVBoxLayout(dlg)
        layout.addWidget(render_blocks(task.answer, dlg))
        close_btn = QPushButton("Закрыть", dlg)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)
        dlg.resize(500, 200)
        dlg.exec()

    def _refresh_answers_column(self) -> None:
        for row, task in enumerate(self.tasks):
            self._set_answer_cell(row, task)
        self.table.resizeRowsToContents()

    def _delete_task(self, task: StaticTask) -> None:
        try:
            idx = self.tasks.index(task)
        except ValueError:
            return
        self.tasks.pop(idx)
        self.table.removeRow(idx)
        for r in range(self.table.rowCount()):
            self.table.setItem(r, 0, QTableWidgetItem(str(r + 1)))

    def _on_export(self) -> None:
        if not self.tasks:
            QMessageBox.information(self, "Экспорт", "Нет заданий для экспорта.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт в Word", f"{self.generator.name}.docx", "Word (*.docx)"
        )
        if not path:
            return
        try:
            export_tasks_to_docx(self.tasks, path,
                                 title=self.generator.name,
                                 with_answers=self.show_answers_chk.isChecked())
            QMessageBox.information(self, "Экспорт", "Готово.")
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Ошибка: {e}")
