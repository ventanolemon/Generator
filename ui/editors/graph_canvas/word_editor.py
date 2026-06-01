"""
WordEditorDialog — предпросмотр и правка словаря слов (term → translation).

Открывается из инспектора для узла words_file. Показывает слова таблицей,
позволяет добавлять/удалять/изменять строки и (по желанию) сохранить результат
обратно в JSON-файл. По OK правки возвращаются вызывающему коду, который кладёт
их в параметр inline узла — так отредактированный словарь живёт прямо в графе.
"""

from __future__ import annotations

import json

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QLabel, QFileDialog, QMessageBox, QAbstractItemView,
)


class WordEditorDialog(QDialog):
    """Таблица слов с добавлением/удалением строк и опц. сохранением в файл."""

    def __init__(self, words: dict[str, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Слова: предпросмотр и правка")
        self.resize(560, 460)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Слева — термин (англ.), справа — перевод. "
            "Добавляйте/удаляйте строки; пустые термины игнорируются."
        ))

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Термин", "Перевод"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self.table, stretch=1)

        for term, tr in (words or {}).items():
            self._append_row(str(term), str(tr))

        # Кнопки управления строками.
        rowbtns = QHBoxLayout()
        add = QPushButton("+ Строка")
        rem = QPushButton("− Удалить выделенные")
        save_file = QPushButton("Сохранить в файл…")
        add.clicked.connect(lambda: self._append_row("", ""))
        rem.clicked.connect(self._remove_selected)
        save_file.clicked.connect(self._save_to_file)
        rowbtns.addWidget(add)
        rowbtns.addWidget(rem)
        rowbtns.addStretch()
        rowbtns.addWidget(save_file)
        root.addLayout(rowbtns)

        # OK / Отмена.
        actions = QHBoxLayout()
        actions.addStretch()
        ok = QPushButton("OK")
        cancel = QPushButton("Отмена")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        actions.addWidget(ok)
        actions.addWidget(cancel)
        root.addLayout(actions)

    def _append_row(self, term: str, tr: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(term))
        self.table.setItem(r, 1, QTableWidgetItem(tr))

    def _remove_selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def result_words(self) -> dict[str, str]:
        """Собрать словарь из таблицы (пустые термины пропускаются)."""
        out: dict[str, str] = {}
        for r in range(self.table.rowCount()):
            t_item = self.table.item(r, 0)
            v_item = self.table.item(r, 1)
            term = (t_item.text().strip() if t_item else "")
            tr = (v_item.text().strip() if v_item else "")
            if term:
                out[term] = tr
        return out

    def _save_to_file(self) -> None:
        """Сохранить текущий словарь в JSON (формат vocabulary)."""
        words = self.result_words()
        if not words:
            QMessageBox.information(self, "Пусто", "Нет слов для сохранения.")
            return
        fn, _ = QFileDialog.getSaveFileName(
            self, "Сохранить слова", "", "JSON (*.json)")
        if not fn:
            return
        if not fn.lower().endswith(".json"):
            fn += ".json"
        payload = {
            "title": "Словарь",
            "vocabulary": [{"term": t, "translation": v} for t, v in words.items()],
        }
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Не удалось сохранить", str(e))
            return
        QMessageBox.information(self, "Сохранено", f"Слова сохранены:\n{fn}")
