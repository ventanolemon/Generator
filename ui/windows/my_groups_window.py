"""
MyGroupsWindow — read-only витрина групп преподавателя (docs/ui_rework_plan.md,
«осталось по мелочи»).

Преподаватель видит группы, которые ведёт, и их состав. Данные — с сервера
(AssignmentsClient.my_groups → /groups/mine); управление составом остаётся у
администратора (AdminWindow). Мастер-деталь: слева список групп, справа
участники выбранной. Заглушки: нет сервера / вход не выполнен. HTTP — в
фоновом _CallWorker. Немодальный синглтон; refresh() дёшев.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from core.assignments import AssignmentsError
from ui.app_context import AppContext
from ui.qt_worker import run_detached


class _CallWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn())
        except AssignmentsError as e:
            self.failed.emit((str(e), getattr(e, "status", None)))
        except Exception as e:
            self.failed.emit((f"группы: {e}", None))


class MyGroupsWindow(QWidget):
    """Read-only список групп преподавателя и их состав."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = getattr(context, "assignments_client", None)
        self._worker: Optional[_CallWorker] = None
        self._groups: dict[int, dict] = {}

        self.setWindowTitle("Мои группы")
        self.resize(620, 460)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        title = QLabel("Мои группы", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        self.notice = QLabel("", self)
        self.notice.setProperty("class", "muted")
        self.notice.setWordWrap(True)
        self.notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.notice.hide()
        root.addWidget(self.notice)

        self.body = QWidget(self)
        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(6)
        left_cap = QLabel("Группы", self.body)
        left_cap.setProperty("class", "subtitle")
        left.addWidget(left_cap)
        self.groups_list = QListWidget(self.body)
        self.groups_list.currentItemChanged.connect(
            lambda *_: self._render_members())
        left.addWidget(self.groups_list, stretch=1)
        body.addLayout(left, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.members_cap = QLabel("Участники", self.body)
        self.members_cap.setProperty("class", "subtitle")
        right.addWidget(self.members_cap)
        self.members_list = QListWidget(self.body)
        right.addWidget(self.members_list, stretch=1)
        self.members_empty = QLabel("В группе пока нет студентов.", self.body)
        self.members_empty.setProperty("class", "muted")
        self.members_empty.hide()
        right.addWidget(self.members_empty)
        body.addLayout(right, stretch=2)

        root.addWidget(self.body, stretch=1)

    def refresh(self) -> None:
        if self.client is None or not self.client.has_server():
            self._show_notice("Группы недоступны: адрес сервера не задан.\n"
                              "Укажите его в Настройках (вкладка «Соединение»).")
            return
        if self.client.is_guest():
            self._show_notice("Войдите, чтобы видеть свои группы.")
            return
        self.notice.hide()
        self.body.show()
        self._load()

    def _show_notice(self, text: str) -> None:
        self.notice.setText(text)
        self.notice.show()
        self.body.hide()

    def _load(self) -> None:
        if self.client is None or self._worker is not None:
            return
        self._start_call(self.client.my_groups, self._on_loaded,
                         lambda _e: self._show_notice(
                             "Не удалось загрузить группы."))

    def _on_loaded(self, groups: list) -> None:
        self._groups = {int(g["id"]): g for g in groups}
        prev = self._current_group_id()
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        for g in groups:
            item = QListWidgetItem(
                f"{g.get('name', '')}  ·  {g.get('member_count', 0)}")
            item.setData(Qt.ItemDataRole.UserRole, int(g["id"]))
            self.groups_list.addItem(item)
        self.groups_list.blockSignals(False)
        if groups:
            target = prev if prev in self._groups else int(groups[0]["id"])
            for i in range(self.groups_list.count()):
                if self.groups_list.item(i).data(
                        Qt.ItemDataRole.UserRole) == target:
                    self.groups_list.setCurrentRow(i)
                    break
        self._render_members()

    def _current_group_id(self) -> Optional[int]:
        item = self.groups_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _render_members(self) -> None:
        self.members_list.clear()
        gid = self._current_group_id()
        group = self._groups.get(gid) if gid is not None else None
        members = list(group.get("members", [])) if group else []
        for login in members:
            self.members_list.addItem(login)
        self.members_empty.setVisible(group is not None and not members)
        self.members_cap.setText(
            f"Участники — {group['name']}" if group else "Участники")

    def _start_call(self, fn, on_done, on_failed) -> None:
        if self._worker is not None:
            return
        # Без родителя и через run_detached: поток, принадлежащий окну,
        # умирает вместе с ним прямо на ходу (см. ui/qt_worker.py).
        worker = _CallWorker(fn)
        self._worker = worker

        def _done(result):
            self._worker = None
            on_done(result)

        def _failed(err):
            self._worker = None
            on_failed(err)

        run_detached(self, worker, _done, _failed)
