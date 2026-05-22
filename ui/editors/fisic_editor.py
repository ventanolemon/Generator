"""
FisicEditor — конструктор физической задачи.

Структура generation_parametrs:

  {
    "condition": "Текст условия с маркерами #var#",
    "result_letter": "F",
    "formula": "m * a",                                  // поддерживает ^, √, π
    "dimension": "Н",
    "result": {                                          // опционально
        "kind": "natural",                               // natural | integer | real
        "min": 1, "max": 1000
    },
    "variables": {
      "m": {
          "min": 1, "max": 100,
          "kind": "natural",                             // natural | integer | real | auto
          "step": 1,
          "forbidden": [0],
          "dimension": "кг"
      }
    }
  }

При наборе текста условия автоматически обновляется список переменных:
парсятся все вхождения #имя# и для каждой создаётся строка в таблице.
Если переменная пропадает из условия, её строка удаляется.
"""

from __future__ import annotations
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLineEdit, QLabel,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QGroupBox,
)

from .base import PartitionEditor


_VAR_PATTERN = re.compile(r"#([A-Za-zА-Яа-я_][\w]*)#")

VAR_KINDS = ["auto", "natural", "integer", "real"]
RESULT_KINDS = ["real", "natural", "integer"]


class FisicEditor(PartitionEditor):
    """Конструктор задачи по физике (constracted=1)."""

    CONSTRACTED = 1

    # Колонки таблицы переменных
    COL_NAME, COL_MIN, COL_MAX, COL_KIND, COL_STEP, COL_FORBIDDEN, COL_DIM = range(7)
    COLUMN_LABELS = [
        "Переменная", "Минимум", "Максимум", "Тип", "Шаг",
        "Запрещённые", "Размерность",
    ]

    def __init__(self, repository, subject_id, partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        # Запоминаем введённые пользователем значения, чтобы не терять
        # их при пересборе таблицы из текста условия
        self._var_state: dict[str, dict] = {}
        self._build_ui()
        if self.is_edit_mode:
            self.load_existing()

    # --- UI ---

    def _build_ui(self) -> None:
        self.setMinimumSize(900, 700)
        self.setWindowTitle(
            "Редактирование физической задачи" if self.is_edit_mode
            else "Создание физической задачи"
        )

        root = QVBoxLayout(self)

        # ---- Название ----
        root.addWidget(QLabel("Название задачи:"))
        self.name_edit = QLineEdit(self)
        root.addWidget(self.name_edit)

        # ---- Условие ----
        root.addWidget(QLabel(
            "Условие задачи (используйте #имя# для подстановки переменных):"
        ))
        self.condition_edit = QPlainTextEdit(self)
        self.condition_edit.setMinimumHeight(80)
        self.condition_edit.setMaximumHeight(140)
        root.addWidget(self.condition_edit)

        # ---- Параметры результата (буква + формула + размерность) ----
        result_grid = QGridLayout()
        result_grid.addWidget(QLabel("Искомая величина:"), 0, 0)
        self.result_letter_edit = QLineEdit(self)
        self.result_letter_edit.setMaximumWidth(80)
        result_grid.addWidget(self.result_letter_edit, 0, 1)

        result_grid.addWidget(QLabel("Формула:"), 0, 2)
        self.formula_edit = QLineEdit(self)
        self.formula_edit.setPlaceholderText("например: m * a, √(a^2 + b^2), 2*π*r")
        result_grid.addWidget(self.formula_edit, 0, 3)

        result_grid.addWidget(QLabel("Размерность:"), 0, 4)
        self.dimension_edit = QLineEdit(self)
        self.dimension_edit.setMaximumWidth(80)
        result_grid.addWidget(self.dimension_edit, 0, 5)
        root.addLayout(result_grid)

        # ---- Ограничения на результат ----
        result_box = QGroupBox("Ограничения на результат (необязательно)", self)
        result_box_layout = QGridLayout(result_box)

        result_box_layout.addWidget(QLabel("Тип:"), 0, 0)
        self.result_kind_combo = QComboBox(self)
        self.result_kind_combo.addItems(RESULT_KINDS)
        self.result_kind_combo.setToolTip(
            "real — без ограничений\n"
            "natural — результат должен быть натуральным числом ≥ 1\n"
            "integer — результат должен быть целым"
        )
        result_box_layout.addWidget(self.result_kind_combo, 0, 1)

        result_box_layout.addWidget(QLabel("Min:"), 0, 2)
        self.result_min_edit = QLineEdit(self)
        self.result_min_edit.setMaximumWidth(120)
        self.result_min_edit.setPlaceholderText("необязательно")
        result_box_layout.addWidget(self.result_min_edit, 0, 3)

        result_box_layout.addWidget(QLabel("Max:"), 0, 4)
        self.result_max_edit = QLineEdit(self)
        self.result_max_edit.setMaximumWidth(120)
        self.result_max_edit.setPlaceholderText("необязательно")
        result_box_layout.addWidget(self.result_max_edit, 0, 5)

        root.addWidget(result_box)

        # ---- Таблица переменных ----
        root.addWidget(QLabel(
            "Переменные (Min/Max могут быть формулами: 10^3, 2*π, sqrt(2)):"
        ))
        self.vars_table = QTableWidget(0, len(self.COLUMN_LABELS), self)
        self.vars_table.setHorizontalHeaderLabels(self.COLUMN_LABELS)
        hdr = self.vars_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_KIND, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_STEP, QHeaderView.ResizeMode.ResizeToContents)
        self.vars_table.verticalHeader().setVisible(False)
        root.addWidget(self.vars_table, stretch=1)

        # ---- Save / Cancel ----
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

    # ---- Парсинг условия → таблица переменных ----

    def _refresh_variables(self) -> None:
        """Сканирует условие, обновляет таблицу. Сохранённые значения не теряются."""
        self._snapshot_table_into_state()

        text = self.condition_edit.toPlainText()
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
                state.get("kind", "auto"),
                str(state.get("step", "")),
                ", ".join(str(x) for x in state.get("forbidden", []))
                    if state.get("forbidden") else "",
                state.get("dimension", ""),
            )
        self.vars_table.blockSignals(False)

    def _add_var_row(self, name, vmin, vmax, kind, step, forbidden, dim) -> None:
        row = self.vars_table.rowCount()
        self.vars_table.insertRow(row)

        # Имя — нередактируемое
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.vars_table.setItem(row, self.COL_NAME, name_item)

        # Простые редактируемые ячейки
        self.vars_table.setItem(row, self.COL_MIN, QTableWidgetItem(vmin))
        self.vars_table.setItem(row, self.COL_MAX, QTableWidgetItem(vmax))
        self.vars_table.setItem(row, self.COL_STEP, QTableWidgetItem(step))
        self.vars_table.setItem(row, self.COL_FORBIDDEN, QTableWidgetItem(forbidden))
        self.vars_table.setItem(row, self.COL_DIM, QTableWidgetItem(dim))

        # Combo для kind
        combo = QComboBox(self.vars_table)
        combo.addItems(VAR_KINDS)
        if kind in VAR_KINDS:
            combo.setCurrentText(kind)
        combo.currentIndexChanged.connect(self._on_table_changed)
        self.vars_table.setCellWidget(row, self.COL_KIND, combo)

    def _on_table_changed(self, *_args) -> None:
        self._snapshot_table_into_state()

    def _snapshot_table_into_state(self) -> None:
        """Скопировать значения из таблицы в self._var_state."""
        for row in range(self.vars_table.rowCount()):
            name_item = self.vars_table.item(row, self.COL_NAME)
            if name_item is None:
                continue
            name = name_item.text()
            kind_combo = self.vars_table.cellWidget(row, self.COL_KIND)
            kind = kind_combo.currentText() if kind_combo else "auto"
            self._var_state[name] = {
                "min": self._cell_text(row, self.COL_MIN),
                "max": self._cell_text(row, self.COL_MAX),
                "kind": kind,
                "step": self._cell_text(row, self.COL_STEP),
                "forbidden": self._parse_list(
                    self._cell_text(row, self.COL_FORBIDDEN)
                ),
                "dimension": self._cell_text(row, self.COL_DIM),
            }

    def _cell_text(self, row: int, col: int) -> str:
        item = self.vars_table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _parse_list(raw: str) -> list:
        """'1, 2.5, -3' → ['1', '2.5', '-3'] (как строки, парсинг — на стороне backend)."""
        if not raw.strip():
            return []
        return [p.strip() for p in raw.split(",") if p.strip()]

    # ---- Загрузка существующей задачи ----

    def load_existing(self) -> None:
        part = self.repo.get_partition(self.partition_id)
        if part is None:
            self._show_error(f"Раздел {self.partition_id} не найден.")
            return
        self.name_edit.setText(part.name)

        cfg = part.generation_params
        if "raw" in cfg:
            import json
            try:
                cfg = json.loads(cfg["raw"])
            except json.JSONDecodeError:
                cfg = {}

        self.condition_edit.setPlainText(cfg.get("condition", ""))
        self.result_letter_edit.setText(cfg.get("result_letter", ""))
        self.formula_edit.setText(cfg.get("formula", ""))
        self.dimension_edit.setText(cfg.get("dimension", ""))

        # result constraint
        result_cfg = cfg.get("result") or {}
        kind = result_cfg.get("kind", "real")
        if kind in RESULT_KINDS:
            self.result_kind_combo.setCurrentText(kind)
        if result_cfg.get("min") is not None:
            self.result_min_edit.setText(str(result_cfg["min"]))
        if result_cfg.get("max") is not None:
            self.result_max_edit.setText(str(result_cfg["max"]))

        # variables
        for name, var in (cfg.get("variables") or {}).items():
            forbidden = var.get("forbidden", []) or []
            self._var_state[name] = {
                "min": var.get("min", ""),
                "max": var.get("max", ""),
                "kind": var.get("kind", "auto"),
                "step": var.get("step", ""),
                "forbidden": [str(x) for x in forbidden]
                    if isinstance(forbidden, list) else [str(forbidden)],
                "dimension": var.get("dimension", ""),
            }
        self._refresh_variables()

    # ---- Сборка payload ----

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

        # Валидируем формулу
        try:
            from exercises.fisic.expression import parse_formula
            parse_formula(formula)
        except Exception as e:
            raise ValueError(f"Ошибка в формуле: {e}")

        dimension = self.dimension_edit.text().strip()

        # Собираем переменные
        self._snapshot_table_into_state()
        var_names_in_condition = list(set(_VAR_PATTERN.findall(condition)))

        if not var_names_in_condition:
            raise ValueError(
                "В условии нет ни одной переменной. Используйте формат #имя#."
            )

        variables: dict[str, dict] = {}
        for vname in var_names_in_condition:
            st = self._var_state.get(vname, {})
            vmin_raw = st.get("min", "")
            vmax_raw = st.get("max", "")
            if not vmin_raw or not vmax_raw:
                raise ValueError(
                    f"Переменная {vname!r}: укажите минимум и максимум."
                )

            entry: dict = {
                "min":       vmin_raw,
                "max":       vmax_raw,
                "kind":      st.get("kind", "auto"),
                "dimension": st.get("dimension", ""),
            }
            step = st.get("step", "")
            if step:
                entry["step"] = step
            forbidden = st.get("forbidden", [])
            if forbidden:
                entry["forbidden"] = forbidden
            variables[vname] = entry

        # Валидируем, что все переменные формулы есть в таблице
        from exercises.fisic.expression import extract_variable_names
        try:
            used_in_formula = extract_variable_names(formula)
        except Exception as e:
            raise ValueError(f"Ошибка в формуле: {e}")
        missing = used_in_formula - set(variables.keys())
        if missing:
            raise ValueError(
                f"В формуле использованы переменные {sorted(missing)}, "
                "но они отсутствуют в условии (#имя#)."
            )

        # Result constraint
        result_kind = self.result_kind_combo.currentText()
        result_section: dict = {"kind": result_kind}
        result_min = self.result_min_edit.text().strip()
        result_max = self.result_max_edit.text().strip()
        if result_min:
            result_section["min"] = result_min
        if result_max:
            result_section["max"] = result_max

        payload: dict = {
            "condition": condition,
            "result_letter": result_letter,
            "formula": formula,
            "dimension": dimension,
            "variables": variables,
        }
        # Добавляем result только если он не дефолтный
        if result_kind != "real" or result_min or result_max:
            payload["result"] = result_section

        return name, self.CONSTRACTED, payload
