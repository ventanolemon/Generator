"""
ParamInspector — форма параметров выбранного узла. Поля генерируются из
PARAMS_SCHEMA узла. Значения пишутся обратно в GraphDocument; при изменении
параметров, влияющих на порты (var_dict.names, block_list.count), сцене
посылается сигнал на перестроение.
"""

from __future__ import annotations
import json
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QLineEdit, QSpinBox, QComboBox, QLabel, QPlainTextEdit,
    QPushButton,
)

from core.graph import GraphDocument


# Параметры, изменение которых меняет набор портов узла — по типам узлов.
# (var_dict.names и block_list.count влияют на порты; repeat.count — нет.)
_PORT_AFFECTING = {
    "var_dict": {"names"},
    "block_list": {"count"},
    "repeat": {"imports"},      # объявление внешних переменных меняет входы
    "map": {"imports"},
    "case": {"imports", "cases"},  # imports → входы; cases → число кнопок-ветвей
    "input_var": {"type"},      # тип внешней переменной меняет выходной порт
    "map_item": {"type"},       # (на будущее — у map_item тоже типизованный выход)
    "shift_get": {"type"},      # тип регистра меняет выход
    "shift_set": {"type"},      # тип регистра меняет вход и выход
}


class ParamInspector(QWidget):
    """Редактор параметров одного узла."""

    ports_changed = pyqtSignal(str)        # node_id — перестроить порты на сцене
    params_changed = pyqtSignal(str)       # node_id — параметры изменились (перерисовать)
    open_subgraph = pyqtSignal(str, str)   # node_id, param_key — открыть тело-подграф

    def __init__(self, doc: GraphDocument, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.node_id: Optional[str] = None
        self._entries = {e["type_id"]: e for e in doc.registry.palette()}
        self._form = QFormLayout(self)
        self._editors: dict[str, callable] = {}
        self._placeholder = QLabel("Выберите узел, чтобы изменить параметры.")
        self._form.addRow(self._placeholder)

    def _clear(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._editors.clear()

    def show_node(self, node_id: Optional[str]) -> None:
        self._clear()
        self.node_id = node_id
        if node_id is None or node_id not in self.doc.nodes:
            self._form.addRow(QLabel("Узел не выбран."))
            return

        node = self.doc.nodes[node_id]
        entry = self._entries.get(node.type, {})
        self._form.addRow(QLabel(f"<b>{entry.get('display_name', node.type)}</b>"))
        desc = entry.get("description")
        if desc:
            lbl = QLabel(desc)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #9AA0A6;")
            self._form.addRow(lbl)
        self._form.addRow("id", QLabel(node.id))

        schema = entry.get("params_schema") or {}
        if not schema:
            self._form.addRow(QLabel("У узла нет параметров."))
            return

        for key, meta in schema.items():
            self._add_field(node, key, meta)

    def _add_field(self, node, key: str, meta: dict) -> None:
        kind = meta.get("type", "string")
        cur = node.params.get(key, meta.get("default"))

        if kind == "subgraph":
            # Тело вложенного графа не редактируется формой — открывается
            # отдельным холстом. Кнопка делегирует это редактору.
            btn = QPushButton("Открыть подграф…")
            btn.clicked.connect(
                lambda _checked=False, k=key: self.open_subgraph.emit(self.node_id, k)
            )
            self._form.addRow(key, btn)
            return

        if kind == "case_bodies":
            # По кнопке на каждую ветвь (case_0..case_{N-1}) + ветвь default.
            try:
                n = max(0, int(node.params.get("cases", 2)))
            except (TypeError, ValueError):
                n = 2
            for i in range(n):
                bkey = f"case_{i}"
                b = QPushButton(f"Открыть ветвь {i}…")
                b.clicked.connect(
                    lambda _checked=False, k=bkey: self.open_subgraph.emit(self.node_id, k)
                )
                self._form.addRow(bkey, b)
            bd = QPushButton("Открыть ветвь default…")
            bd.clicked.connect(
                lambda _checked=False: self.open_subgraph.emit(self.node_id, "default")
            )
            self._form.addRow("default", bd)
            return

        if kind == "enum":
            w = QComboBox()
            w.addItems([str(v) for v in meta.get("values", [])])
            if cur is not None:
                w.setCurrentText(str(cur))
            w.currentTextChanged.connect(lambda _v, k=key: self._commit(k))
            self._editors[key] = w.currentText
        elif kind == "int":
            w = QSpinBox(); w.setRange(-10_000_000, 10_000_000)
            try: w.setValue(int(cur))
            except (TypeError, ValueError): w.setValue(0)
            w.valueChanged.connect(lambda _v, k=key: self._commit(k))
            self._editors[key] = w.value
        elif kind in ("text",):
            w = QPlainTextEdit(); w.setMaximumHeight(80)
            w.setPlainText("" if cur is None else str(cur))
            w.textChanged.connect(lambda k=key: self._commit(k))
            self._editors[key] = w.toPlainText
        elif kind == "list":
            w = QLineEdit("" if not cur else ", ".join(str(x) for x in cur))
            w.setPlaceholderText("через запятую")
            w.textChanged.connect(lambda _v, k=key: self._commit(k))
            self._editors[key] = lambda _w=w: [
                s.strip() for s in _w.text().split(",") if s.strip()
            ]
        else:  # string / number — храним как строку, backend нормализует
            w = QLineEdit("" if cur is None else str(cur))
            w.textChanged.connect(lambda _v, k=key: self._commit(k))
            self._editors[key] = (lambda _w=w: _w.text())

        # Параметры, меняющие набор портов (var_dict.names, block_list.count,
        # repeat/map.imports, input_var.type), перестраивают порты.
        # Текстовые поля — по завершении ввода (Enter / потеря фокуса), иначе
        # холст моргает; выпадающие списки — сразу при смене значения.
        if key in self._port_affecting_keys(node):
            if hasattr(w, "editingFinished"):
                w.editingFinished.connect(self._commit_ports)
            elif isinstance(w, QComboBox):
                w.currentTextChanged.connect(lambda _v: self._commit_ports())

        self._form.addRow(key, w)

    @staticmethod
    def _port_affecting_keys(node) -> set:
        return _PORT_AFFECTING.get(node.type, set())

    def _commit(self, key: str) -> None:
        if self.node_id is None:
            return
        node = self.doc.nodes.get(self.node_id)
        if node is None:
            return
        getter = self._editors.get(key)
        if getter is None:
            return
        node.params[key] = getter()
        # Значение записано в модель (JSON синхронизируется). Перестроение портов
        # для port-affecting полей произойдёт отдельно, по editingFinished.
        self.params_changed.emit(self.node_id)

    def _commit_ports(self) -> None:
        if self.node_id is not None:
            self.ports_changed.emit(self.node_id)
