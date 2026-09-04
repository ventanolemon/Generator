"""
Цвета и метрики канваса. Цвет провода = тип порта (как в LabVIEW).

Два разных вида цвета, и путать их нельзя
-----------------------------------------
**Цвет-значение** — тип порта, категория узла, ветка «условие»/«ответ».
Он часть языка графа: синий провод означает число в любой теме, и менять
его вместе с оформлением значило бы менять смысл картинки.

**Цвет-поверхность** — фон сцены, сетка, тело узла, текст. Это оформление,
и оно обязано следовать теме приложения.

Раньше поверхности были такими же константами, как значения, и ставились
один раз при создании сцены. Тема о них не знала и знать не могла — холст
оставался чёрным при переключении на светлую. Теперь поверхности
ВЫВОДЯТСЯ из палитры темы (`apply_palette`), а не заводятся вторым
набором констант: отдельный «светлый» набор разошёлся бы с темой при
первой же её правке — ровно так разошлись эти.

Модуль не импортирует `ui.theme`: зависимость идёт в одну сторону —
`apply_theme` зовёт `apply_palette`. Обратный импорт сделал бы цикл.
"""

from __future__ import annotations

import weakref

from PyQt6.QtGui import QColor

from core.graph import PortType


# Цвет по типу порта — БАЗОВЫЕ тона. Значение здесь несёт ТОН: синий
# означает число в любой теме. Светлота подбирается под фон холста
# (см. apply_palette): на светлом холсте те же тона нужны темнее,
# иначе салатовый провод на белом просто не виден — это замерено.
_BASE_PORT_COLORS: dict[PortType, QColor] = {
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
    PortType.SENTENCES:   QColor("#4DB6AC"),   # светло-бирюзовый — предложения
    PortType.TASK:        QColor("#27AE60"),   # зелёный
    PortType.FUNC:        QColor("#EC407A"),   # розовый — символьная функция
    # Средне-серый, а не светлый: цвет-значение один на обе темы, и
    # прежний #D0D0D0 на светлом холсте практически не читался.
    PortType.ANY:         QColor("#909090"),   # серый — полиморфный порт
}

# Цвет заголовка узла по категории — базовые тона, та же логика.
_BASE_CATEGORY_COLORS: dict[str, QColor] = {
    "task":     QColor("#1B5E20"),   # готовые задания — тёмно-зелёные
    "source":   QColor("#6C3483"),   # источники — фиолетовые
    "compute":  QColor("#117864"),   # вычисление — бирюзовые
    "control":  QColor("#B9770E"),   # управление — янтарные
    "list":     QColor("#558B2F"),   # списки — оливковый
    "symbolic": QColor("#7D3C98"),   # символьная арифметика — пурпурные
    "linalg":   QColor("#3949AB"),   # линейная алгебра — индиго
    "ode":      QColor("#00838F"),   # дифференциальные уравнения — тёмная бирюза
    "english":  QColor("#00695C"),   # английский язык — глубокий бирюзовый
    "image":    QColor("#2E7D32"),   # изображения / ОПВС — зелёный
    "plot":     QColor("#AD1457"),   # графика на ℂ-плоскости — малиновый
    "content":  QColor("#A93226"),   # контент — коралловые
    "assembly": QColor("#1F618D"),   # сборка — синие
}

NODE_BG = QColor("#2B2B2B")
NODE_BORDER = QColor("#555555")
NODE_BORDER_SEL = QColor("#F7C948")

# Подсветка портов при протягивании провода: прямо совместим / нужен конвертер.
DROP_OK = QColor("#7CFC8A")          # зелёный — типы совместимы напрямую
DROP_CONVERT = QColor("#F5B041")     # янтарный — есть конвертер X→Y
NODE_TEXT = QColor("#ECECEC")
SCENE_BG = QColor("#1E1E1E")
GRID = QColor("#2A2A2A")

# Рамка-структура развёрнутого цикла (тело на холсте, LabVIEW-style).
FRAME_BG = QColor(34, 38, 34)            # чуть зеленее фона сцены
FRAME_BORDER = QColor("#8A6D1F")         # тёмно-янтарная (категория control)

# Рамка-комментарий (аннотация, не исполняется): полупрозрачная заливка,
# пунктирная граница, шапка с текстом.
COMMENT_BG = QColor(247, 201, 72, 28)    # янтарная, сильно прозрачная
COMMENT_HEADER_BG = QColor(247, 201, 72, 60)
COMMENT_BORDER = QColor("#B8912E")
COMMENT_TEXT = QColor("#E8DCB0")

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

# Ветки «условие»/«ответ» (core/graph/branches.py) — режим чтения графа.
# Намеренно не пересекаются с палитрой типов портов выше: подсветка
# включается поверх той же картинки, и совпадение цвета читалось бы как
# «этот провод такого типа».
_BASE_BRANCH_COLORS: dict[str, QColor] = {
    "statement": QColor("#3F7FD0"),   # условие
    "answer":    QColor("#2E9E6B"),   # ответ
    "both":      QColor("#A06CD5"),   # и туда, и туда
}
# Провод (узел), не доходящий до финала: он ни на что не влияет.
BRANCH_UNUSED = QColor(140, 140, 140, 130)
BRANCH_TITLES: dict[str, str] = {
    "statement": "условие",
    "answer": "ответ",
    "both": "общее",
}

# Подпись провода (meta.edge_notes): текст поверх линии, обведённый цветом
# фона, — плашка накрыла бы сам провод.
EDGE_NOTE_TEXT = QColor("#E8E8E8")
EDGE_NOTE_HALO = SCENE_BG

# Живые таблицы цветов-значений: базовые тона, подогнанные по светлоте
# под фон холста. Пересчитываются в apply_palette; до неё — тёмная тема.
PORT_COLORS: dict[PortType, QColor] = dict(_BASE_PORT_COLORS)
CATEGORY_COLORS: dict[str, QColor] = dict(_BASE_CATEGORY_COLORS)
BRANCH_COLORS: dict[str, QColor] = dict(_BASE_BRANCH_COLORS)

PORT_RADIUS = 6.0
NODE_WIDTH = 180.0
HEADER_H = 26.0
ROW_H = 22.0

# Лента-сводка содержимого узла под заголовком (Node.summary()): «окошко»,
# в котором видно, ЧТО узел делает — формула, диапазон, глиф операции.
SUMMARY_H = 20.0
SUMMARY_BG = QColor("#232323")           # чуть темнее тела — как дисплей
_BASE_SUMMARY_TEXT = QColor("#F5D06E")   # тёплый акцент: сводка ≠ подпись порта
SUMMARY_TEXT = QColor(_BASE_SUMMARY_TEXT)
GLYPH_MAX_CHARS = 3                      # сводки не длиннее — крупным глифом


def port_color(port_type: PortType) -> QColor:
    return PORT_COLORS.get(port_type, QColor("#AAAAAA"))


def category_color(category: str) -> QColor:
    return CATEGORY_COLORS.get(category, QColor("#444444"))


# ---------- Поверхности: выводятся из палитры темы ----------
#
# Значения ниже — умолчание тёмной темы, чтобы модуль оставался рабочим
# без темы вовсе (тесты, headless-рендер, ранний импорт до apply_theme).
# Живые значения ставит apply_palette; код рисования читает их через
# `style.ИМЯ`, поэтому пересчёт виден всем без правки мест использования.


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    """Линейная смесь: t=0 → a, t=1 → b."""
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    )


def luminance(color: QColor) -> float:
    """Относительная яркость по WCAG. Нужна, чтобы решать, а не угадывать."""
    def channel(value: int) -> float:
        v = value / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return (0.2126 * channel(color.red())
            + 0.7152 * channel(color.green())
            + 0.0722 * channel(color.blue()))


def contrast(a: QColor, b: QColor) -> float:
    """Контраст по WCAG: 1.0 — неразличимы, 21.0 — чёрное на белом."""
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def on_color(background: QColor) -> QColor:
    """
    Цвет текста, читаемый НА этой заливке.

    Заголовок узла залит цветом категории — тёмным и насыщенным. Взять
    туда цвет текста темы значило бы получить тёмное на тёмном ровно в
    светлой теме: цвет категории от темы не зависит, а цвет текста
    зависит. Выбор по яркости самой заливки такого рассогласования не
    допускает по построению.
    """
    return QColor("#101114") if luminance(background) > 0.35 else QColor("#F4F4F7")


def _for_ground(color: QColor, ground: QColor, *, target: float) -> QColor:
    """
    Тот же ТОН, но со светлотой, различимой на этом фоне.

    Тон и насыщенность — язык графа: синий провод означает число в любой
    теме. Светлота к языку не относится, и держать её постоянной нельзя:
    салатовый провод (#9CCC65) на белом холсте даёт контраст 1.5 — это
    замер, а не мнение. Поэтому светлота подтягивается к цели, заданной
    фоном: на тёмном холсте тона светлее, на светлом темнее.
    """
    hue, saturation, lightness, alpha = color.getHslF()
    if hue < 0:                       # серый: тона нет, тянем только светлоту
        hue, saturation = 0.0, 0.0
    out = QColor()
    out.setHslF(hue, saturation, max(0.0, min(1.0, target)), alpha)
    return out


def _targets(ground: QColor) -> tuple[float, float]:
    """
    Целевая светлота: провода и заливки заголовков.

    Провода тянутся ОТ фона: на тёмном холсте светлее, на светлом темнее.
    Заливка заголовка остаётся тёмной в обеих темах — на ней стоит текст,
    и тёмная заливка со светлым текстом читается одинаково везде. 0.22
    выбрана замером: при 0.32 худшая пара («english») давала контраст
    2.9, при 0.22 — 5.3.
    """
    return (0.66, 0.22) if luminance(ground) < 0.25 else (0.36, 0.22)


def _text_target(ground: QColor) -> float:
    """
    Целевая светлота для ЦВЕТНОГО ТЕКСТА на этом фоне.

    Отдельно от проводов: провод — линия в два пикселя с обводкой, буква
    тоньше и требует большего запаса. Замер: янтарная сводка по «проводной»
    цели давала на светлой теме контраст 2.8, по этой — 6.9.
    """
    return 0.74 if luminance(ground) < 0.25 else 0.26


#: Живые сцены, которым нужно сообщить о смене темы. Слабые ссылки:
#: реестр не должен удерживать закрытый редактор.
_scenes: "weakref.WeakSet" = weakref.WeakSet()


def register_scene(scene) -> None:
    """
    Запомнить сцену, чтобы перекрасить её при смене темы.

    Без этого фон остался бы прежним у уже открытого редактора: QSS на
    QGraphicsScene не действует, фон ставится кистью один раз.
    """
    _scenes.add(scene)


def apply_palette(palette) -> None:
    """
    Пересчитать цвета-поверхности из палитры темы и перекрасить сцены.

    `palette` — `ui.theme.Palette` (утиный доступ по именам токенов),
    чтобы модуль холста не зависел от модуля темы.
    """
    global SCENE_BG, GRID, NODE_BG, NODE_BORDER, NODE_TEXT
    global FRAME_BG, COMMENT_TEXT, EDGE_NOTE_TEXT, EDGE_NOTE_HALO
    global SUMMARY_BG, SUMMARY_TEXT
    global PORT_COLORS, CATEGORY_COLORS, BRANCH_COLORS

    bg = QColor(palette.bg)
    surface = QColor(palette.surface)
    surface_alt = QColor(palette.surface_alt)
    text = QColor(palette.text)
    border = QColor(palette.border)

    # Холст — «лист», отодвинутый от фона окна В СТОРОНУ ТЕКСТА: в тёмной
    # теме он светлее хрома, в светлой темнее. Одно правило на обе темы,
    # без разбора «а сейчас у нас светло или темно»: такой разбор и есть
    # второй набор констант, только записанный условием.
    SCENE_BG = _mix(bg, text, 0.07)
    # Узел — карточка на этом листе: ещё шаг в ту же сторону.
    NODE_BG = _mix(bg, text, 0.16)
    GRID = _mix(SCENE_BG, text, 0.06)
    NODE_BORDER = _mix(border, text, 0.20)
    NODE_TEXT = text
    # Лента-сводка — «дисплей»: на полтона обратно к фону окна.
    SUMMARY_BG = _mix(NODE_BG, bg, 0.45)
    # Рамка цикла — чуть в сторону «успеха» от холста (см. FRAME_BORDER).
    FRAME_BG = _mix(SCENE_BG, QColor(palette.success), 0.08)
    # Текст комментария — основной, притянутый к янтарю комментариев.
    COMMENT_TEXT = _for_ground(QColor(palette.warning), SCENE_BG,
                               target=_text_target(SCENE_BG))
    EDGE_NOTE_TEXT = text
    # Обводка подписи провода — цветом холста: плашка накрыла бы провод.
    EDGE_NOTE_HALO = SCENE_BG
    SUMMARY_TEXT = _for_ground(_BASE_SUMMARY_TEXT, SUMMARY_BG,
                               target=_text_target(SUMMARY_BG))

    # Цвета-значения: тон прежний, светлота — под фон холста.
    wire_target, fill_target = _targets(SCENE_BG)
    PORT_COLORS = {t: _for_ground(c, SCENE_BG, target=wire_target)
                   for t, c in _BASE_PORT_COLORS.items()}
    BRANCH_COLORS = {k: _for_ground(c, SCENE_BG, target=wire_target)
                     for k, c in _BASE_BRANCH_COLORS.items()}
    CATEGORY_COLORS = {k: _for_ground(c, SCENE_BG, target=fill_target)
                       for k, c in _BASE_CATEGORY_COLORS.items()}

    for scene in list(_scenes):
        try:
            scene.setBackgroundBrush(SCENE_BG)
            scene.update()
        except RuntimeError:
            # Сцена уже удалена на стороне C++ — слабая ссылка ещё жива.
            _scenes.discard(scene)
