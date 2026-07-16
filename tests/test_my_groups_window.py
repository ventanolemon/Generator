"""
MyGroupsWindow (offscreen Qt): заглушки (нет сервера/гость), загрузка групп
преподавателя и рендер состава выбранной группы.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_my_groups_window
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.assignments import AssignmentsClient

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


class FakeGroupsServer:
    def __init__(self, groups=None):
        self.groups = groups if groups is not None else [
            {"id": 1, "name": "КСБО-11-24", "members": ["s1", "s2"],
             "teachers": ["alla"], "member_count": 2},
            {"id": 2, "name": "ИСТ-21-24", "members": [],
             "teachers": ["alla"], "member_count": 0},
        ]

    def transport(self, path, payload, method):
        if path == "/groups/mine":
            return {"groups": self.groups}
        raise AssertionError(path)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class MyGroupsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, base_url="http://x", login="alla", role="teacher",
                server=None):
        from types import SimpleNamespace
        from ui.windows.my_groups_window import MyGroupsWindow

        srv = server or FakeGroupsServer()
        client = AssignmentsClient(base_url=base_url, transport=srv.transport,
                                   user_id_provider=lambda: login,
                                   user_role_provider=lambda: role)
        ctx = SimpleNamespace(assignments_client=client)
        w = MyGroupsWindow(ctx)
        self.addCleanup(w.deleteLater)
        self._srv = srv
        return w

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "условие не наступило")
            self.app.processEvents()
            time.sleep(0.01)

    def test_notice_without_server(self):
        w = self._window(base_url="")
        self.assertFalse(w.notice.isHidden())
        self.assertIn("адрес сервера", w.notice.text())

    def test_notice_for_guest(self):
        w = self._window(login=None)
        self.assertFalse(w.notice.isHidden())
        self.assertIn("Войдите", w.notice.text())

    def test_lists_groups_and_members(self):
        w = self._window()
        self._spin(lambda: w.groups_list.count() == 2)
        self._spin(lambda: w._worker is None)
        # Первая группа выбрана — её участники видны.
        self._spin(lambda: w.members_list.count() == 2)
        members = {w.members_list.item(i).text()
                   for i in range(w.members_list.count())}
        self.assertEqual(members, {"s1", "s2"})

    def test_empty_group_shows_placeholder(self):
        w = self._window()
        self._spin(lambda: w.groups_list.count() == 2)
        self._spin(lambda: w._worker is None)
        # Выбираем вторую группу (пустую).
        for i in range(w.groups_list.count()):
            from PyQt6.QtCore import Qt
            if w.groups_list.item(i).data(Qt.ItemDataRole.UserRole) == 2:
                w.groups_list.setCurrentRow(i)
                break
        self.assertEqual(w.members_list.count(), 0)
        self.assertFalse(w.members_empty.isHidden())


if __name__ == "__main__":
    unittest.main()
