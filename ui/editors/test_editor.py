"""
TestEditor — редактор раздела-теста.

Тест отличается от группы тремя вещами:
  * порядок заданий важен
  * у каждого задания указывается count (сколько раз генерировать)
  * могут включаться задания из РОДСТВЕННЫХ предметов (через pra_subject)

Сохраняется с constracted=3 и generation_parametrs =
  {"parent_subject": <id>, "data": [{"task_id": N, "task_name": "...", "task_cnt": K}, ...]}
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QWidget
)

from core import Capability, GeneratorRegistry
from .base import PartitionEditor


class TestEditor(PartitionEditor):
    """Создание/редактирование теста."""

    CONSTRACTED = 3

    def __init__(self, repository, subject_id, registry: GeneratorRegistry,
                 partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        self.registry = registry
        # Список (partition_id, partition_name) — то, что можно добавить в тест
        self._candidates: list[tuple[int, str]] = []

        self._build_ui()
        self._load_candidates()
        if self.is_edit_mode:
            self.load_existing()

    # --- UI ---

    def _build_ui(self) -> None:
        self.setMinimumSize(560, 540)
        self.setWindowTitle("Редактирование теста" if self.is_edit_mode
                            else "Создание теста")

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Название теста:"))
        self.name_edit = QLineEdit(self)
        root.addWidget(self.name_edit)

        # Выбор раздела + кнопка добавления
        add_row = QHBoxLayout()
        add_row.addWidget(QLabel("Тип задания:"))
        self.type_combo = QComboBox(self)
        add_row.addWidget(self.type_combo, stretch=1)
        self.add_btn = QPushButton("Добавить в тест", self)
        add_row.addWidget(self.add_btn)
        root.addLayout(add_row)

        # Таблица заданий
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Тип задания", "Кол-во", "Действия"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 140)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, stretch=1)

        # Save/Cancel
        btns = QHBoxLayout()
        save_btn = QPushButton("Сохранить", self)
        cancel_btn = QPushButton("Отмена", self)
        btns.addStretch()
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        self.add_btn.clicked.connect(self._on_add_row)
        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self._on_cancel)

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # --- Загрузка кандидатов ---

    def _load_candidates(self) -> None:
        """В тест можно добавлять разделы своего предмета и братских (pra_subject)."""
        # Свои разделы
        own = self.repo.list_partitions_for_subject(self.subject_id)

        # Родственные предметы — те, у которых pra_subject совпадает с моим subject_name
        all_subjects = self.repo.list_subjects()
        my_subject = next((s for s in all_subjects if s.id == self.subject_id), None)

        sibling_parts = []
        if my_subject:
            for s in all_subjects:
                if s.id != self.subject_id and s.parent_name == my_subject.name:
                    sibling_parts.extend(self.repo.list_partitions_for_subject(s.id))

        # Все вместе, без других тестов и без самого себя
        merged = own + sibling_parts
        self._candidates = [
            (p.id, p.name) for p in merged
            if p.constracted != self.CONSTRACTED
            and p.id != self.partition_id
        ]

        self.type_combo.clear()
        for pid, name in self._candidates:
            self.type_combo.addItem(name, userData=pid)

    # --- Работа с таблицей ---

    def _on_add_row(self) -> None:
        if self.type_combo.currentIndex() < 0:
            return
        pid = self.type_combo.currentData()
        name = self.type_combo.currentText()
        self._add_row(pid, name, count=1)

    def _add_row(self, partition_id: int, name: str, count: int) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Колонка 0 — название (нередактируемое), partition_id в UserRole
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setData(Qt.ItemDataRole.UserRole, partition_id)
        self.table.setItem(row, 0, item)

        # Колонка 1 — количество
        edit = QLineEdit(str(count), self)
        edit.setValidator(QIntValidator(1, 100))
        self.table.setCellWidget(row, 1, edit)

        # Колонка 2 — кнопки управления
        self.table.setCellWidget(row, 2, self._make_row_buttons(item))

    def _make_row_buttons(self, anchor_item: QTableWidgetItem) -> QWidget:
        """
        Кнопки ↑ ↓ × . Привязаны к ячейке через anchor_item, поэтому
        срабатывают на актуальной позиции, даже если строки переставлялись.
        """
        wrap = QWidget(self)
        h = QHBoxLayout(wrap)
        h.setContentsMargins(2, 2, 2, 2)

        up = QPushButton("↑", wrap)
        down = QPushButton("↓", wrap)
        delete = QPushButton("×", wrap)
        for b in (up, down, delete):
            b.setFixedWidth(34)

        up.clicked.connect(lambda: self._move(anchor_item, -1))
        down.clicked.connect(lambda: self._move(anchor_item, +1))
        delete.clicked.connect(lambda: self._remove(anchor_item))

        h.addWidget(up)
        h.addWidget(down)
        h.addWidget(delete)
        return wrap

    def _row_of(self, anchor_item: QTableWidgetItem) -> int:
        return self.table.row(anchor_item)

    def _move(self, anchor: QTableWidgetItem, delta: int) -> None:
        row = self._row_of(anchor)
        target = row + delta
        if target < 0 or target >= self.table.rowCount():
            return
        # Соберём текущее содержимое обеих строк и переставим
        rows_data = self._snapshot_rows()
        rows_data[row], rows_data[target] = rows_data[target], rows_data[row]
        self._restore_rows(rows_data)

    def _remove(self, anchor: QTableWidgetItem) -> None:
        self.table.removeRow(self._row_of(anchor))

    def _snapshot_rows(self) -> list[tuple[int, str, int]]:
        """Снимок содержимого таблицы: [(partition_id, name, count), ...]."""
        out = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, 0)
            edit = self.table.cellWidget(r, 1)
            count = int(edit.text() or "1") if edit else 1
            out.append((item.data(Qt.ItemDataRole.UserRole), item.text(), count))
        return out

    def _restore_rows(self, rows: list[tuple[int, str, int]]) -> None:
        self.table.setRowCount(0)
        for pid, name, count in rows:
            self._add_row(pid, name, count)

    # --- Загрузка существующего теста ---

    def load_existing(self) -> None:
        part = self.repo.get_partition(self.partition_id)
        if part is None:
            self._show_error(f"Тест {self.partition_id} не найден.")
            return
        self.name_edit.setText(part.name)

        items = part.generation_params.get("data", part.generation_params) \
            if isinstance(part.generation_params, dict) else part.generation_params
        if not isinstance(items, list):
            items = []

        for it in items:
            if not isinstance(it, dict):
                continue
            pid = it.get("task_id")
            if pid is None:
                continue
            # Восстановим имя из БД (на случай переименования)
            cpart = self.repo.get_partition(int(pid))
            name = cpart.name if cpart else it.get("task_name", "?")
            count = int(it.get("task_cnt", 1))
            self._add_row(int(pid), name, count)

    # --- Сборка payload ---

    def collect_payload(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Введите название теста.")
        if self.table.rowCount() == 0:
            raise ValueError("Добавьте хотя бы одно задание.")

        data = []
        for pid, pname, count in self._snapshot_rows():
            data.append({
                "task_id": pid,
                "task_name": pname,
                "task_cnt": count,
            })

        payload = {
            "parent_subject": self.subject_id,
            "data": data,
        }
        return name, self.CONSTRACTED, payload
