"""
Мелкие удобства входа: поле пароля с переключателем видимости
(ui.widgets.password_field) и запоминание последнего логина в AuthWindow.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_password_field
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QLineEdit
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core.repository import Repository
    from core.settings import Settings
    from ui.widgets.password_field import make_password_field
    from ui.windows.auth_window import AuthWindow


def _db_with_user() -> str:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE users (login TEXT PRIMARY KEY, password TEXT, '
        'FIO TEXT, "group" TEXT, role TEXT NOT NULL DEFAULT \'teacher\')')
    conn.commit()
    conn.close()
    repo = Repository(path)
    repo.create_user("ivanov", "secret123", fio="Иванов", role="teacher")
    return path


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class PasswordFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_toggle_is_in_layout_not_overlapping(self):
        # Регрессия: кнопка «Показать» должна быть В лейауте (иначе наезжает
        # на поле в позиции (0,0)). Оба виджета — элементы лейаута строки.
        row = make_password_field()
        self.addCleanup(row.deleteLater)
        self.assertEqual(row.layout().count(), 2)
        widgets = {row.layout().itemAt(i).widget()
                   for i in range(row.layout().count())}
        self.assertIn(row.edit, widgets)
        self.assertIn(row.toggle, widgets)

    def test_starts_hidden_and_toggles(self):
        row = make_password_field(placeholder="пароль")
        self.addCleanup(row.deleteLater)
        self.assertEqual(row.edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(row.toggle.text(), "Показать")

        row.toggle.setChecked(True)
        self.assertEqual(row.edit.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(row.toggle.text(), "Скрыть")

        row.toggle.setChecked(False)
        self.assertEqual(row.edit.echoMode(), QLineEdit.EchoMode.Password)
        self.assertEqual(row.toggle.text(), "Показать")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AuthConveniencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db = _db_with_user()
        self.repo = Repository(self.db)
        self.settings = Settings(
            QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat))
        self.result = []
        # Модальные QMessageBox из _on_login заблокировали бы offscreen-тест —
        # подменяем на no-op на время теста.
        import ui.windows.auth_window as aw

        class _Silent:
            @staticmethod
            def warning(*a, **k):
                return None

            @staticmethod
            def critical(*a, **k):
                return None

        self._orig_msg = aw.QMessageBox
        aw.QMessageBox = _Silent
        self.addCleanup(lambda: setattr(aw, "QMessageBox", self._orig_msg))

    def tearDown(self):
        os.remove(self.db)

    def _win(self):
        w = AuthWindow(repository=self.repo, on_success=self.result.append,
                       settings=self.settings)
        self.addCleanup(w.deleteLater)
        return w

    def test_password_field_hidden_by_default(self):
        w = self._win()
        self.assertEqual(w.password_edit.echoMode(),
                         QLineEdit.EchoMode.Password)

    def test_saves_last_login_on_success_and_prefills_next_time(self):
        w = self._win()
        w.login_edit.setText("ivanov")
        w.password_edit.setText("secret123")
        w._on_login()
        self.assertEqual(len(self.result), 1)          # вход удался
        self.assertEqual(self.settings.get_last_login(), "ivanov")
        # Следующее окно подставляет логин и фокусирует пароль.
        w2 = self._win()
        self.assertEqual(w2.login_edit.text(), "ivanov")

    def test_wrong_password_does_not_save_login(self):
        w = self._win()
        w.login_edit.setText("ivanov")
        w.password_edit.setText("неверный")
        w._on_login()
        self.assertEqual(self.result, [])
        self.assertEqual(self.settings.get_last_login(), "")


if __name__ == "__main__":
    unittest.main()
