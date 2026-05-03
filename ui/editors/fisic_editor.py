"""
FisicEditor — конструктор физической задачи.

Структура generation_parametrs:
  {
    "condition": "Текст условия с маркерами #var#",
    "result_letter": "F",
    "formula": "m * a",
    "dimension": "Н",
    "variables": {
      "m": {"min": 1.0, "max": 100.0, "forbidden": [], "dimension": "кг"},
      "a": {"min": 1.0, "max": 5.0,   "forbidden": [], "dimension": "м/c^2"}
    }
  }

При наборе текста условия автоматически обновляется список переменных:
парсятся все вхождения вида #имя_переменной# и для каждой создаётся строка
в таблице. Если переменная пропадает из условия, её строка удаляется.
"""

from __future__ import annotations
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLineEdit, QLabel,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
)

from .base import PartitionEditor


_VAR_PATTERN = re.compile(r"#([A-Za-zА-Яа-я_][\w]*)#")


class FisicEditor(PartitionEditor):
    """Конструктор задачи по физике (constracted=1)."""

    CONSTRACTED = 1

    # Колонки таблицы переменных
    COL_NAME, COL_MIN, COL_MAX, COL_FORBIDDEN, COL_DIM = range(5)

    def __init__(self, repository, subject_id, partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        # Запоминаем введённые пользователем значения, чтобы не терять
        # их при пересборе таблицы из текста условия
        self._var_state: dict[str, dict] = {}
        self._build_ui()
        if self.is_edit_mode:
            self.load_existing()
        else:
            self.setWindowTitle("Создание физической задачи")

    # --- UI ---

    def _build_ui(self) -> None:
        self.setMinimumSize(720, 600)
        self.setWindowTitle(
            "Редактирование физической задачи" if self.is_edit_mode
            else "Создание физической задачи"
        )

        root = QVBoxLayout(self)

        # Название раздела
        root.addWidget(QLabel("Название задачи:"))
        self.name_edit = QLineEdit(self)
        root.addWidget(self.name_edit)

        # Текст условия
        root.addWidget(QLabel(
            "Условие задачи (используйте #имя# для подстановки переменных):"
        ))
        self.condition_edit = QPlainTextEdit(self)
        self.condition_edit.setMinimumHeight(80)
        self.condition_edit.setMaximumHeight(140)
        root.addWidget(self.condition_edit)

        # Параметры результата (буква, формула, размерность)
        result_grid = QGridLayout()
        result_grid.addWidget(QLabel("Искомая величина:"), 0, 0)
        self.result_letter_edit = QLineEdit(self)
        self.result_letter_edit.setMaximumWidth(60)
        result_grid.addWidget(self.result_letter_edit, 0, 1)

        result_grid.addWidget(QLabel("Формула:"), 0, 2)
        self.formula_edit = QLineEdit(self)
        result_grid.addWidget(self.formula_edit, 0, 3)

        result_grid.addWidget(QLabel("Размерность:"), 0, 4)
        self.dimension_edit = QLineEdit(self)
        self.dimension_edit.setMaximumWidth(80)
        result_grid.addWidget(self.dimension_edit, 0, 5)
        root.addLayout(result_grid)

        # Таблица переменных
        root.addWidget(QLabel("Переменные:"))
        self.vars_table = QTableWidget(0, 5, self)
        self.vars_table.setHorizontalHeaderLabels([
            "Переменная", "Минимум", "Максимум", "Запрещённые", "Размерность"
        ])
        hdr = self.vars_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.vars_table.verticalHeader().setVisible(False)
        root.addWidget(self.vars_table, stretch=1)

        # Save / Cancel
        btns = QHBoxLayout()
        save_btn = QPushButton("Сохранить", self)
        cancel_btn = QPushButton("Отмена", self)
        btns.addStretch()
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        # Сигналы
        self.condition_edit.textChanged.connect(self._refresh_variables)
        self.vars_table.itemChanged.connect(self._on_table_changed)
        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self._on_cancel)

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # --- Парсинг условия → таблица переменных ---

    def _refresh_variables(self) -> None:
        """
        Сканирует условие, обновляет таблицу. Существующие значения сохраняются
        в self._var_state и переносятся, если переменная остаётся.
        """
        # Сначала запомним текущее состояние таблицы
        self._snapshot_table_into_state()

        text = self.condition_edit.toPlainText()
        # Сохраняем порядок появления + уникальность
        seen: list[str] = []
        for m in _VAR_PATTERN.finditer(text):
            v = m.group(1)
            if v not in seen:
                seen.append(v)

        self.vars_table.blockSignals(True)
        self.vars_table.setRowCount(0)
        for var_name in seen:
            state = self._var_state.get(var_name, {})
            self._add_var_row(
                var_name,
                str(state.get("min", "")),
                str(state.get("max", "")),
                ", ".join(str(x) for x in state.get("forbidden", []))
                    if state.get("forbidden") else "",
                state.get("dimension", ""),
            )
        self.vars_table.blockSignals(False)

    def _add_var_row(self, name: str, vmin: str, vmax: str,
                     forbidden: str, dim: str) -> None:
        row = self.vars_table.rowCount()
        self.vars_table.insertRow(row)

        # Имя — нередактируемое
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.vars_table.setItem(row, self.COL_NAME, name_item)

        for col, val in (
            (self.COL_MIN, vmin),
            (self.COL_MAX, vmax),
            (self.COL_FORBIDDEN, forbidden),
            (self.COL_DIM, dim),
        ):
            self.vars_table.setItem(row, col, QTableWidgetItem(val))

    def _on_table_changed(self, _item) -> None:
        # Просто обновим снимок состояния
        self._snapshot_table_into_state()

    def _snapshot_table_into_state(self) -> None:
        """Скопировать значения из таблицы в self._var_state."""
        for row in range(self.vars_table.rowCount()):
            name_item = self.vars_table.item(row, self.COL_NAME)
            if name_item is None:
                continue
            name = name_item.text()
            self._var_state[name] = {
                "min": self._cell_text(row, self.COL_MIN),
                "max": self._cell_text(row, self.COL_MAX),
                "forbidden": self._parse_forbidden(
                    self._cell_text(row, self.COL_FORBIDDEN)
                ),
                "dimension": self._cell_text(row, self.COL_DIM),
            }

    def _cell_text(self, row: int, col: int) -> str:
        item = self.vars_table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _parse_forbidden(raw: str) -> list[float]:
        """'1, 2.5, -3' → [1.0, 2.5, -3.0]."""
        if not raw.strip():
            return []
        out = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(float(part))
            except ValueError:
                continue
        return out

    # --- Загрузка существующей задачи ---

    def load_existing(self) -> None:
        part = self.repo.get_partition(self.partition_id)
        if part is None:
            self._show_error(f"Раздел {self.partition_id} не найден.")
            return
        self.name_edit.setText(part.name)

        cfg = part.generation_params
        if "raw" in cfg:
            # сырая строка — попробуем распарсить как JSON
            import json
            try:
                cfg = json.loads(cfg["raw"])
            except json.JSONDecodeError:
                cfg = {}

        self.condition_edit.setPlainText(cfg.get("condition", ""))
        self.result_letter_edit.setText(cfg.get("result_letter", ""))
        self.formula_edit.setText(cfg.get("formula", ""))
        self.dimension_edit.setText(cfg.get("dimension", ""))

        # Заполняем var_state, прежде чем _refresh_variables построит таблицу
        for name, var in (cfg.get("variables") or {}).items():
            self._var_state[name] = {
                "min": var.get("min", ""),
                "max": var.get("max", ""),
                "forbidden": var.get("forbidden", []) or [],
                "dimension": var.get("dimension", ""),
            }
        self._refresh_variables()

    # --- Сборка payload ---

    def collect_payload(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Введите название задачи.")

        condition = self.condition_edit.toPlainText().strip()
        if not condition:
            raise ValueError("Введите текст условия.")

        formula = self.formula_edit.text().strip()
        if not formula:
            raise ValueError("Введите формулу.")

        result_letter = self.result_letter_edit.text().strip()
        if not result_letter:
            raise ValueError("Укажите искомую величину.")

        dimension = self.dimension_edit.text().strip()

        # Собираем переменные из таблицы
        self._snapshot_table_into_state()
        var_names_in_condition = list(set(_VAR_PATTERN.findall(condition)))

        variables = {}
        for name in var_names_in_condition:
            st = self._var_state.get(name, {})
            try:
                vmin = float(st.get("min", "") or 0)
                vmax = float(st.get("max", "") or 0)
            except ValueError:
                raise ValueError(
                    f"Переменная {name!r}: минимум и максимум должны быть числами."
                )
            if vmax < vmin:
                raise ValueError(
                    f"Переменная {name!r}: максимум меньше минимума."
                )
            variables[name] = {
                "min": vmin,
                "max": vmax,
                "forbidden": st.get("forbidden", []),
                "dimension": st.get("dimension", ""),
            }

        if not variables:
            raise ValueError(
                "В условии нет ни одной переменной (формат: #имя#)."
            )

        payload = {
            "condition": condition,
            "result_letter": result_letter,
            "formula": formula,
            "dimension": dimension,
            "variables": variables,
        }
        return name, self.CONSTRACTED, payload
