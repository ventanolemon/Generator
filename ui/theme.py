"""
Тема приложения — контракт K1 плана docs/ui_rework_plan.md (владелец Fable).

Одна точка правды о цветах и типографике UI:

  * `Palette` — токены темы (bg/surface/.../border), два экземпляра:
    `DARK` (по умолчанию, согласован с холстом графа #1E1E1E/#2B2B2B из
    ui/editors/graph_canvas/style.py) и `LIGHT`.
  * `build_qss(palette)` — глобальный QSS, построенный из токенов.
  * `apply_theme(app, name)` — применить тему ("dark"|"light") к приложению.

Словарь QSS-классов (обе стороны используют ровно эти имена; виджет получает
класс через `w.setProperty("class", "…")`, стилизация — селектором
`QWidget[class="…"]`):

    title, subtitle, card, toolbar, toolbtn,
    badge, badge-warn, badge-error, danger, muted

Дополнительно (расширение сверх минимума K1, тем же механизмом): `accent`.

ВАЖНО: если класс меняется у уже показанного виджета, QSS перечитывается
только после re-polish (`style().unpolish(w); style().polish(w)`) — так уже
делает TopBar.set_badge.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    """Токены темы. Все значения — hex-строки вида #RRGGBB."""

    bg: str            # фон окна
    surface: str       # фон "приподнятых" поверхностей: поля ввода, карточки
    surface_alt: str   # альтернативная поверхность: кнопки, шапки таблиц
    text: str          # основной текст
    text_muted: str    # вторичный текст (подписи, подсказки)
    accent: str        # акцент: фокус, выделение, ссылки
    danger: str        # ошибка / необратимое действие
    success: str       # успех
    border: str        # рамки и разделители
    warning: str       # предупреждение (нужен бейджу badge-warn; не в K1-минимуме)


# Тёмная тема — по умолчанию. Согласована с painter-токенами канваса графа
# (SCENE_BG #1E1E1E, NODE_BG #2B2B2B, NODE_TEXT #ECECEC в graph_canvas/style.py),
# чтобы хром приложения не спорил с холстом.
DARK = Palette(
    bg="#1E1E1E",
    surface="#2B2B2B",
    surface_alt="#363636",
    text="#ECECEC",
    text_muted="#9AA0A6",
    accent="#4F8EF7",
    danger="#E5534B",
    success="#3FB950",
    border="#3D3D3D",
    warning="#F5B041",
)

LIGHT = Palette(
    bg="#F5F6F8",
    surface="#FFFFFF",
    surface_alt="#E9EBEE",
    text="#1F2328",
    text_muted="#6E7681",
    accent="#2563EB",
    danger="#C62828",
    success="#1A7F37",
    border="#D0D5DB",
    warning="#9A6700",
)

_PALETTES: dict[str, Palette] = {"dark": DARK, "light": LIGHT}

DEFAULT_THEME_NAME = "dark"


def current_palette(name: str | None) -> Palette:
    """Палитра по имени темы; незнакомое имя откатывается к тёмной."""
    return _PALETTES.get((name or DEFAULT_THEME_NAME).strip().lower(), DARK)


def _rgba(hex_color: str, alpha: int) -> str:
    """'#RRGGBB' + альфа (0..255) → строка 'rgba(r, g, b, a)' для QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def build_qss(palette: Palette) -> str:
    """
    Глобальный стиль приложения из токенов палитры.

    Базовые правила покрывают стандартные виджеты; словарь классов K1 —
    семантические роли (title/subtitle/card/...), которые обе стороны
    навешивают через setProperty("class", ...).
    """
    p = palette
    # Тонированные подложки статус-бейджей: цвет уровня на четверть прозрачности.
    warn_bg = _rgba(p.warning, 46)
    error_bg = _rgba(p.danger, 46)
    badge_bg = _rgba(p.text_muted, 36)
    accent_soft = _rgba(p.accent, 60)

    return f"""
/* ============ база ============ */

QWidget {{
    background-color: {p.bg};
    color: {p.text};
}}

QLabel, QCheckBox, QRadioButton {{
    background: transparent;
}}

QToolTip {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    padding: 4px 6px;
}}

/* ---- кнопки ---- */

QPushButton {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    border-color: {p.accent};
}}
QPushButton:pressed {{
    background-color: {p.surface};
}}
QPushButton:disabled {{
    color: {p.text_muted};
    background-color: {p.bg};
}}

QToolButton {{
    background-color: transparent;
    color: {p.text};
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 10px;
}}
QToolButton:hover {{
    background-color: {p.surface_alt};
    border-color: {p.border};
}}
QToolButton:pressed {{
    background-color: {p.surface};
}}

/* ---- поля ввода ---- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 4px 6px;
    selection-background-color: {accent_soft};
    selection-color: {p.text};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p.accent};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    color: {p.text_muted};
    background-color: {p.bg};
}}

QComboBox {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 4px 6px;
}}
QComboBox:focus {{
    border-color: {p.accent};
}}
QComboBox QAbstractItemView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    selection-background-color: {accent_soft};
    selection-color: {p.text};
}}

/* ---- списки, таблицы, вкладки ---- */

QListWidget, QListView, QTreeView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 6px;
}}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected {{
    background-color: {accent_soft};
    color: {p.text};
}}
QListWidget::item:hover, QListView::item:hover {{
    background-color: {p.surface_alt};
}}

QTableWidget, QTableView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    gridline-color: {p.border};
    alternate-background-color: {p.surface_alt};
    selection-background-color: {accent_soft};
    selection-color: {p.text};
}}
QHeaderView::section {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    padding: 4px 6px;
}}
QTableCornerButton::section {{
    background-color: {p.surface_alt};
    border: none;
}}

QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: {p.bg};
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 5px 12px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {p.surface};
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QTabBar::tab:hover:!selected {{
    color: {p.text};
}}

/* ---- прокрутка и обвязка ---- */

QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {p.border};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {p.text_muted};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}

QSplitter::handle {{
    background-color: {p.border};
}}

QMenu {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
}}
QMenu::item:selected {{
    background-color: {accent_soft};
}}

QStatusBar {{
    background-color: {p.surface};
    color: {p.text_muted};
}}

/* ============ словарь классов K1 ============ */

QWidget[class="title"] {{
    font-size: 16pt;
    font-weight: bold;
    background: transparent;
}}

QWidget[class="subtitle"] {{
    font-size: 11pt;
    color: {p.text_muted};
    background: transparent;
}}

QWidget[class="card"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 8px;
}}

QWidget[class="toolbar"] {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
}}

QWidget[class="toolbtn"] {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 10px;
}}
QWidget[class="toolbtn"]:hover {{
    background-color: {p.surface_alt};
    border-color: {p.border};
}}
QWidget[class="toolbtn"]:pressed {{
    background-color: {p.bg};
}}

QWidget[class="badge"] {{
    background-color: {badge_bg};
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
}}

QWidget[class="badge-warn"] {{
    background-color: {warn_bg};
    color: {p.warning};
    border: 1px solid {p.warning};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
}}

QWidget[class="badge-error"] {{
    background-color: {error_bg};
    color: {p.danger};
    border: 1px solid {p.danger};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
}}

QWidget[class="danger"] {{
    color: {p.danger};
    border: 1px solid {p.danger};
    background-color: transparent;
    border-radius: 6px;
    padding: 5px 12px;
}}
QWidget[class="danger"]:hover {{
    background-color: {error_bg};
}}

QWidget[class="muted"] {{
    color: {p.text_muted};
    background: transparent;
}}

/* расширение: акцентный текст (например, статус завершения сессии) */
QWidget[class="accent"] {{
    color: {p.accent};
    font-weight: 600;
    background: transparent;
}}

/* ============ структурные классы (волна E) ============ */
/* Базовые значения от Opus; тонкую визуальную настройку ведёт Fable. */

/* Боковая панель главного окна */
QWidget[class="sidebar"] {{
    background-color: {p.surface};
    border-right: 1px solid {p.border};
}}

/* Бренд-надпись (крупнее title, «лицо» приложения) */
QWidget[class="brand"] {{
    font-size: 18pt;
    font-weight: bold;
    color: {p.text};
    background: transparent;
}}

/* Первичная (акцентная) кнопка — главное действие экрана */
QPushButton[class="primary"] {{
    background-color: {p.accent};
    color: #FFFFFF;
    border: 1px solid {p.accent};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton[class="primary"]:hover {{
    border-color: {p.text};
}}
QPushButton[class="primary"]:pressed {{
    background-color: {accent_soft};
}}
QPushButton[class="primary"]:disabled {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    border-color: {p.border};
}}
QToolButton[class="primary"] {{
    background-color: {p.accent};
    color: #FFFFFF;
    border: 1px solid {p.accent};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}}
QToolButton[class="primary"]:hover {{
    border-color: {p.text};
}}
QToolButton[class="primary"]::menu-indicator {{
    image: none;
    width: 0;
}}

/* Кнопка-ссылка (плоская, акцентный текст) — второстепенная навигация */
QPushButton[class="link"] {{
    background: transparent;
    border: none;
    color: {p.accent};
    padding: 2px 4px;
    text-decoration: underline;
}}
QPushButton[class="link"]:hover {{
    color: {p.text};
}}

/* Чип-метка (тип раздела и т.п.) — компактнее бейджа, информативный */
QWidget[class="chip"] {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 8pt;
}}

/* Крупный центрированный placeholder пустого состояния */
QWidget[class="empty"] {{
    color: {p.text_muted};
    font-size: 11pt;
    background: transparent;
}}
"""


def apply_theme(app, name: str = DEFAULT_THEME_NAME) -> None:
    """
    Применить тему к приложению: app.setStyleSheet(build_qss(палитра)).

    `name` — "dark" | "light" (иное имя тихо откатывается к "dark").
    Точка вызова — main.py после создания QApplication:
        apply_theme(app, settings.get_theme())
    """
    app.setStyleSheet(build_qss(current_palette(name)))
