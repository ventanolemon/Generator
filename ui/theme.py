"""
Тема приложения — контракт K1 плана docs/ui_rework_plan.md (владелец Fable).

Дизайн-язык «Graphite & Iris»: глубокий холодный графит поверхностей
(чуть темнее холста графа, чтобы хром отступал, а канвас читался как
«документ») и фирменный ирисовый акцент — сдержанный, но узнаваемый.

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
    badge, badge-warn, badge-error, danger, muted,
    accent, sidebar, brand, primary, link, chip, empty

Расширения волны E (визуальная идентичность, тем же механизмом):

    hero        — брендовая панель (градиентная подложка входа/регистрации)
    hero-brand  — крупный wordmark на hero-панели
    hero-sub    — подпись/слоган на hero-панели
    logo-badge  — квадратный знак-логотип (глиф на акцентном градиенте)
    field-label — маленькая надпись над полем формы (разреженный трекинг)
    error-banner— плашка ошибки валидации (тонированная, со скруглением)
    ghost       — тихая второстепенная кнопка (контурная)

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


# Тёмная тема — по умолчанию. Хром на полтона глубже холста графа
# (SCENE_BG #1E1E1E, NODE_BG #2B2B2B, NODE_TEXT #ECECEC в graph_canvas/style.py):
# одна графитовая температура, канвас читается как рабочий «лист».
DARK = Palette(
    bg="#1A1B1E",
    surface="#232428",
    surface_alt="#2E3036",
    text="#EDEEF2",
    text_muted="#A2A7B4",
    accent="#8A8FF8",
    danger="#F0716B",
    success="#57C793",
    border="#383A41",
    warning="#F2B354",
)

LIGHT = Palette(
    bg="#F4F4F7",
    surface="#FFFFFF",
    surface_alt="#E9EAF0",
    text="#1B1C21",
    text_muted="#676C7A",
    accent="#4F52C4",
    danger="#C13A34",
    success="#17784A",
    border="#D6D8E0",
    warning="#915F00",
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


def _mix(a: str, b: str, t: float) -> str:
    """Линейная смесь двух hex-цветов: t=0 → a, t=1 → b."""
    ha, hb = a.lstrip("#"), b.lstrip("#")
    parts = []
    for i in (0, 2, 4):
        ca, cb = int(ha[i:i + 2], 16), int(hb[i:i + 2], 16)
        parts.append(round(ca + (cb - ca) * t))
    return "#{:02X}{:02X}{:02X}".format(*parts)


def build_qss(palette: Palette) -> str:
    """
    Глобальный стиль приложения из токенов палитры.

    Базовые правила покрывают стандартные виджеты; словарь классов K1 —
    семантические роли (title/subtitle/card/...), которые обе стороны
    навешивают через setProperty("class", ...).
    """
    p = palette
    h = p.bg.lstrip("#")
    bg_lum = (0.2126 * int(h[0:2], 16) + 0.7152 * int(h[2:4], 16)
              + 0.0722 * int(h[4:6], 16))
    dark = bg_lum < 128  # тёмная ли палитра (по яркости фона)

    # --- производные состояния (вычисляем, а не плодим токены) ---
    # Кнопки: hover чуть светлее поверхности, pressed чуть глубже.
    btn_hover = _mix(p.surface_alt, p.text, 0.07)
    btn_press = _mix(p.surface_alt, p.bg, 0.45)
    # Первичная кнопка: вертикальный градиент от светлого к базовому акценту.
    prim_base = _mix(p.accent, p.bg, 0.18) if dark else p.accent
    prim_hi = _mix(prim_base, "#FFFFFF", 0.10)
    prim_hover_hi = _mix(prim_base, "#FFFFFF", 0.18)
    prim_press = _mix(prim_base, "#000000", 0.16)
    # Подложки выделения/ховера списков.
    sel_bg = _rgba(p.accent, 56 if dark else 44)
    row_hover = _rgba(p.text, 14)
    # Тонированные подложки статус-бейджей.
    warn_bg = _rgba(p.warning, 42)
    error_bg = _rgba(p.danger, 40)
    ok_bg = _rgba(p.success, 40)
    badge_bg = _rgba(p.text_muted, 32)
    accent_soft = _rgba(p.accent, 60)
    # Hero-панель: диагональный градиент с ирисовым подтоном.
    hero_a = _mix(p.accent, p.bg, 0.80 if dark else 0.78)
    hero_b = _mix(p.accent, p.bg, 0.94 if dark else 0.92)
    # Знак-логотип: акцентный градиент.
    logo_a = _mix(p.accent, "#FFFFFF", 0.12)
    logo_b = _mix(p.accent, "#000000", 0.22)

    return f"""
/* ==================== база ==================== */

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
    border-radius: 6px;
    padding: 5px 8px;
}}

/* ---- кнопки: спокойная поверхность, ясные состояния ---- */

QPushButton {{
    background-color: {p.surface_alt};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {btn_hover};
    border-color: {_rgba(p.accent, 150)};
}}
QPushButton:pressed {{
    background-color: {btn_press};
    border-color: {p.border};
}}
QPushButton:disabled {{
    color: {_rgba(p.text_muted, 150)};
    background-color: {_mix(p.surface_alt, p.bg, 0.55)};
    border-color: {_rgba(p.border, 140)};
}}
QPushButton:focus {{
    border-color: {p.accent};
}}

QToolButton {{
    background-color: transparent;
    color: {p.text};
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 10px;
}}
QToolButton:hover {{
    background-color: {p.surface_alt};
    border-color: {p.border};
}}
QToolButton:pressed {{
    background-color: {btn_press};
}}
QToolButton:disabled {{
    color: {_rgba(p.text_muted, 150)};
}}

/* ---- поля ввода: компенсированный 2px фокус-обвод акцентом ---- */

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {accent_soft};
    selection-color: {p.text};
}}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {_mix(p.border, p.accent, 0.45)};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 2px solid {p.accent};
    padding: 5px 9px;
    background-color: {_mix(p.surface, p.accent, 0.04)};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    color: {p.text_muted};
    background-color: {_mix(p.surface, p.bg, 0.6)};
}}
QLineEdit[echoMode="2"] {{
    lineedit-password-character: 9679;
}}

QComboBox {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 6px 10px;
}}
QComboBox:hover {{
    border-color: {_mix(p.border, p.accent, 0.45)};
}}
QComboBox:focus {{
    border: 2px solid {p.accent};
    padding: 5px 9px;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 8px;
    selection-background-color: {sel_bg};
    selection-color: {p.text};
    padding: 4px;
}}

/* ---- списки, таблицы, вкладки ---- */

QListWidget, QListView, QTreeView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}
QListWidget::item, QListView::item {{
    border-radius: 6px;
    padding: 5px 8px;
    margin: 1px 2px;
}}
QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover {{
    background-color: {row_hover};
}}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected {{
    background-color: {sel_bg};
    color: {p.text};
}}

QTableWidget, QTableView {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 10px;
    gridline-color: {_rgba(p.border, 160)};
    alternate-background-color: {_mix(p.surface, p.surface_alt, 0.45)};
    selection-background-color: {sel_bg};
    selection-color: {p.text};
}}
QHeaderView::section {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    border: none;
    border-right: 1px solid {p.border};
    border-bottom: 1px solid {p.border};
    padding: 5px 8px;
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {p.surface_alt};
    border: none;
}}

QTabWidget::pane {{
    border: 1px solid {p.border};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p.text_muted};
    border: none;
    border-bottom: 2px solid transparent;
    padding: 7px 14px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    color: {p.text};
    border-bottom: 2px solid {_rgba(p.accent, 90)};
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
    width: 8px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {_rgba(p.text_muted, 110)};
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {_rgba(p.text_muted, 200)};
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
QSplitter::handle:hover {{
    background-color: {_rgba(p.accent, 140)};
}}

QMenu {{
    background-color: {p.surface};
    color: {p.text};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    border-radius: 5px;
    padding: 5px 22px 5px 12px;
}}
QMenu::item:selected {{
    background-color: {sel_bg};
}}
QMenu::separator {{
    height: 1px;
    background: {p.border};
    margin: 4px 8px;
}}

QStatusBar {{
    background-color: {p.surface};
    color: {p.text_muted};
    border-top: 1px solid {p.border};
}}

QGroupBox {{
    border: 1px solid {p.border};
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {p.text_muted};
}}

QProgressBar {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 7px;
    text-align: center;
    color: {p.text};
}}
QProgressBar::chunk {{
    background-color: {p.accent};
    border-radius: 6px;
}}

/* ==================== словарь классов K1 ==================== */

QWidget[class="title"] {{
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0.2px;
    background: transparent;
}}

QWidget[class="subtitle"] {{
    font-size: 10.5pt;
    color: {p.text_muted};
    background: transparent;
}}

QWidget[class="card"] {{
    background-color: {p.surface};
    border: 1px solid {p.border};
    border-radius: 12px;
}}

QWidget[class="toolbar"] {{
    background-color: {p.surface};
    border-bottom: 1px solid {p.border};
}}

QWidget[class="toolbtn"] {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px 10px;
}}
QWidget[class="toolbtn"]:hover {{
    background-color: {p.surface_alt};
    border-color: {p.border};
}}
QWidget[class="toolbtn"]:pressed {{
    background-color: {btn_press};
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
    border: 1px solid {_rgba(p.warning, 170)};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
}}

QWidget[class="badge-error"] {{
    background-color: {error_bg};
    color: {p.danger};
    border: 1px solid {_rgba(p.danger, 170)};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
}}

/* успешный вердикт (например, критик «принять») */
QWidget[class="badge-ok"] {{
    background-color: {ok_bg};
    color: {p.success};
    border: 1px solid {_rgba(p.success, 170)};
    border-radius: 9px;
    padding: 2px 10px;
    font-size: 9pt;
    font-weight: 600;
}}

QWidget[class="danger"] {{
    color: {p.danger};
    border: 1px solid {_rgba(p.danger, 170)};
    background-color: transparent;
    border-radius: 8px;
    padding: 5px 12px;
}}
QWidget[class="danger"]:hover {{
    background-color: {error_bg};
    border-color: {p.danger};
}}

QWidget[class="muted"] {{
    color: {p.text_muted};
    background: transparent;
}}

/* акцентный текст (например, статус завершения сессии) */
QWidget[class="accent"] {{
    color: {p.accent};
    font-weight: 600;
    background: transparent;
}}

/* ==================== структурные классы (волна E) ==================== */

/* Боковая панель главного окна */
QWidget[class="sidebar"] {{
    background-color: {p.surface};
    border-right: 1px solid {p.border};
}}
QWidget[class="sidebar"] QListWidget,
QWidget[class="sidebar"] QListView {{
    background: transparent;
    border: none;
}}

/* Бренд-надпись (крупнее title, «лицо» приложения) */
QWidget[class="brand"] {{
    font-size: 18pt;
    font-weight: 800;
    letter-spacing: 0.6px;
    color: {p.text};
    background: transparent;
}}

/* Первичная (акцентная) кнопка — главное действие экрана */
QPushButton[class="primary"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {prim_hi}, stop:1 {prim_base});
    color: #FFFFFF;
    border: 1px solid {_mix(prim_base, "#000000", 0.18)};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
    letter-spacing: 0.2px;
}}
QPushButton[class="primary"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {prim_hover_hi}, stop:1 {_mix(prim_base, "#FFFFFF", 0.08)});
}}
QPushButton[class="primary"]:pressed {{
    background-color: {prim_press};
}}
QPushButton[class="primary"]:disabled {{
    background-color: {p.surface_alt};
    color: {p.text_muted};
    border-color: {p.border};
}}
QPushButton[class="primary"]:focus {{
    border: 1px solid {_mix(p.accent, "#FFFFFF", 0.5)};
}}
QToolButton[class="primary"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {prim_hi}, stop:1 {prim_base});
    color: #FFFFFF;
    border: 1px solid {_mix(prim_base, "#000000", 0.18)};
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: 600;
}}
QToolButton[class="primary"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {prim_hover_hi}, stop:1 {_mix(prim_base, "#FFFFFF", 0.08)});
}}
QToolButton[class="primary"]:pressed {{
    background-color: {prim_press};
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
    font-weight: 500;
}}
QPushButton[class="link"]:hover {{
    color: {_mix(p.accent, p.text, 0.5)};
    text-decoration: underline;
}}
QPushButton[class="link"]:pressed {{
    color: {p.text_muted};
}}

/* Тихая второстепенная кнопка — контурная, не спорит с primary */
QPushButton[class="ghost"] {{
    background: transparent;
    color: {p.text_muted};
    border: 1px solid {p.border};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton[class="ghost"]:hover {{
    color: {p.text};
    border-color: {_mix(p.border, p.accent, 0.55)};
    background-color: {_rgba(p.text, 10)};
}}
QPushButton[class="ghost"]:pressed {{
    background-color: {btn_press};
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

/* ==================== фирменные классы (Wave E, Fable) ==================== */

/* Hero-панель входа/регистрации: диагональный ирисовый градиент */
QWidget[class="hero"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {hero_a}, stop:0.55 {hero_b}, stop:1 {p.bg});
    border-right: 1px solid {p.border};
}}

/* Wordmark на hero-панели */
QWidget[class="hero-brand"] {{
    font-size: 21pt;
    font-weight: 800;
    letter-spacing: 0.8px;
    color: {p.text};
    background: transparent;
}}

/* Слоган/подпись на hero-панели */
QWidget[class="hero-sub"] {{
    font-size: 10.5pt;
    color: {p.text_muted};
    background: transparent;
}}

/* Квадратный знак-логотип: глиф на акцентном градиенте */
QWidget[class="logo-badge"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {logo_a}, stop:1 {logo_b});
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    font-size: 17pt;
    font-weight: 800;
}}

/* Маленькая надпись над полем формы */
QWidget[class="field-label"] {{
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 1.1px;
    color: {p.text_muted};
    background: transparent;
}}

/* Плашка ошибки валидации */
QWidget[class="error-banner"] {{
    background-color: {error_bg};
    color: {p.danger};
    border: 1px solid {_rgba(p.danger, 150)};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 9.5pt;
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
