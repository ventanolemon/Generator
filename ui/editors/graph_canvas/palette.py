"""
NodePalette — список доступных узлов, сгруппированный по категориям.
Строится целиком из NodeRegistry.palette(); о конкретных классах не знает.
Двойной клик по типу добавляет узел в центр сцены.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from core.graph import DEFAULT_REGISTRY
from core.graph.registry import NodeRegistry


_CATEGORY_LABELS = {
    "source":   "Источники",
    "compute":  "Вычисление",
    "control":  "Управление",
    "content":  "Блоки контента",
    "assembly": "Сборка задания",
}
_CATEGORY_ORDER = ["source", "compute", "control", "content", "assembly"]


class NodePalette(QTreeWidget):
    """Дерево «категория → типы узлов»."""

    add_requested = pyqtSignal(str)     # type_id

    def __init__(self, registry: NodeRegistry | None = None, parent=None):
        super().__init__(parent)
        self.registry = registry or DEFAULT_REGISTRY
        self.setHeaderHidden(True)
        self.setMaximumWidth(240)
        self._populate()
        self.itemDoubleClicked.connect(self._on_double_click)

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
            self.addTopLevelItem(head)
            for entry in sorted(entries, key=lambda e: e["display_name"]):
                child = QTreeWidgetItem([entry["display_name"]])
                child.setData(0, Qt.ItemDataRole.UserRole, entry["type_id"])
                child.setToolTip(0, self._tooltip(entry))
                head.addChild(child)
            head.setExpanded(True)

    @staticmethod
    def _tooltip(entry: dict) -> str:
        ins = ", ".join(f"{n}:{t}" for n, t in entry["inputs"]) or "—"
        outs = ", ".join(f"{n}:{t}" for n, t in entry["outputs"]) or "—"
        return (f"{entry['type_id']}\n"
                f"входы: {ins}\n"
                f"выходы: {outs}")

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        type_id = item.data(0, Qt.ItemDataRole.UserRole)
        if type_id:
            self.add_requested.emit(type_id)
