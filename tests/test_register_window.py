"""
E2 плана docs/ui_rework_plan.md — экран регистрации (RegisterWindow) поверх
repo.create_user (D1). Валидация, успешная регистрация с автологином,
навигация «Ко входу».

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_register_window
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core.repository import Repository
    from ui.windows.register_window import RegisterWindow


def _db() -> str:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE users (login TEXT PRIMARY KEY, password TEXT, '
        'FIO TEXT, "group" TEXT, role TEXT NOT NULL DEFAULT \'teacher\')')
    conn.execute("INSERT INTO users VALUES ('занят','x','','','teacher')")
    conn.commit()
    conn.close()
    return path


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class RegisterWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = _db()
        self.repo = Repository(self.db)
        self.registered = []
        self.went_back = []

    def tearDown(self):
        os.remove(self.db)

    def _win(self):
        w = RegisterWindow(self.repo, on_success=self.registered.append,
                           on_back=lambda: self.went_back.append(True))
        self.addCleanup(w.deleteLater)
        return w

    def test_successful_registration_logs_in(self):
        w = self._win()
        w.login_edit.setText("новичок")
        w.fio_edit.setText("Иванов И.И.")
        w.group_edit.setText("Б-21")
        w.password_edit.setText("пароль")
        w.repeat_edit.setText("пароль")
        w._on_create()
        self.assertEqual(self.registered, ["новичок"])
        row = self.repo.find_user("новичок", "пароль")
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "Иванов И.И.")
        self.assertEqual(row[3], "teacher")

    def test_duplicate_login_shows_error(self):
        w = self._win()
        w.login_edit.setText("занят")
        w.password_edit.setText("пароль")
        w.repeat_edit.setText("пароль")
        w._on_create()
        self.assertEqual(self.registered, [])
        self.assertTrue(w.error_label.isVisibleTo(w))
        self.assertIn("занят", w.error_label.text())

    def test_mismatched_passwords(self):
        w = self._win()
        w.login_edit.setText("x")
        w.password_edit.setText("аaaa")
        w.repeat_edit.setText("бbbb")
        w._on_create()
        self.assertEqual(self.registered, [])
        self.assertIn("не совпадают", w.error_label.text())

    def test_short_password(self):
        w = self._win()
        w.login_edit.setText("x")
        w.password_edit.setText("аб")
        w.repeat_edit.setText("аб")
        w._on_create()
        self.assertEqual(self.registered, [])
        self.assertIn("короче", w.error_label.text())

    def test_empty_login(self):
        w = self._win()
        w.password_edit.setText("пароль")
        w.repeat_edit.setText("пароль")
        w._on_create()
        self.assertIn("логин", w.error_label.text().lower())

    def test_back_navigation(self):
        w = self._win()
        w._on_back()
        self.assertEqual(self.went_back, [True])


if __name__ == "__main__":
    unittest.main()
