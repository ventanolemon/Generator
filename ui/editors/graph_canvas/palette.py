"""
NodePalette — список доступных узлов, сгруппированный по категориям.
Строится целиком из NodeRegistry.palette(); о конкретных классах не знает.
Двойной клик по типу добавляет узел в центр сцены.

Отдельный раздел «Словари» перечисляет JSON-файлы со словами/предложениями из
resources/words: двойной клик добавляет уже настроенный на этот файл узел
(тип определяется по содержимому), плюс кнопка «Обзор…» для файла из любого места.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QPushButton, QFileDialog,
    QMessageBox,
)

from core.graph import DEFAULT_REGISTRY
from core.graph.registry import NodeRegistry


_CATEGORY_LABELS = {
    "source":   "Источники",
    "compute":  "Вычисление",
    "control":  "Управление",
    "symbolic": "Символьная математика",
    "linalg":   "Линейная алгебра",
    "ode":      "Дифф. уравнения",
    "english":  "Английский язык",
    "image":    "Изображения / ОПВС",
    "list":     "Списки",
    "content":  "Блоки контента",
    "assembly": "Сборка задания",
}
_CATEGORY_ORDER = ["source", "compute", "control", "list", "symbolic", "linalg",
                   "ode", "english", "image", "content", "assembly"]


def _words_dir() -> Path | None:
    """Стандартная папка со словарями (resources/words), если задана в const."""
    try:
        from const import WORDS_DIR
        return Path(WORDS_DIR)
    except Exception:
        return None


def _node_type_for_file(path: str) -> str | None:
    """Тип узла-источника по содержимому JSON: words_file / sentences_file."""
    try:
        from exercises.english.generators import _detect_kind
        kind = _detect_kind(Path(path))
    except Exception:
        return None
    if kind == "words":
        return "words_file"
    if kind == "sentences":
        return "sentences_file"
    return None


# Роль для хранения пути к файлу в элементе раздела «Словари».
_FILE_ROLE = Qt.ItemDataRole.UserRole + 1


class NodePalette(QWidget):
    """Палитра: дерево «категория → типы узлов» + раздел файлов словарей."""

    add_requested = pyqtSignal(str)              # type_id
    add_file_requested = pyqtSignal(str, str)    # type_id, file_path

    def __init__(self, registry: NodeRegistry | None = None, parent=None):
        super().__init__(parent)
        self.registry = registry or DEFAULT_REGISTRY
        self.setMaximumWidth(240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.tree, stretch=1)

        self.browse_btn = QPushButton("Обзор файла словаря…", self)
        self.browse_btn.setToolTip(
            "Выбрать JSON со словами или предложениями из любого места — "
            "узел добавится автоматически по содержимому файла."
        )
        self.browse_btn.clicked.connect(self._browse_file)
        layout.addWidget(self.browse_btn)

        self._populate()

    def _populate(self) -> None:
        by_cat: dict[str, list[dict]] = {}
        for entry in self.registry.palette():
            by_cat.setdefault(entry["category"], []).append(entry)

        ordered = _CATEGORY_ORDER + [
            c for c in by_cat if c not in _CATEGORY_ORDER
        ]
        for cat in ordered:
            entries = by_cat.get(cat)
            if not entries:
                continue
            head = QTreeWidgetItem([_CATEGORY_LABELS.get(cat, cat)])
            head.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = head.font(0); font.setBold(True); head.setFont(0, font)
            self.tree.addTopLevelItem(head)
            for entry in sorted(entries, key=lambda e: e["display_name"]):
                child = QTreeWidgetItem([entry["display_name"]])
                child.setData(0, Qt.ItemDataRole.UserRole, entry["type_id"])
                child.setToolTip(0, self._tooltip(entry))
                head.addChild(child)
            head.setExpanded(True)

        self._populate_files()

    def _populate_files(self) -> None:
        """Раздел «Словари»: файлы из resources/words с авто-определением типа."""
        wd = _words_dir()
        if wd is None or not wd.exists():
            return
        files = sorted(wd.glob("*.json"))
        if not files:
            return
        head = QTreeWidgetItem(["Словари (файлы)"])
        head.setFlags(Qt.ItemFlag.ItemIsEnabled)
        font = head.font(0); font.setBold(True); head.setFont(0, font)
        self.tree.addTopLevelItem(head)
        for path in files:
            type_id = _node_type_for_file(str(path))
            if type_id is None:
                continue
            label = path.stem
            kind = "слова" if type_id == "words_file" else "предложения"
            child = QTreeWidgetItem([label])
            child.setData(0, Qt.ItemDataRole.UserRole, type_id)
            child.setData(0, _FILE_ROLE, str(path))
            child.setToolTip(0, f"{path.name}\n({kind})")
            head.addChild(child)
        head.setExpanded(True)

    @staticmethod
    def _tooltip(entry: dict) -> str:
        ins = ", ".join(f"{n}:{t}" for n, t in entry["inputs"]) or "—"
        outs = ", ".join(f"{n}:{t}" for n, t in entry["outputs"]) or "—"
        lines = [entry["type_id"]]
        if entry.get("description"):
            lines.append(entry["description"])
        lines += [f"входы: {ins}", f"выходы: {outs}"]
        return "\n".join(lines)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not type_id:
            return
        file_path = item.data(0, _FILE_ROLE)
        if file_path:
            self.add_file_requested.emit(type_id, file_path)
        else:
            self.add_requested.emit(type_id)

    def _browse_file(self) -> None:
        start = ""
        wd = _words_dir()
        if wd is not None and wd.exists():
            start = str(wd)
        fn, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл словаря/предложений", start, "JSON (*.json)")
        if not fn:
            return
        type_id = _node_type_for_file(fn)
        if type_id is None:
            QMessageBox.warning(
                self, "Не удалось распознать файл",
                "Файл не похож ни на словарь, ни на предложения с пропусками."
            )
            return
        self.add_file_requested.emit(type_id, fn)
