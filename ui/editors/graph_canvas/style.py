"""
Цвета и метрики канваса. Цвет провода = тип порта (как в LabVIEW).
"""

from __future__ import annotations

from PyQt6.QtGui import QColor

from core.graph import PortType


# Цвет по типу порта.
PORT_COLORS: dict[PortType, QColor] = {
    PortType.NUMBER:      QColor("#4F8EF7"),   # синий
    PortType.STRING:      QColor("#E0A030"),   # оранжевый
    PortType.NUMBER_DICT: QColor("#9B59B6"),   # фиолетовый
    PortType.IMAGE:       QColor("#16A085"),   # бирюзовый
    PortType.BLOCK:       QColor("#E74C3C"),   # коралловый
    PortType.BLOCK_LIST:  QColor("#C0392B"),   # тёмно-коралловый
    PortType.BOOL:        QColor("#7F8C8D"),   # серый
    PortType.LIST:        QColor("#9CCC65"),   # салатовый — коллекция
    PortType.EXPR:        QColor("#AB47BC"),   # пурпурный — символьное выражение
    PortType.MATRIX:      QColor("#5C6BC0"),   # индиго — матрица/вектор
    PortType.WORDS:       QColor("#26A69A"),   # бирюзовый — словарь слов
    PortType.TASK:        QColor("#27AE60"),   # зелёный
}

# Цвет заголовка узла по категории.
CATEGORY_COLORS: dict[str, QColor] = {
    "task":     QColor("#1B5E20"),   # готовые задания — тёмно-зелёные
    "source":   QColor("#6C3483"),   # источники — фиолетовые
    "compute":  QColor("#117864"),   # вычисление — бирюзовые
    "control":  QColor("#B9770E"),   # управление — янтарные
    "symbolic": QColor("#7D3C98"),   # символьная арифметика — пурпурные
    "linalg":   QColor("#3949AB"),   # линейная алгебра — индиго
    "ode":      QColor("#00838F"),   # дифференциальные уравнения — тёмная бирюза
    "english":  QColor("#00695C"),   # английский язык — глубокий бирюзовый
    "content":  QColor("#A93226"),   # контент — коралловые
    "assembly": QColor("#1F618D"),   # сборка — синие
}

NODE_BG = QColor("#2B2B2B")
NODE_BORDER = QColor("#555555")
NODE_BORDER_SEL = QColor("#F7C948")
NODE_TEXT = QColor("#ECECEC")
SCENE_BG = QColor("#1E1E1E")
GRID = QColor("#2A2A2A")

# Рамка-структура развёрнутого цикла (тело на холсте, LabVIEW-style).
FRAME_BG = QColor(34, 38, 34)            # чуть зеленее фона сцены
FRAME_BORDER = QColor("#8A6D1F")         # тёмно-янтарная (категория control)

# Роль узла относительно финала графа: рамка и бейдж в заголовке.
#   result    — единственный свободный выход TASK: финал графа;
#   conflict  — свободных TASK несколько: финал неоднозначен;
#   forbidden — узел-задание внутри тела цикла/ветви: TASK здесь запрещён.
ROLE_BORDERS: dict[str, QColor] = {
    "result":    QColor("#27AE60"),   # зелёный — как тип TASK
    "conflict":  QColor("#E67E22"),   # оранжевый — требует решения
    "forbidden": QColor("#C0392B"),   # красный — здесь нельзя
}
ROLE_BADGES: dict[str, tuple[str, QColor]] = {
    "result":    ("ВЫХОД",  ROLE_BORDERS["result"]),
    "conflict":  ("ВЫХОД?", ROLE_BORDERS["conflict"]),
    "forbidden": ("✗ TASK", ROLE_BORDERS["forbidden"]),
}
ROLE_TOOLTIPS: dict[str, str] = {
    "result": "Финальный узел: его свободный выход TASK — результат всего графа.",
    "conflict": ("Несколько узлов со свободным выходом TASK — финал графа "
                 "неоднозначен. Оставьте свободным ровно один (лишние удалите "
                 "или подключите)."),
    "forbidden": ("Узел-задание внутри тела цикла/ветви: выход TASK здесь "
                  "запрещён. Результат итерации — свободный выход BLOCK, "
                  "а финальное задание собирается во внешнем графе."),
}

PORT_RADIUS = 6.0
NODE_WIDTH = 180.0
HEADER_H = 26.0
ROW_H = 22.0


def port_color(port_type: PortType) -> QColor:
    return PORT_COLORS.get(port_type, QColor("#AAAAAA"))


def category_color(category: str) -> QColor:
    return CATEGORY_COLORS.get(category, QColor("#444444"))
