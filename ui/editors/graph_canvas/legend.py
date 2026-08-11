"""
Легенда типов портов и таблица конверсий — справочник прямо в редакторе.

Делает видимым то, что иначе приходится искать в коде: что означает каждый
цвет провода и каким узлом превратить один тип в другой. Открывается кнопкой
в редакторе графа.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QLabel, QVBoxLayout, QFrame, QScrollArea, QWidget,
)

from core.graph import PortType, conversion_table

from . import style


# Короткое человекочитаемое значение каждого типа порта (для легенды).
TYPE_MEANINGS: dict[PortType, str] = {
    PortType.NUMBER: "число (int/float)",
    PortType.STRING: "текст",
    PortType.NUMBER_DICT: "словарь имя→число (бандл переменных)",
    PortType.BOOL: "логическое да/нет",
    PortType.LIST: "список значений (коллекция)",
    PortType.EXPR: "символьное выражение (sympy)",
    PortType.MATRIX: "матрица / вектор (sympy)",
    PortType.IMAGE: "изображение (PIL)",
    PortType.WORDS: "словарь слов term→перевод (англ.)",
    PortType.SENTENCES: "предложения с пропусками (англ.)",
    PortType.BLOCK: "блок задания",
    PortType.BLOCK_LIST: "список блоков",
    PortType.TASK: "готовое задание (финал графа)",
    PortType.FUNC: "символьная функция: параметры + тело (expr_lambda → expr_call)",
    PortType.ANY: "любой тип — полиморфный вход (узел сам разбирает)",
}


def _swatch(color) -> QLabel:
    w = QLabel()
    w.setFixedSize(16, 16)
    w.setStyleSheet(
        f"background:{color.name()}; border:1px solid #1A1A1A; border-radius:8px;"
    )
    return w


class TypeLegendDialog(QDialog):
    """Окно: список типов с цветами + таблица «из чего во что» (конвертеры)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Типы данных и конверсии")
        self.setMinimumWidth(440)

        root = QVBoxLayout(self)

        root.addWidget(QLabel("<b>Типы портов</b> (цвет провода = тип):"))
        types_grid = QGridLayout()
        for row, pt in enumerate(PortType):
            types_grid.addWidget(_swatch(style.port_color(pt)), row, 0)
            types_grid.addWidget(QLabel(f"<b>{pt.value}</b>"), row, 1)
            types_grid.addWidget(QLabel(TYPE_MEANINGS.get(pt, "")), row, 2)
        types_grid.setColumnStretch(2, 1)
        root.addLayout(types_grid)

        line = QFrame(); line.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line)

        # Ветки — вторая раскраска тех же проводов, поэтому объясняется
        # там же, где первая: иначе включивший режим видит другие цвета и
        # не знает, где посмотреть их значение.
        root.addWidget(QLabel(
            "<b>Ветки задания</b> (кнопка «Ветки»: цвет провода = куда он "
            "в итоге приходит):"))
        branch_grid = QGridLayout()
        rows = [
            ("statement", "готовит УСЛОВИЕ — то, что видит студент"),
            ("answer", "готовит ОТВЕТ — то, с чем сверяется ввод"),
            ("both", "работает и на условие, и на ответ"),
        ]
        for row, (key, meaning) in enumerate(rows):
            branch_grid.addWidget(_swatch(style.BRANCH_COLORS[key]), row, 0)
            branch_grid.addWidget(
                QLabel(f"<b>{style.BRANCH_TITLES[key]}</b>"), row, 1)
            branch_grid.addWidget(QLabel(meaning), row, 2)
        last = len(rows)
        branch_grid.addWidget(_swatch(style.BRANCH_UNUSED), last, 0)
        branch_grid.addWidget(QLabel("<b>не в задании</b>"), last, 1)
        branch_grid.addWidget(
            QLabel("до финального узла не доходит — на задание не влияет"),
            last, 2)
        branch_grid.setColumnStretch(2, 1)
        root.addLayout(branch_grid)
        root.addWidget(QLabel(
            "<i>Ветки не размечаются вручную: они считаются по графу от "
            "финального узла.</i>"))

        line2 = QFrame(); line2.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(line2)

        root.addWidget(QLabel(
            "<b>Как превратить один тип в другой</b> "
            "(узел-конвертер; авто — движок сам):"))
        conv = QGridLayout()
        conv.addWidget(QLabel("<i>из</i>"), 0, 0)
        conv.addWidget(QLabel("<i>в</i>"), 0, 1)
        conv.addWidget(QLabel("<i>узел</i>"), 0, 2)
        for i, (src, dst, node) in enumerate(conversion_table(), start=1):
            conv.addWidget(QLabel(src), i, 0)
            conv.addWidget(QLabel("→ " + dst), i, 1)
            conv.addWidget(QLabel(node), i, 2)
        conv.setColumnStretch(2, 1)
        wrap = QWidget(); wrap.setLayout(conv)
        scroll = QScrollArea(); scroll.setWidget(wrap); scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

        hint = QLabel(
            "Совет: тяните провод от выхода — совместимые входы подсветятся "
            "зелёным, а входы, куда нужен конвертер, — янтарным пунктиром. "
            "Отпустите на янтарном, чтобы вставить конвертер автоматически.")
        hint.setWordWrap(True)
        hint.setProperty("class", "muted")
        root.addWidget(hint)
