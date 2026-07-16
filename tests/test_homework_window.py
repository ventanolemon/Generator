"""
HomeworkWindow (offscreen Qt): ветвление по роли и заглушки, выдача задания
преподавателем + список/снятие, просмотр студентом.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_homework_window
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.assignments import AssignmentsClient
from tests.test_assignments_client import FakeServer

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


class _FakeRepo:
    """Локальные предметы/партиции для формы выдачи (сеть не нужна)."""
    class _S:
        def __init__(self, i, n): self.id, self.name = i, n
    class _P:
        def __init__(self, i, n): self.id, self.name = i, n

    def list_subjects(self):
        return [self._S(1, "Физика")]

    def list_partitions_for_subject(self, sid):
        return [self._P(10, "Сила F=ma")]


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class HomeworkWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, role="teacher", login="alla", base_url="http://x",
                server=None):
        from types import SimpleNamespace
        from ui.windows.homework_window import HomeworkWindow

        srv = server or FakeServer()
        client = AssignmentsClient(base_url=base_url, transport=srv.transport,
                                   user_id_provider=lambda: login,
                                   user_role_provider=lambda: role)
        ctx = SimpleNamespace(assignments_client=client, repo=_FakeRepo())
        w = HomeworkWindow(ctx)
        self.addCleanup(w.deleteLater)
        self._srv = srv
        return w

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "условие не наступило")
            self.app.processEvents()
            time.sleep(0.01)

    def _settle(self, w):
        self._spin(lambda: w._worker is None)

    # ---------- заглушки/ветвление ----------

    def test_notice_without_server(self):
        w = self._window(base_url="")
        self.assertEqual(w.stack.currentIndex(), 0)
        self.assertIn("адрес сервера", w.notice_label.text())

    def test_notice_for_guest(self):
        w = self._window(login=None)
        self.assertEqual(w.stack.currentIndex(), 0)
        self.assertIn("Войдите", w.notice_label.text())

    def test_teacher_sees_teacher_page(self):
        w = self._window(role="teacher")
        self.assertEqual(w.stack.currentIndex(), 1)

    def test_student_sees_student_page(self):
        w = self._window(role="student")
        self.assertEqual(w.stack.currentIndex(), 2)

    # ---------- teacher-поток ----------

    def test_teacher_task_and_group_combos_populated(self):
        w = self._window(role="teacher")
        self._settle(w)
        self._spin(lambda: w.group_combo.count() == 1)
        # Задача — из локальной БД; группа — из /groups/mine.
        self.assertEqual(w.task_combo.itemData(0), 10)
        self.assertEqual(w.group_combo.itemData(0), 1)

    def test_teacher_assign_then_delete(self):
        w = self._window(role="teacher")
        self._settle(w)
        self._spin(lambda: w.group_combo.count() == 1)
        w.no_due_check.setChecked(True)
        w.assign_btn.click()
        self._spin(lambda: w.teaching_table.rowCount() == 1)
        self._settle(w)
        self.assertEqual(len(self._srv.assignments), 1)
        # «Сдали X/Y» из обогащённого teaching.
        self.assertEqual(w.teaching_table.item(0, 4).text(), "1/2")
        # Снять — вторая кнопка в ячейке действий (последняя колонка).
        from PyQt6.QtWidgets import QPushButton
        actions = w.teaching_table.cellWidget(0, 5)
        del_btn = actions.findChildren(QPushButton)[-1]
        del_btn.click()
        self._spin(lambda: w.teaching_table.rowCount() == 0)
        self._settle(w)
        self.assertEqual(self._srv.assignments, {})

    def test_teacher_who_solved_dialog(self):
        w = self._window(role="teacher")
        self._settle(w)
        self._spin(lambda: w.group_combo.count() == 1)
        w.no_due_check.setChecked(True)
        w.assign_btn.click()
        self._spin(lambda: w.teaching_table.rowCount() == 1)
        self._settle(w)
        w._show_progress(list(self._srv.assignments)[0])
        self._settle(w)
        self._spin(lambda: w._progress_dialog is not None
                   and w._progress_dialog.table.rowCount() == 2)
        self.assertIn("сдали 1 из 2", w._progress_dialog.summary_label.text())

    def test_teacher_assign_uses_due_epoch(self):
        w = self._window(role="teacher")
        self._settle(w)
        self._spin(lambda: w.group_combo.count() == 1)
        w.no_due_check.setChecked(False)
        w.assign_btn.click()
        self._spin(lambda: w.teaching_table.rowCount() == 1)
        self._settle(w)
        rec = list(self._srv.assignments.values())[0]
        self.assertIn("due_at", rec)
        self.assertIsInstance(rec["due_at"], float)

    # ---------- student-поток ----------

    def test_student_lists_homework(self):
        srv = FakeServer()
        srv.assignments[1] = {"id": 1, "partition_name": "Сила F=ma",
                              "subject_name": "Физика", "group_name": "Г1",
                              "due_at": None}
        w = self._window(role="student", server=srv)
        self._settle(w)
        self._spin(lambda: w.mine_table.rowCount() == 1)
        self.assertEqual(w.mine_table.item(0, 3).text(), "без срока")


if __name__ == "__main__":
    unittest.main()
