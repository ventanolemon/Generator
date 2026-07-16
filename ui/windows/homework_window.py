"""
HomeworkWindow — домашки (docs/ui_rework_plan.md, задача 2, продолжение).

Роль-зависимое окно поверх AssignmentsClient:
  * teacher/admin — форма выдачи (задача + группа + срок) и список своих
    выдач с возможностью снять;
  * student — список выданных ему домашек (по группам, в которых состоит).

Задачи для формы берутся из локальной БД (repo.list_subjects →
list_partitions_for_subject), группы преподавателя — с сервера (/groups/mine).
Права проверяет сервер; окно лишь удобная оболочка. Заглушки: не задан адрес
сервера / вход не выполнен (гость). HTTP-вызовы — в фоновом _CallWorker.
Немодальный синглтон; refresh() дёшев.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from PyQt6.QtCore import QDate, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QStackedWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.assignments import AssignmentsError
from ui.app_context import AppContext

_PAGE_NOTICE = 0
_PAGE_TEACHER = 1
_PAGE_STUDENT = 2


class _CallWorker(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(object)   # (message, status)

    def __init__(self, fn: Callable[[], object], parent: QWidget | None = None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn())
        except AssignmentsError as e:
            self.failed.emit((str(e), getattr(e, "status", None)))
        except Exception as e:
            self.failed.emit((f"домашки: {e}", None))


class HomeworkWindow(QWidget):
    """Окно домашек: выдача (teacher) / просмотр (student)."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = getattr(context, "assignments_client", None)
        self._worker: Optional[_CallWorker] = None

        self.setWindowTitle("Домашки")
        self.resize(720, 560)
        self._build_ui()
        self.refresh()

    # ---------- сборка ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)
        title = QLabel("Домашки", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_notice_page())    # 0
        self.stack.addWidget(self._build_teacher_page())   # 1
        self.stack.addWidget(self._build_student_page())   # 2
        root.addWidget(self.stack, stretch=1)

    def _build_notice_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        self.notice_label = QLabel("", page)
        self.notice_label.setProperty("class", "muted")
        self.notice_label.setWordWrap(True)
        self.notice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.notice_label)
        lay.addStretch(2)
        return page

    def _build_teacher_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        intro = QLabel("Выдайте задание группе. Видно только тем задачам, "
                       "что доступны вам, и группам, которые вы ведёте.", page)
        intro.setProperty("class", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        form = QHBoxLayout()
        self.task_combo = QComboBox(page)
        self.task_combo.setMinimumWidth(220)
        form.addWidget(self.task_combo, stretch=2)
        self.group_combo = QComboBox(page)
        form.addWidget(self.group_combo, stretch=1)
        self.due_edit = QDateEdit(page)
        self.due_edit.setCalendarPopup(True)
        self.due_edit.setDate(QDate.currentDate().addDays(7))
        form.addWidget(self.due_edit)
        self.no_due_check = QCheckBox("без срока", page)
        form.addWidget(self.no_due_check)
        self.assign_btn = QPushButton("Выдать", page)
        self.assign_btn.clicked.connect(self._on_assign)
        form.addWidget(self.assign_btn)
        lay.addLayout(form)

        self.teacher_error = QLabel("", page)
        self.teacher_error.setProperty("class", "danger")
        self.teacher_error.setWordWrap(True)
        self.teacher_error.hide()
        lay.addWidget(self.teacher_error)

        self.teaching_table = self._make_table(
            page, ["Задание", "Предмет", "Группа", "Срок", "Сдали", ""])
        lay.addWidget(self.teaching_table, stretch=1)
        self._progress_dialog: Optional[QDialog] = None
        return page

    def _build_student_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)
        cap = QLabel("Выданные вам задания по вашим группам.", page)
        cap.setProperty("class", "muted")
        lay.addWidget(cap)
        self.student_empty = QLabel("Пока ничего не выдано.", page)
        self.student_empty.setProperty("class", "muted")
        self.student_empty.hide()
        lay.addWidget(self.student_empty)
        self.mine_table = self._make_table(
            page, ["Задание", "Предмет", "Группа", "Срок"])
        lay.addWidget(self.mine_table, stretch=1)
        return page

    def _make_table(self, parent, headers) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        return table

    # ---------- публичное обновление ----------

    def refresh(self) -> None:
        if self.client is None or not self.client.has_server():
            self._notice("Домашки недоступны: адрес сервера не задан.\n"
                         "Укажите его в Настройках (вкладка «Соединение»).")
            return
        if self.client.is_guest():
            self._notice("Войдите, чтобы видеть выданные задания.")
            return
        if self.client.can_assign():
            self.stack.setCurrentIndex(_PAGE_TEACHER)
            self._reload_tasks()
            self._load_teacher()
        else:
            self.stack.setCurrentIndex(_PAGE_STUDENT)
            self._load_student()

    def _notice(self, text: str) -> None:
        self.notice_label.setText(text)
        self.stack.setCurrentIndex(_PAGE_NOTICE)

    # ---------- teacher ----------

    def _reload_tasks(self) -> None:
        """Задачи для формы — из локальной БД (сеть не нужна)."""
        self.task_combo.clear()
        try:
            subjects = self.ctx.repo.list_subjects()
        except Exception:
            subjects = []
        for s in subjects:
            for p in self.ctx.repo.list_partitions_for_subject(s.id):
                self.task_combo.addItem(f"{s.name} / {p.name}", p.id)

    def _load_teacher(self) -> None:
        if self.client is None:
            return
        self.teacher_error.hide()
        # Сначала группы (для формы), затем список выдач.
        self._start_call(self.client.my_groups, self._on_groups,
                         self._on_teacher_error)

    def _on_groups(self, groups: list) -> None:
        current = self.group_combo.currentData()
        self.group_combo.clear()
        for g in groups:
            self.group_combo.addItem(str(g.get("name", "")), int(g["id"]))
        if current is not None:
            idx = self.group_combo.findData(current)
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
        # Теперь список выдач.
        self._start_call(self.client.teaching, self._on_teaching,
                         self._on_teacher_error)

    def _on_teaching(self, items: list) -> None:
        self.teaching_table.setRowCount(0)
        for a in items:
            row = self.teaching_table.rowCount()
            self.teaching_table.insertRow(row)
            self.teaching_table.setItem(
                row, 0, QTableWidgetItem(str(a.get("partition_name", ""))))
            self.teaching_table.setItem(
                row, 1, QTableWidgetItem(str(a.get("subject_name", ""))))
            self.teaching_table.setItem(
                row, 2, QTableWidgetItem(str(a.get("group_name", ""))))
            self.teaching_table.setItem(
                row, 3, QTableWidgetItem(self._fmt_due(a.get("due_at"))))
            self.teaching_table.setItem(
                row, 4, QTableWidgetItem(
                    f"{a.get('solved_count', 0)}/{a.get('member_count', 0)}"))
            aid = int(a["id"])
            actions = QWidget(self.teaching_table)
            arow = QHBoxLayout(actions)
            arow.setContentsMargins(2, 2, 2, 2)
            arow.setSpacing(4)
            who_btn = QPushButton("Кто сдал", actions)
            who_btn.clicked.connect(lambda _c=False, i=aid: self._show_progress(i))
            arow.addWidget(who_btn)
            del_btn = QPushButton("Снять", actions)
            del_btn.setProperty("class", "danger")
            del_btn.clicked.connect(lambda _c=False, i=aid: self._on_delete(i))
            arow.addWidget(del_btn)
            self.teaching_table.setCellWidget(row, 5, actions)

    def _show_progress(self, assignment_id: int) -> None:
        self.teacher_error.hide()
        self._start_call(lambda: self.client.progress(assignment_id),
                         self._on_progress, self._on_teacher_error)

    def _on_progress(self, data: object) -> None:
        if not isinstance(data, dict):
            return
        dlg = self._progress_dialog
        if dlg is None:
            dlg = QDialog(self)
            dlg.setWindowTitle("Кто сдал")
            dlg.resize(420, 360)
            dlay = QVBoxLayout(dlg)
            dlg.summary_label = QLabel("", dlg)
            dlg.summary_label.setProperty("class", "muted")
            dlay.addWidget(dlg.summary_label)
            dlg.table = self._make_table(dlg, ["Студент", "Попыток", "Статус"])
            dlay.addWidget(dlg.table, stretch=1)
            self._progress_dialog = dlg
        summary = data.get("summary") or {}
        a = data.get("assignment") or {}
        dlg.summary_label.setText(
            f"{a.get('partition_name', '')} · {a.get('group_name', '')} — "
            f"сдали {summary.get('solved', 0)} из {summary.get('members', 0)}")
        dlg.table.setRowCount(0)
        for s in (data.get("students") or []):
            row = dlg.table.rowCount()
            dlg.table.insertRow(row)
            fio = str(s.get("fio", "")) or str(s.get("login", ""))
            dlg.table.setItem(row, 0, QTableWidgetItem(
                f"{fio}\n{s.get('login', '')}"))
            dlg.table.setItem(row, 1, QTableWidgetItem(
                str(s.get("attempts", 0))))
            status = ("сдал" if s.get("solved")
                      else "пытался" if s.get("attempts") else "не начал")
            dlg.table.setItem(row, 2, QTableWidgetItem(status))
        dlg.show()
        dlg.raise_()

    def _on_assign(self) -> None:
        pid = self.task_combo.currentData()
        gid = self.group_combo.currentData()
        if pid is None or gid is None:
            self._show_teacher_error(
                "Нужны и задание, и группа. Если групп нет — вас пока не "
                "назначили преподавателем ни на одну.")
            return
        due = None if self.no_due_check.isChecked() else self._due_epoch()
        self.teacher_error.hide()
        self._start_call(
            lambda: self.client.create(int(pid), int(gid), due),
            lambda _r: self._load_teacher(), self._on_teacher_error)

    def _on_delete(self, assignment_id: int) -> None:
        self.teacher_error.hide()
        self._start_call(lambda: self.client.delete(assignment_id),
                         lambda _r: self._load_teacher(),
                         self._on_teacher_error)

    def _on_teacher_error(self, err) -> None:
        message, _status = err
        self._show_teacher_error(message)

    def _show_teacher_error(self, text: str) -> None:
        self.teacher_error.setText(text)
        self.teacher_error.show()

    def _due_epoch(self) -> float:
        d = self.due_edit.date()
        return datetime(d.year(), d.month(), d.day(),
                        tzinfo=timezone.utc).timestamp()

    # ---------- student ----------

    def _load_student(self) -> None:
        if self.client is None:
            return
        self._start_call(self.client.mine, self._on_mine, lambda _e: None)

    def _on_mine(self, items: list) -> None:
        self.mine_table.setRowCount(0)
        for a in items:
            row = self.mine_table.rowCount()
            self.mine_table.insertRow(row)
            self.mine_table.setItem(
                row, 0, QTableWidgetItem(str(a.get("partition_name", ""))))
            self.mine_table.setItem(
                row, 1, QTableWidgetItem(str(a.get("subject_name", ""))))
            self.mine_table.setItem(
                row, 2, QTableWidgetItem(str(a.get("group_name", ""))))
            self.mine_table.setItem(
                row, 3, QTableWidgetItem(self._fmt_due(a.get("due_at"))))
        self.student_empty.setVisible(not items)

    # ---------- утилиты ----------

    @staticmethod
    def _fmt_due(due) -> str:
        if due is None:
            return "без срока"
        try:
            return datetime.fromtimestamp(
                float(due), tz=timezone.utc).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return "—"

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
