"""
SyncWindow — окно офлайн-синхронизации (B3 плана docs/ui_rework_plan.md).

Показывает состояние синка и даёт две ручки:
  * «Синхронизировать сейчас» — прогон SyncClient.sync() push→pull.
    sync() блокирующий (urllib + SQLite), поэтому выполняется в фоновом
    QThread (_SyncWorker); результат (SyncReport) возвращается в UI-поток
    Qt-сигналом — виджеты из воркера не трогаются.
  * Разрешение конфликтов: список sync_conflicts с компактным сравнением
    «моя ↔ серверная» и кнопками «Оставить мою» / «Принять серверную»
    (SyncClient.resolve_conflict).

Окно немодальное, живёт синглтоном у главного окна (как StatsWindow):
данные снимаются при показе/действии, публичный refresh() пересчитывает
статус, счётчик очереди и список конфликтов.

Для бейджа в TopBar есть модульный помощник pending_badge_text(sync_client)
— короткая сводка (text, level) для TopBar.set_badge("sync", ...).
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.sync import SyncReport
from ui.app_context import AppContext

# Человекочитаемые имена видов сущностей в карточке конфликта.
_KIND_LABELS = {"partition": "раздел", "subject": "предмет"}

# Поля версий, которые сравниваем в карточке (по порядку показа).
_COMPARE_FIELDS = (
    ("partition_name", "Название"),
    ("subject_name", "Название предмета"),
    ("subject_id", "Предмет (id)"),
    ("constracted", "Собрано заданий"),
    ("generation_parametrs", "Параметры генерации"),
)


def pending_badge_text(sync_client) -> tuple[str, str]:
    """
    Короткая сводка состояния синка для статус-бейджа TopBar.

    Возвращает (text, level), где level ∈ {"", "warn", "error"} — ровно
    контракт TopBar.set_badge. Пустой text = «нечего показывать» (бейдж
    прячется): очередь пуста и конфликтов нет. Приоритет у конфликтов —
    они требуют действия пользователя.

        text, level = pending_badge_text(ctx.sync_client)
        top_bar.set_badge("sync", text, level)
    """
    if sync_client is None:
        return ("", "")
    conflicts = len(sync_client.store.unresolved_conflicts())
    if conflicts:
        return (f"конфликтов: {conflicts}", "error")
    pending = len(sync_client.store.pending())
    if pending:
        return (f"не синхр.: {pending}", "warn")
    return ("", "")


class _SyncWorker(QThread):
    """
    Фоновый прогон SyncClient.sync(). sync() блокирует (сеть + SQLite),
    но потокобезопасен относительно UI: каждый вызов store/repo открывает
    своё SQLite-соединение, глобального состояния нет. Результат уходит
    сигналом — Qt сам доставит его в UI-поток очередью событий.
    """

    finished_report = pyqtSignal(object)  # SyncReport
    # after — необязательный пост-шаг в том же фоне (обновление снимка выдач
    # предметов). Его ошибка не отменяет сам синк: контент уже приехал, просто
    # права остались прежними — это попадает в errors отчёта отдельной строкой.

    def __init__(self, client, parent: QWidget | None = None, *,
                 after: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self._client = client
        self._after = after

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            report = self._client.sync()
        except Exception as e:  # sync() сам ловит сеть; это страховка
            report = SyncReport(errors=[f"sync: {e}"])
        if self._after is not None:
            try:
                self._after()
            except Exception as e:
                report.errors.append(f"выдачи предметов: {e}")
        self.finished_report.emit(report)


class SyncWindow(QWidget):
    """Окно «Синхронизация»: статус, ручной запуск, разрешение конфликтов."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        # Отдельное top-level окно даже при заданном parent (как диалог,
        # но немодальное): parent держит время жизни, Qt — стекинг.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = context.sync_client
        self._worker: Optional[_SyncWorker] = None
        self._last_report: Optional[SyncReport] = None

        self.setWindowTitle("Синхронизация")
        self.resize(640, 560)
        self._build_ui()
        self.refresh()

    # ---------- сборка ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("Синхронизация", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        # --- статус-карточка: сервер, очередь, последний прогон ---
        card = QFrame(self)
        card.setProperty("class", "card")
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        def _row(row: int, caption: str) -> QLabel:
            cap = QLabel(caption, card)
            cap.setProperty("class", "muted")
            grid.addWidget(cap, row, 0, Qt.AlignmentFlag.AlignTop)
            value = QLabel("", card)
            value.setWordWrap(True)
            grid.addWidget(value, row, 1)
            return value

        self.server_label = _row(0, "Сервер:")
        self.pending_label = _row(1, "Очередь:")
        self.last_sync_label = _row(2, "Последний прогон:")
        grid.setColumnStretch(1, 1)
        root.addWidget(card)

        # --- ошибки последнего прогона (скрыты, пока их нет) ---
        self.errors_label = QLabel("", self)
        self.errors_label.setProperty("class", "danger")
        self.errors_label.setWordWrap(True)
        self.errors_label.hide()
        root.addWidget(self.errors_label)

        # --- действия ---
        actions = QHBoxLayout()
        self.sync_btn = QPushButton("Синхронизировать сейчас", self)
        self.sync_btn.clicked.connect(self._on_sync_clicked)
        actions.addWidget(self.sync_btn)
        actions.addStretch(1)
        self.close_btn = QPushButton("Закрыть", self)
        self.close_btn.clicked.connect(self.close)
        actions.addWidget(self.close_btn)
        root.addLayout(actions)

        # --- конфликты ---
        conflicts_title = QLabel("Конфликты", self)
        conflicts_title.setProperty("class", "subtitle")
        root.addWidget(conflicts_title)

        self.no_conflicts_label = QLabel("конфликтов нет", self)
        self.no_conflicts_label.setProperty("class", "muted")
        root.addWidget(self.no_conflicts_label)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        self._conflicts_host = QWidget(scroll)
        self.conflicts_layout = QVBoxLayout(self._conflicts_host)
        self.conflicts_layout.setContentsMargins(0, 0, 0, 0)
        self.conflicts_layout.setSpacing(8)
        self.conflicts_layout.addStretch(1)
        scroll.setWidget(self._conflicts_host)
        root.addWidget(scroll, stretch=1)

    # ---------- публичное обновление ----------

    def refresh(self) -> None:
        """Пересчитать статус (сервер/очередь), список конфликтов и кнопку.

        Дешёвая операция (два SELECT по локальной БД) — дергается при
        показе окна, после прогона sync и после разрешения конфликта.
        """
        self._refresh_status()
        self._rebuild_conflicts()

    def _refresh_status(self) -> None:
        base_url = self.ctx.settings.get_base_url() if self.ctx.settings else ""
        if base_url:
            self.server_label.setText(base_url)
            _set_class(self.server_label, "")
        else:
            self.server_label.setText("адрес не задан — задайте в Настройках")
            _set_class(self.server_label, "muted")

        if self.client is not None:
            n = len(self.client.store.pending())
            self.pending_label.setText(
                f"несинхронизированных изменений: {n}" if n
                else "все изменения отправлены")
        else:
            self.pending_label.setText("клиент синхронизации не настроен")

        if self._last_report is None and not self.last_sync_label.text():
            self.last_sync_label.setText("ещё не запускалась")
            _set_class(self.last_sync_label, "muted")

        # Кнопка активна, только когда есть куда синкать и нет прогона.
        can_sync = (self.client is not None and self.client.has_server()
                    and self._worker is None)
        self.sync_btn.setEnabled(can_sync)
        if self.client is None or not self.client.has_server():
            self.sync_btn.setToolTip(
                "Адрес сервера не задан — укажите его в Настройках.")
        else:
            self.sync_btn.setToolTip("")

    # ---------- прогон sync ----------

    def _on_sync_clicked(self) -> None:
        if self._worker is not None or self.client is None:
            return  # уже идёт
        self.sync_btn.setEnabled(False)
        self.last_sync_label.setText("выполняется…")
        _set_class(self.last_sync_label, "accent")

        self._worker = _SyncWorker(self.client, self,
                                   after=self._refresh_grants)
        self._worker.finished_report.connect(self._on_sync_finished)
        self._worker.start()

    def _refresh_grants(self) -> None:
        """
        Подтянуть выданные админом предметы — тем же фоном, что и синк.

        Синк уже привёз контент и scope-эпоху; здесь обновляется локальный
        снимок прав, которым фильтруется витрина встроенных предметов.
        Гостю и без адреса сервера обновлять нечего — refresh_into вернёт
        None, не ходя в сеть.
        """
        client = getattr(self.ctx, "grants_client", None)
        if client is None:
            return
        client.refresh_into(self.ctx.repo, self.ctx.user_id_provider())

    def _on_sync_finished(self, report: SyncReport) -> None:
        """Слот результата воркера — выполняется в UI-потоке."""
        self._last_report = report
        if self._worker is not None:
            self._worker.finished_report.disconnect(self._on_sync_finished)
            self._worker.deleteLater()
            self._worker = None

        stamp = time.strftime("%H:%M:%S")
        summary = (
            f"{stamp} — отправлено попыток: {report.pushed_attempts}, "
            f"принято правок: {report.accepted_entities}, "
            f"получено: {report.pulled_subjects} предм. / "
            f"{report.pulled_partitions} разд., "
            f"удалено: {report.deleted_applied}, "
            f"конфликтов: {report.conflicts}"
        )
        if report.ok:
            self.last_sync_label.setText(f"успешно. {summary}")
            _set_class(self.last_sync_label, "accent")
            self.errors_label.hide()
        else:
            self.last_sync_label.setText(f"завершилась с ошибками. {summary}")
            _set_class(self.last_sync_label, "")
            self.errors_label.setText(
                "Ошибки:\n" + "\n".join(f"• {e}" for e in report.errors))
            self.errors_label.show()

        self.refresh()

    # ---------- конфликты ----------

    def _rebuild_conflicts(self) -> None:
        # Снести старые карточки (последний элемент лейаута — растяжка).
        # setParent(None) отвязывает виджет немедленно — иначе он висит до
        # прогона deleteLater в цикле событий и «мигает» после разрешения.
        while self.conflicts_layout.count() > 1:
            item = self.conflicts_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

        conflicts = (self.client.store.unresolved_conflicts()
                     if self.client is not None else [])
        self.no_conflicts_label.setVisible(not conflicts)
        for conflict in conflicts:
            card = self._make_conflict_card(conflict)
            self.conflicts_layout.insertWidget(
                self.conflicts_layout.count() - 1, card)

    def _make_conflict_card(self, conflict: dict) -> QFrame:
        card = QFrame(self._conflicts_host)
        card.setProperty("class", "card")
        card.setProperty("conflict_id", conflict["id"])  # для тестов/отладки
        grid = QGridLayout(card)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        kind = _KIND_LABELS.get(conflict["entity_kind"],
                                conflict["entity_kind"])
        head = QLabel(f"{kind} #{conflict['entity_id']}", card)
        head.setProperty("class", "subtitle")
        grid.addWidget(head, 0, 0, 1, 2)
        badge = QLabel("конфликт", card)
        badge.setProperty("class", "badge-warn")
        grid.addWidget(badge, 0, 2, Qt.AlignmentFlag.AlignRight)

        mine = conflict.get("mine") or {}
        theirs = conflict.get("theirs") or {}
        row = 1
        for field, label in _COMPARE_FIELDS:
            if field not in mine and field not in theirs:
                continue
            mine_v, theirs_v = mine.get(field), theirs.get(field)
            # partition_name показываем всегда (якорь «о чём речь»),
            # прочие поля — только когда версии реально расходятся.
            if field != "partition_name" and mine_v == theirs_v:
                continue
            cap = QLabel(label, card)
            cap.setProperty("class", "muted")
            grid.addWidget(cap, row, 0, Qt.AlignmentFlag.AlignTop)
            mine_lbl = QLabel(f"моя: {_fmt(mine_v)}", card)
            mine_lbl.setWordWrap(True)
            grid.addWidget(mine_lbl, row, 1)
            theirs_lbl = QLabel(f"серверная: {_fmt(theirs_v)}", card)
            theirs_lbl.setWordWrap(True)
            theirs_lbl.setProperty("class", "muted")
            grid.addWidget(theirs_lbl, row, 2)
            row += 1

        buttons = QHBoxLayout()
        keep_mine = QPushButton("Оставить мою", card)
        keep_mine.clicked.connect(
            lambda _=False, cid=conflict["id"]: self._resolve(cid, "mine"))
        keep_theirs = QPushButton("Принять серверную", card)
        keep_theirs.clicked.connect(
            lambda _=False, cid=conflict["id"]: self._resolve(cid, "theirs"))
        buttons.addWidget(keep_mine)
        buttons.addWidget(keep_theirs)
        buttons.addStretch(1)
        grid.addLayout(buttons, row, 0, 1, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        return card

    def _resolve(self, conflict_id: int, keep: str) -> None:
        if self.client is None:
            return
        self.client.resolve_conflict(conflict_id, keep)
        # keep="mine" пере-ставит правку в outbox — счётчик очереди меняется.
        self.refresh()

    # ---------- жизненный цикл ----------

    def closeEvent(self, event) -> None:  # noqa: N802 — контракт Qt
        # Немодальный синглтон: закрытие лишь прячет окно; бегущий воркер
        # довершит прогон, его результат обновит скрытое окно — при
        # следующем показе владелец всё равно дернёт refresh().
        super().closeEvent(event)


def _fmt(value) -> str:
    """Компактное представление значения поля в карточке конфликта."""
    if value is None or value == "":
        return "—"
    s = str(value)
    return s if len(s) <= 120 else s[:117] + "…"


def _set_class(widget: QWidget, cls: str) -> None:
    """Сменить QSS-класс уже показанного виджета (с re-polish, см. ui/theme)."""
    widget.setProperty("class", cls)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
