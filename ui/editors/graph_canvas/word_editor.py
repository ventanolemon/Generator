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

    def __init__(self, words: dict[str, str], parent=None, audio=None):
        super().__init__(parent)
        self.setWindowTitle("Слова: предпросмотр и правка")
        self.resize(820, 460)
        self._audio = dict(audio or {})

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Термин, перевод и необязательный собственный WAV-эталон. "
            "Добавляйте/удаляйте строки; пустые термины игнорируются."
        ))

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Термин", "Перевод", "Аудио WAV"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 220)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        root.addWidget(self.table, stretch=1)

        for term, tr in (words or {}).items():
            self._append_row(str(term), str(tr), self._audio.get(str(term), ""))

        # Кнопки управления строками.
        rowbtns = QHBoxLayout()
        add = QPushButton("+ Строка")
        rem = QPushButton("− Удалить выделенные")
        save_file = QPushButton("Сохранить в файл…")
        pick_audio = QPushButton("Выбрать WAV для строки…")
        add.clicked.connect(lambda: self._append_row("", "", ""))
        rem.clicked.connect(self._remove_selected)
        save_file.clicked.connect(self._save_to_file)
        pick_audio.clicked.connect(self._pick_audio)
        rowbtns.addWidget(add)
        rowbtns.addWidget(rem)
        rowbtns.addWidget(pick_audio)
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

    def _append_row(self, term: str, tr: str, audio: str = "") -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(term))
        self.table.setItem(r, 1, QTableWidgetItem(tr))
        self.table.setItem(r, 2, QTableWidgetItem(audio))

    def _pick_audio(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Строка не выбрана",
                                    "Сначала выберите слово в таблице.")
            return
        filename, _ = QFileDialog.getOpenFileName(
            self, "Выберите образец произношения", "", "WAV (*.wav)")
        if filename:
            self.table.setItem(row, 2, QTableWidgetItem(filename))

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

    def result_audio(self) -> dict[str, str]:
        """Собрать непустые пользовательские WAV по терминам."""
        out: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            term = self.table.item(row, 0)
            audio = self.table.item(row, 2)
            if term and audio and term.text().strip() and audio.text().strip():
                out[term.text().strip()] = audio.text().strip()
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
        audio = self.result_audio()
        entries = []
        for term, translation in words.items():
            entry = {"term": term, "translation": translation}
            if term in audio:
                entry["audio"] = audio[term]
            entries.append(entry)
        payload = {
            "title": "Словарь",
            "vocabulary": entries,
        }
        try:
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except OSError as e:
            QMessageBox.warning(self, "Не удалось сохранить", str(e))
            return
        QMessageBox.information(self, "Сохранено", f"Слова сохранены:\n{fn}")
