"""
GroupEditor — редактор раздела-группы.

В группу можно положить любой раздел того же предмета, кроме других групп
(чтобы не плодить вложенность). Дочерние разделы выбираются чекбоксами.

Сохраняется в Partitions с constracted=2 и generation_parametrs =
[{"task_id": N, "task_name": "...", "constracted": K}, ...] —
тот же формат, что был в старом GroupAdder, чтобы не ломать совместимость.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QListWidget, QListWidgetItem
)

from core import Capability, GeneratorRegistry
from .base import PartitionEditor


class GroupEditor(PartitionEditor):
    """
    Создание/редактирование раздела-группы.

    Аргументы конструктора:
      registry — нужен только для проверки GROUPABLE на этапе сохранения
                 (на самом деле фильтруем чекбоксы по списку из БД,
                  это просто страховка).
    """

    CONSTRACTED = 2

    def __init__(self, repository, subject_id, registry: GeneratorRegistry,
                 partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        self.registry = registry
        self._candidate_partitions: list = []  # из БД, без других групп

        self._build_ui()
        self._load_candidates()
        if self.is_edit_mode:
            self.load_existing()
        else:
            self.setWindowTitle("Создание группы")

    # --- UI ---

    def _build_ui(self) -> None:
        self.setMinimumSize(420, 480)
        self.setWindowTitle("Редактирование группы" if self.is_edit_mode
                            else "Создание группы")

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Название группы:"))
        self.name_edit = QLineEdit(self)
        root.addWidget(self.name_edit)

        root.addWidget(QLabel("Содержит разделы:"))
        self.list_widget = QListWidget(self)
        root.addWidget(self.list_widget, stretch=1)

        btns = QHBoxLayout()
        save_btn = QPushButton("Сохранить", self)
        cancel_btn = QPushButton("Отмена", self)
        btns.addStretch()
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self._on_cancel)

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # --- Загрузка кандидатов ---

    def _load_candidates(self) -> None:
        """Все разделы предмета, кроме других групп (constracted != 2)."""
        all_parts = self.repo.list_partitions_for_subject(self.subject_id)
        self._candidate_partitions = [
            p for p in all_parts
            if p.constracted != self.CONSTRACTED   # без вложенных групп
            and p.id != self.partition_id          # не себя самого при редактировании
        ]
        self.list_widget.clear()
        for part in self._candidate_partitions:
            item = QListWidgetItem(part.name)
            item.setData(Qt.ItemDataRole.UserRole, part.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            # Подсветка интерактивных, чтобы пользователь понимал, что они
            # будут отфильтрованы фильтром GROUPABLE
            if self.registry.has(part.id):
                gen = None
                try:
                    gen = self.registry.get(part.id, part.generation_params)
                except Exception:
                    pass
                if gen and Capability.GROUPABLE not in gen.capabilities:
                    item.setForeground(Qt.GlobalColor.gray)
                    item.setToolTip(
                        "Этот раздел нельзя положить в группу "
                        "(не помечен как GROUPABLE — например, тренажёр)."
                    )
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.list_widget.addItem(item)

    # --- Загрузка существующей группы при редактировании ---

    def load_existing(self) -> None:
        part = self.repo.get_partition(self.partition_id)
        if part is None:
            self._show_error(f"Группа {self.partition_id} не найдена.")
            return
        self.name_edit.setText(part.name)

        # generation_params: либо {"data": [...]}, либо просто список (нормализован репозиторием в {"data": ...})
        items = part.generation_params.get("data", part.generation_params) \
            if isinstance(part.generation_params, dict) else part.generation_params
        if not isinstance(items, list):
            items = []

        # Выписываем нужные task_id
        wanted_ids = set()
        for it in items:
            if isinstance(it, dict) and "task_id" in it:
                wanted_ids.add(int(it["task_id"]))
            elif isinstance(it, int):
                wanted_ids.add(it)

        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            pid = it.data(Qt.ItemDataRole.UserRole)
            if pid in wanted_ids and (it.flags() & Qt.ItemFlag.ItemIsUserCheckable):
                it.setCheckState(Qt.CheckState.Checked)

    # --- Сборка payload ---

    def collect_payload(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Введите название группы.")

        chosen: list[dict] = []
        # Маппинг id → объект Partition
        part_by_id = {p.id: p for p in self._candidate_partitions}

        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.checkState() != Qt.CheckState.Checked:
                continue
            pid = it.data(Qt.ItemDataRole.UserRole)
            part = part_by_id.get(pid)
            if part is None:
                continue
            chosen.append({
                "task_id": part.id,
                "task_name": part.name,
                "constracted": part.constracted,
            })

        if not chosen:
            raise ValueError("Выберите хотя бы один раздел.")

        return name, self.CONSTRACTED, chosen
