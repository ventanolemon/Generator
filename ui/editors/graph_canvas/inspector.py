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
    "formula": {"expr"},        # переменные формулы → именованные входы
    "template": {"text"},       # маркеры #имя# → именованные входы
    "text": {"text"},           # то же для узла «Текст»
    "repeat": {"imports", "registers"},  # imports → входы, registers → выходы
    "list_new": {"count", "elem_type"},  # число/тип входов-элементов
    "list_append": {"elem_type"},        # тип входа item
    "list_get": {"elem_type"},           # тип выхода
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

        if kind == "hidden":
            # Служебный параметр (напр. inline-словарь) — в форме не показываем.
            return

        if kind == "file":
            self._add_file_field(node, key, meta)
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

    def _add_file_field(self, node, key: str, meta: dict) -> None:
        """Поле выбора файла: путь + «Выбрать…» (+ «Просмотр» для слов)."""
        from PyQt6.QtWidgets import QFileDialog, QWidget, QVBoxLayout, QHBoxLayout

        wrap = QWidget()
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)

        cur = str(node.params.get(key, meta.get("default", "")) or "")
        path_lbl = QLabel(cur or "— файл не выбран —")
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet("color: #9AA0A6;")
        col.addWidget(path_lbl)

        row = QHBoxLayout()
        pick = QPushButton("Выбрать…")
        row.addWidget(pick)
        preview_kind = meta.get("preview")
        edit_btn = QPushButton("Просмотр/правка") if preview_kind == "words" else None
        if edit_btn is not None:
            row.addWidget(edit_btn)
        col.addLayout(row)

        flt = meta.get("filter", "Все файлы (*.*)")

        def choose():
            start = node.params.get(key) or ""
            fn, _ = QFileDialog.getOpenFileName(self, "Выберите файл", start, flt)
            if fn:
                node.params[key] = fn
                # Новый файл отменяет ранее сохранённые правки (inline).
                if "inline" in (self._entries.get(node.type, {})
                                .get("params_schema") or {}):
                    node.params["inline"] = None
                path_lbl.setText(fn)
                self.params_changed.emit(self.node_id)

        pick.clicked.connect(lambda: choose())
        if edit_btn is not None:
            edit_btn.clicked.connect(lambda: self._edit_words(node, key))

        self._form.addRow(key, wrap)

    def _edit_words(self, node, file_key: str) -> None:
        """Открыть диалог предпросмотра/правки словаря слов узла."""
        from .word_editor import WordEditorDialog
        # Источник слов: сохранённые правки (inline) или файл.
        words = node.params.get("inline")
        if not isinstance(words, dict) or not words:
            path = str(node.params.get(file_key, "") or "")
            try:
                from core.graph.nodes.english import _load_words_file
                words = _load_words_file(path) if path else {}
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Не удалось открыть слова", str(e))
                return
        dlg = WordEditorDialog(words, parent=self)
        if dlg.exec():
            node.params["inline"] = dlg.result_words()
            self.params_changed.emit(self.node_id)

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
