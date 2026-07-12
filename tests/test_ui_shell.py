"""
Волна A плана docs/ui_rework_plan.md — фундамент оболочки: настройки среды
(core/settings), роль сессии (Repository.role-колонка + find_user), верхняя
панель действий (ui/widgets/TopBar) с ролевым гейтингом и бейджами.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_ui_shell
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.repository import Repository
from core.settings import Settings, DEFAULT_THEME

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QToolButton
    HAS_QT = True
except Exception:
    HAS_QT = False


def _temp_db_with_user(role_column: bool) -> str:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    cols = 'login TEXT, password TEXT, FIO TEXT, "group" TEXT'
    if role_column:
        cols += ", role TEXT NOT NULL DEFAULT 'teacher'"
    conn.execute(f"CREATE TABLE users ({cols})")
    if role_column:
        conn.execute("INSERT INTO users VALUES ('t','p','ФИО','Г1','admin')")
    else:
        conn.execute("INSERT INTO users VALUES ('t','p','ФИО','Г1')")
    conn.commit()
    conn.close()
    return path


class SettingsTests(unittest.TestCase):
    @unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
    def _settings(self) -> Settings:
        return Settings(QSettings(tempfile.mktemp(suffix=".ini"),
                                  QSettings.Format.IniFormat))

    @unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
    def test_base_url_roundtrip(self):
        s = self._settings()
        self.assertEqual(s.get_base_url(), "")
        s.set_base_url("  http://host:5000  ")
        self.assertEqual(s.get_base_url(), "http://host:5000")  # trimmed

    @unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
    def test_theme_default_and_set(self):
        s = self._settings()
        self.assertEqual(s.get_theme(), DEFAULT_THEME)
        s.set_theme("light")
        self.assertEqual(s.get_theme(), "light")


class RoleColumnTests(unittest.TestCase):
    def test_ensure_adds_column_idempotent(self):
        path = _temp_db_with_user(role_column=False)
        repo = Repository(path)
        repo.ensure_user_role_column()
        repo.ensure_user_role_column()  # второй раз — не падает
        conn = sqlite3.connect(path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        conn.close()
        self.assertIn("role", cols)
        os.remove(path)

    def test_find_user_returns_role(self):
        path = _temp_db_with_user(role_column=True)
        repo = Repository(path)
        row = repo.find_user("t", "p")
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "t")
        self.assertEqual(row[3], "admin")
        os.remove(path)

    def test_find_user_fallback_without_role_column(self):
        # Колонки role нет и ensure не звали — мягкий откат к 'teacher'.
        path = _temp_db_with_user(role_column=False)
        repo = Repository(path)
        row = repo.find_user("t", "p")
        self.assertEqual(row[3], "teacher")
        os.remove(path)

    def test_migrated_default_is_teacher(self):
        path = _temp_db_with_user(role_column=False)
        repo = Repository(path)
        repo.ensure_user_role_column()
        row = repo.find_user("t", "p")
        self.assertEqual(row[3], "teacher")
        os.remove(path)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class TopBarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _bar(self, role="teacher"):
        from ui.widgets import TopBar
        self._role = {"v": role}
        return TopBar(lambda: self._role["v"])

    def test_add_action_returns_button(self):
        bar = self._bar()
        btn = bar.add_action("Настройки", "tt", lambda: None)
        self.assertIsInstance(btn, QToolButton)
        self.assertEqual(btn.text(), "Настройки")

    def test_role_gating_hides_for_wrong_role(self):
        bar = self._bar(role="teacher")
        btn = bar.add_action("Контур", "tt", lambda: None,
                             roles={"teacher", "admin"})
        self.assertFalse(btn.isHidden())          # видима (флаг hide снят)
        self._role["v"] = "student"
        bar.refresh_roles()
        self.assertTrue(btn.isHidden())
        self._role["v"] = "admin"
        bar.refresh_roles()
        self.assertFalse(btn.isHidden())

    def test_ungated_action_always_visible(self):
        bar = self._bar(role="student")
        btn = bar.add_action("Статистика", "tt", lambda: None)
        self.assertFalse(btn.isHidden())

    def test_badge_set_and_hide(self):
        bar = self._bar()
        bar.set_badge("sync", "3 не отправлено", "warn")
        self.assertFalse(bar._badges["sync"].isHidden())
        self.assertEqual(bar._badges["sync"].property("class"), "badge-warn")
        bar.set_badge("sync", "")          # пусто → прячем
        self.assertTrue(bar._badges["sync"].isHidden())

    def test_action_click_fires_callback(self):
        bar = self._bar()
        fired = {"n": 0}
        btn = bar.add_action("X", "tt", lambda: fired.__setitem__("n", fired["n"] + 1))
        btn.click()
        self.assertEqual(fired["n"], 1)


if __name__ == "__main__":
    unittest.main()
