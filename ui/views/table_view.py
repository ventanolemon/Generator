"""
TableTaskView — табличное представление: накапливает N сгенерированных
заданий, показывает условия и ответы рядом, можно удалять отдельные строки
и экспортировать всё в Word.
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox
)

from core import Capability, StaticTask, TaskGenerator
from ui.utils import blocks_to_plain
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
        self.tasks: list[StaticTask] = []   # параллельно строкам таблицы

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
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        # Вертикальная высота строк по контенту
        self.table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        root.addWidget(self.table, stretch=1)

        self.gen_btn.clicked.connect(self._on_generate)
        self.export_btn.clicked.connect(self._on_export)
        self.show_answers_chk.stateChanged.connect(self._refresh_answers_column)
        self.table.cellClicked.connect(self._on_cell_clicked)

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

        # Условие — текстовое представление блоков
        cond_item = QTableWidgetItem(blocks_to_plain(task.statement))
        cond_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.table.setItem(row, 1, cond_item)

        # Ответ
        self.table.setItem(row, 2, self._make_answer_item(task))

        # Кнопка удаления
        del_btn = QPushButton("✕", self)
        del_btn.clicked.connect(lambda _, t=task: self._delete_task(t))
        self.table.setCellWidget(row, 3, del_btn)

        self.table.resizeRowsToContents()

    def _make_answer_item(self, task: StaticTask) -> QTableWidgetItem:
        text = blocks_to_plain(task.answer)
        if self.show_answers_chk.isChecked():
            item = QTableWidgetItem(text)
        else:
            item = QTableWidgetItem("Нажмите для просмотра")
            item.setData(Qt.ItemDataRole.UserRole, text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        return item

    def _refresh_answers_column(self) -> None:
        for row, task in enumerate(self.tasks):
            self.table.setItem(row, 2, self._make_answer_item(task))
        self.table.resizeRowsToContents()

    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col != 2 or self.show_answers_chk.isChecked():
            return
        item = self.table.item(row, col)
        if item is None:
            return
        hidden = item.data(Qt.ItemDataRole.UserRole)
        if hidden:
            QMessageBox.information(self, "Ответ", hidden)

    def _delete_task(self, task: StaticTask) -> None:
        try:
            idx = self.tasks.index(task)
        except ValueError:
            return
        self.tasks.pop(idx)
        self.table.removeRow(idx)
        # Перенумеровать
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
