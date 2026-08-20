"""
TableTaskView — табличное представление: накапливает N сгенерированных
заданий, показывает условия и ответы рядом, можно удалять отдельные строки
и экспортировать всё в Word.

Содержимое ячеек строится через render_qt каждого блока — поэтому формулы
показываются как картинки, текст как текст, а изображения как изображения.

Хром (заголовок + строка кнопок) — из BaseTaskView (контракт K4);
центральная зона заменена таблицей.
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QCheckBox, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QSizePolicy, QSpinBox
)

from core import Capability, StaticTask
from ui.utils import render_blocks
from ui.exporter import export_tasks_to_docx
from ui.variants import generate_variants, was_interrupted
from ui.widgets.answer_placement import AnswerPlacementBox
from .base_view import BaseTaskView

#: Верхняя граница счётчика. Не «сколько выдержит система», а сколько
#: осмысленно раздать: больше полусотни вариантов одного задания за раз
#: не печатают, а промах в поле ввода на порядок стоит минут ожидания.
MAX_AT_ONCE = 50


class TableTaskView(BaseTaskView):
    """
    Табличный вид: каждая строка — одно задание.
    Колонки: №, Условие, Ответ, Удалить.

    Принимает любой STATIC-генератор. В частности, GroupGenerator
    (тогда задания в таблице будут разных типов).
    """

    REQUIRED_CAPABILITY = Capability.STATIC

    def _init_state(self) -> None:
        self.tasks: list[StaticTask] = []

    def build_controls(self, row: QHBoxLayout) -> None:
        self.gen_btn = QPushButton("Сгенерировать", self)

        # Сколько вариантов добавить за раз. До этого кнопка давала РОВНО
        # ОДНО задание, и лист на тридцать вариантов собирался тридцатью
        # кликами — при том что на вебе то же самое делается числом в
        # поле. Два клиента расходились в поведении молча.
        row.addWidget(self.gen_btn)
        self.count_spin = QSpinBox(self)
        self.count_spin.setRange(1, MAX_AT_ONCE)
        self.count_spin.setValue(1)
        self.count_spin.setToolTip(
            "Сколько вариантов добавить за одно нажатие. Уже набранные "
            "строки остаются: таблица накапливается, а не замещается."
        )
        self.count_spin.setSuffix(" шт.")
        row.addWidget(self.count_spin)

        self.export_btn = QPushButton("Экспорт в Word", self)
        self.show_answers_chk = QCheckBox("Показывать ответы", self)
        row.addWidget(self.export_btn)
        # Галочка осталась — она про ЭКРАН, про колонку «Ответ» в
        # таблице. Список рядом — про ФАЙЛ. Это разные вопросы, и
        # связывать их было ошибкой: преподаватель, скрывший ответы на
        # экране от заглядывающего студента, получал лист без ключа.
        row.addWidget(self.show_answers_chk)
        self.placement_box = AnswerPlacementBox(self)
        row.addWidget(self.placement_box)
        self.count_label = QLabel("", self)
        self.count_label.setProperty("class", "muted")
        row.addWidget(self.count_label)
        row.addStretch()

        self.gen_btn.clicked.connect(self._on_generate)
        self.export_btn.clicked.connect(self._on_export)
        self.show_answers_chk.stateChanged.connect(self._refresh_answers_column)
        self._update_count_label()

    def build_center(self, root: QVBoxLayout) -> None:
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

    def _on_generate(self) -> None:
        asked = self.count_spin.value()
        if asked == 1:
            # Один вариант — прежний путь, без окна хода и без разбора
            # прерывания: прерывать там нечего, а сообщение о том, что
            # генератор вернул не то, здесь конкретнее общего пропуска.
            task = self.generator.generate()
            if not isinstance(task, StaticTask):
                QMessageBox.warning(self, "Ошибка",
                                    f"Генератор вернул {type(task).__name__}.")
                return
            self._append_task(task)
            self._update_count_label()
            return

        produced = generate_variants(self, self.generator, asked)
        for task in produced:
            self._append_task(task)
        self._update_count_label()
        note = was_interrupted(asked, len(produced))
        if note:
            QMessageBox.information(self, "Генерация", note)
        elif not produced:
            QMessageBox.warning(
                self, "Ошибка",
                "Генератор не вернул ни одного задания нужного вида.")

    def _update_count_label(self) -> None:
        total = len(self.tasks)
        self.count_label.setText(f"в таблице: {total}" if total else "")

    def _append_task(self, task: StaticTask) -> None:
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
            widget.setProperty("class", "muted")
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
        self._update_count_label()

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
                                 answers=self.placement_box.placement())
            QMessageBox.information(self, "Экспорт", "Готово.")
        except Exception as e:
            QMessageBox.critical(self, "Экспорт", f"Ошибка: {e}")
