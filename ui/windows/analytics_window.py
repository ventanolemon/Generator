"""
AnalyticsWindow — дашборд успеваемости преподавателя/админа
(docs/ui_rework_plan.md; визуальный референс — Fable-артефакт
analytics_dashboard.html).

Тянет агрегаты с сервера (AnalyticsClient.overview → /analytics/overview) и
показывает:
  * KPI-плитки: попытки, активные студенты, доля верных, активные задания —
    с дельтами к предыдущему периоду той же длины;
  * динамику по дням (столбцы попыток с «верной» частью снизу);
  * распределение студентов по личной доле верных (5 корзин);
  * таблицы: задания (сложность), студенты (статус), группы (охват).
Период (7/30/90 дней) и фильтр по группе — управляются сверху, меняют
пере-запрос.

Скоуп считает сервер (teacher — свои + системные предметы, admin — все);
идентичность обязательна. Окно доступно teacher/admin с заданным адресом
сервера — иначе заглушка. HTTP-вызовы — в фоновом _CallWorker (паттерн
contour/admin-окон). Немодальный синглтон; refresh() дёшев.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.analytics import AnalyticsError
from ui.app_context import AppContext
from ui.theme import current_palette
from ui.widgets.bar_chart import Bar, BarChart

# Период → подпись.
_RANGES = ((7, "7 дней"), (30, "30 дней"), (90, "90 дней"))

_TYPE_LABELS = {"graph": "Граф", "test": "Тест"}
_DIFFICULTY_LABELS = {"easy": "лёгкое", "medium": "среднее", "hard": "трудное"}
_STATUS_LABELS = {"struggling": "отстаёт", "steady": "ровно",
                  "strong": "уверенно"}


class _CallWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)   # (message, status)

    def __init__(self, fn: Callable[[], object], parent: QWidget | None = None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn())
        except AnalyticsError as e:
            self.failed.emit((str(e), getattr(e, "status", None)))
        except Exception as e:
            self.failed.emit((f"аналитика: {e}", None))


class _KpiTile(QFrame):
    """Плитка-карточка: крупное значение + подпись + дельта (цвет по знаку)."""

    def __init__(self, caption: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("class", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(2)
        self.value_label = QLabel("—", self)
        self.value_label.setProperty("class", "title")
        lay.addWidget(self.value_label)
        cap = QLabel(caption, self)
        cap.setProperty("class", "muted")
        lay.addWidget(cap)
        self.delta_label = QLabel("", self)
        self.delta_label.setProperty("class", "muted")
        lay.addWidget(self.delta_label)

    def set_value(self, value: str, delta_text: str = "",
                  delta_level: str = "") -> None:
        self.value_label.setText(value)
        self.delta_label.setText(delta_text)
        cls = {"up": "accent", "down": "danger"}.get(delta_level, "muted")
        self.delta_label.setProperty("class", cls)
        self.delta_label.style().unpolish(self.delta_label)
        self.delta_label.style().polish(self.delta_label)


class AnalyticsWindow(QWidget):
    """Дашборд успеваемости: KPI, динамика, распределение, таблицы."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = getattr(context, "analytics_client", None)
        self._worker: Optional[_CallWorker] = None
        self._groups_known: list[str] = []

        self.setWindowTitle("Аналитика успеваемости")
        self.resize(860, 720)
        self._build_ui()
        self._apply_palette()
        self.refresh()

    # ---------- сборка ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # Шапка: заголовок + управление периодом/группой.
        header = QHBoxLayout()
        title = QLabel("Аналитика успеваемости", self)
        title.setProperty("class", "title")
        header.addWidget(title)
        header.addStretch(1)
        self.range_combo = QComboBox(self)
        for days, label in _RANGES:
            self.range_combo.addItem(label, days)
        self.range_combo.setCurrentIndex(1)  # 30 дней
        self.range_combo.currentIndexChanged.connect(lambda *_: self._load())
        header.addWidget(self.range_combo)
        self.group_combo = QComboBox(self)
        self.group_combo.addItem("Все группы", None)
        self.group_combo.currentIndexChanged.connect(lambda *_: self._load())
        header.addWidget(self.group_combo)
        self.reload_btn = QPushButton("Обновить", self)
        self.reload_btn.clicked.connect(self._load)
        header.addWidget(self.reload_btn)
        root.addLayout(header)

        self.error_label = QLabel("", self)
        self.error_label.setProperty("class", "danger")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)

        # Прокручиваемое тело.
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self.body = QWidget(scroll)
        body_lay = QVBoxLayout(self.body)
        body_lay.setSpacing(12)

        # KPI-плитки.
        self.kpi_row = QGridLayout()
        self.kpi_row.setSpacing(10)
        self.tile_attempts = _KpiTile("Попыток", self.body)
        self.tile_students = _KpiTile("Активных студентов", self.body)
        self.tile_rate = _KpiTile("Доля верных", self.body)
        self.tile_tasks = _KpiTile("Активных заданий", self.body)
        for i, tile in enumerate((self.tile_attempts, self.tile_students,
                                  self.tile_rate, self.tile_tasks)):
            self.kpi_row.addWidget(tile, 0, i)
        body_lay.addLayout(self.kpi_row)

        # Динамика.
        self.timeseries_caption = QLabel("Динамика по дням", self.body)
        self.timeseries_caption.setProperty("class", "subtitle")
        body_lay.addWidget(self.timeseries_caption)
        self.timeseries_chart = BarChart(self.body)
        body_lay.addWidget(self.timeseries_chart)
        self.timeseries_legend = QLabel(
            "столбец — попытки, зелёная часть — верные", self.body)
        self.timeseries_legend.setProperty("class", "muted")
        body_lay.addWidget(self.timeseries_legend)

        # Распределение.
        self.dist_caption = QLabel(
            "Распределение студентов по доле верных", self.body)
        self.dist_caption.setProperty("class", "subtitle")
        body_lay.addWidget(self.dist_caption)
        self.dist_chart = BarChart(self.body)
        body_lay.addWidget(self.dist_chart)

        # Таблицы.
        self.tabs = QTabWidget(self.body)
        self.tasks_table = self._make_table(
            ["Задание", "Предмет", "Тип", "Попыток", "Верно", "Ср. попыток",
             "Студентов", "Сложность"])
        self.students_table = self._make_table(
            ["Студент", "Группа", "Попыток", "Верно", "Статус"])
        self.groups_table = self._make_table(
            ["Группа", "Студентов", "Попыток", "Верно", "Охват"])
        self.tabs.addTab(self.tasks_table, "Задания")
        self.tabs.addTab(self.students_table, "Студенты")
        self.tabs.addTab(self.groups_table, "Группы")
        body_lay.addWidget(self.tabs, stretch=1)

        scroll.setWidget(self.body)
        root.addWidget(scroll, stretch=1)

        # Пустое/недоступное состояние.
        self.notice_label = QLabel("", self)
        self.notice_label.setProperty("class", "muted")
        self.notice_label.setWordWrap(True)
        self.notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice_label.hide()
        root.addWidget(self.notice_label)

    def _make_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers), self.body)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        table.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)
        return table

    def _apply_palette(self) -> None:
        name = None
        try:
            name = self.ctx.settings.get_theme()
        except Exception:
            pass
        p = current_palette(name)
        for chart in (self.timeseries_chart, self.dist_chart):
            chart.set_colors(accent=p.accent, filled=p.success,
                             text_muted=p.text_muted, track=p.surface_alt)

    # ---------- публичное обновление ----------

    def refresh(self) -> None:
        if self.client is None or not self.client.can_use():
            self._show_notice(self._disabled_reason())
            return
        self._apply_palette()
        self._load()

    def _disabled_reason(self) -> str:
        if self.client is None or not self.client.has_server():
            return ("Аналитика недоступна: адрес сервера не задан.\n"
                    "Укажите его в Настройках (вкладка «Соединение»).")
        return ("Аналитика доступна преподавателям и администраторам.\n"
                "Ваша текущая роль — студент.")

    def _show_notice(self, text: str, *, hide_controls: bool = True) -> None:
        """Показать заглушку вместо тела. hide_controls=True прячет и
        селекторы (недоступно/нет сервера); False оставляет их (пустой период
        — пользователь может сменить диапазон/группу)."""
        self.notice_label.setText(text)
        self.notice_label.show()
        self.body.setVisible(False)
        for w in (self.range_combo, self.group_combo, self.reload_btn):
            w.setVisible(not hide_controls)

    def _set_body_visible(self, visible: bool) -> None:
        self.body.setVisible(visible)
        for w in (self.range_combo, self.group_combo, self.reload_btn):
            w.setVisible(visible)

    # ---------- загрузка ----------

    def _load(self) -> None:
        if self.client is None or self._worker is not None:
            return
        self.notice_label.hide()
        self.error_label.hide()
        self.progress.show()
        days = self.range_combo.currentData() or 30
        group = self.group_combo.currentData()
        self._start_call(
            lambda: self.client.overview(int(days), group),
            self._on_loaded, self._on_error)

    def _on_loaded(self, data: object) -> None:
        self.progress.hide()
        if not isinstance(data, dict):
            return
        totals = data.get("totals") or {}
        self._sync_group_combo(data.get("groups") or [])
        if int(totals.get("attempts", 0)) == 0 and \
                self.group_combo.currentData() is None:
            self._show_notice(
                "Пока нет ни одной попытки в выбранном периоде.\n"
                "Данные появятся, когда студенты начнут решать задания.",
                hide_controls=False)
            return
        self.notice_label.hide()
        self._set_body_visible(True)
        self._render_kpis(totals)
        self._render_timeseries(data.get("timeseries") or [])
        self._render_distribution(data.get("correctness_distribution") or [])
        self._render_tasks(data.get("tasks") or [])
        self._render_students(data.get("students") or [])
        self._render_groups(data.get("groups") or [])

    def _on_error(self, err: object) -> None:
        self.progress.hide()
        message, _status = err
        self.error_label.setText(message)
        self.error_label.show()

    # ---------- рендер ----------

    def _render_kpis(self, totals: dict) -> None:
        self.tile_attempts.set_value(
            str(totals.get("attempts", 0)),
            *self._delta_ratio(totals.get("attempts_delta_pct")))
        self.tile_students.set_value(str(totals.get("students_active", 0)))
        self.tile_rate.set_value(
            self._fmt_pct(totals.get("correct_rate")),
            *self._delta_points(totals.get("correct_rate_delta")))
        self.tile_tasks.set_value(str(totals.get("tasks_active", 0)))

    def _render_timeseries(self, series: list) -> None:
        bars = [Bar(label=self._short_date(p.get("date", "")),
                    total=float(p.get("attempts", 0)),
                    filled=float(p.get("correct", 0))) for p in series]
        self.timeseries_chart.set_data(bars)

    def _render_distribution(self, dist: list) -> None:
        bars = [Bar(label=str(b.get("bucket", "")),
                    total=float(b.get("students", 0))) for b in dist]
        self.dist_chart.set_data(bars)

    def _render_tasks(self, tasks: list) -> None:
        self.tasks_table.setRowCount(0)
        for t in tasks:
            self._append_row(self.tasks_table, [
                str(t.get("name", "")),
                str(t.get("subject", "")),
                _TYPE_LABELS.get(t.get("type"), str(t.get("type", ""))),
                str(t.get("attempts", 0)),
                self._fmt_pct(t.get("correct_rate")),
                self._fmt_num(t.get("avg_attempts_to_correct")),
                str(t.get("students", 0)),
                _DIFFICULTY_LABELS.get(t.get("difficulty"),
                                       str(t.get("difficulty", ""))),
            ])

    def _render_students(self, students: list) -> None:
        self.students_table.setRowCount(0)
        for s in students:
            fio = str(s.get("fio", "")) or str(s.get("login", ""))
            self._append_row(self.students_table, [
                f"{fio}\n{s.get('login', '')}",
                str(s.get("group", "")) or "—",
                str(s.get("attempts", 0)),
                self._fmt_pct(s.get("correct_rate")),
                _STATUS_LABELS.get(s.get("status"), str(s.get("status", ""))),
            ])

    def _render_groups(self, groups: list) -> None:
        self.groups_table.setRowCount(0)
        for g in groups:
            self._append_row(self.groups_table, [
                str(g.get("group", "")),
                str(g.get("students", 0)),
                str(g.get("attempts", 0)),
                self._fmt_pct(g.get("correct_rate")),
                self._fmt_pct(g.get("coverage")),
            ])

    @staticmethod
    def _append_row(table: QTableWidget, values: list[str]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for col, val in enumerate(values):
            table.setItem(row, col, QTableWidgetItem(val))

    def _sync_group_combo(self, groups: list) -> None:
        names = [str(g.get("group", "")) for g in groups if g.get("group")]
        if names == self._groups_known:
            return
        self._groups_known = names
        current = self.group_combo.currentData()
        self.group_combo.blockSignals(True)
        self.group_combo.clear()
        self.group_combo.addItem("Все группы", None)
        for name in names:
            self.group_combo.addItem(name, name)
        if current is not None:
            idx = self.group_combo.findData(current)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
        self.group_combo.blockSignals(False)

    # ---------- форматирование ----------

    @staticmethod
    def _fmt_pct(x) -> str:
        if x is None:
            return "—"
        try:
            return f"{round(float(x) * 100)}%"
        except (TypeError, ValueError):
            return "—"

    @staticmethod
    def _fmt_num(x) -> str:
        if x is None:
            return "—"
        try:
            return f"{float(x):.1f}"
        except (TypeError, ValueError):
            return "—"

    def _delta_ratio(self, x) -> tuple[str, str]:
        """Дельта-доля (attempts_delta_pct: -1..+∞) → («+12%», уровень)."""
        if x is None:
            return "", ""
        pct = round(float(x) * 100)
        level = "up" if pct > 0 else "down" if pct < 0 else ""
        sign = "+" if pct > 0 else ""
        return f"{sign}{pct}% к прошлому периоду", level

    def _delta_points(self, x) -> tuple[str, str]:
        """Дельта доли верных (абсолютная, -1..1) → («+3 п.п.», уровень)."""
        if x is None:
            return "", ""
        pts = round(float(x) * 100)
        level = "up" if pts > 0 else "down" if pts < 0 else ""
        sign = "+" if pts > 0 else ""
        return f"{sign}{pts} п.п. к прошлому периоду", level

    @staticmethod
    def _short_date(iso: str) -> str:
        # "2026-07-12" → "07-12"
        return iso[5:] if len(iso) >= 10 else iso

    # ---------- воркер ----------

    def _start_call(self, fn: Callable[[], object],
                    on_done: Callable[[object], None],
                    on_failed: Callable[[object], None]) -> None:
        if self._worker is not None:
            return
        worker = _CallWorker(fn, self)
        self._worker = worker

        def _done(result: object) -> None:
            self._worker = None
            on_done(result)

        def _failed(err: object) -> None:
            self._worker = None
            on_failed(err)

        worker.done.connect(_done)
        worker.failed.connect(_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()
