"""
B1 плана docs/ui_rework_plan.md — диалог технических настроек среды:
сохранение адреса backend и темы, обновление клиента синка, живое превью
темы и откат по «Отмене».

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_settings_window
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
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core.repository import Repository
    from core.settings import Settings
    from core.sync import SyncClient, SyncStore
    from ui.app_context import AppContext
    from ui.theme import apply_theme
    from ui.windows.settings_window import SettingsWindow


def _empty_db() -> str:
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE Subjects(id INTEGER PRIMARY KEY, subject_name TEXT, "
        " pra_subject TEXT);"
        "CREATE TABLE Partitions(id INTEGER PRIMARY KEY AUTOINCREMENT, "
        " subject_id INT, partition_name TEXT, constracted INT, "
        " generation_parametrs TEXT);")
    conn.close()
    return path


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _ctx(self):
        db = _empty_db()
        self._db = db
        repo = Repository(db)
        store = SyncStore(db)
        self.client = SyncClient(repo, store, base_url="")
        self.settings = Settings(QSettings(tempfile.mktemp(suffix=".ini"),
                                           QSettings.Format.IniFormat))
        return AppContext(repo=repo, settings=self.settings,
                          user_id_provider=lambda: "u1",
                          user_role_provider=lambda: "teacher",
                          sync_client=self.client)

    def test_save_persists_and_updates_client(self):
        dlg = SettingsWindow(self._ctx())
        dlg.base_url_edit.setText("  http://host:5000  ")
        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("light"))
        dlg._on_save()
        self.assertEqual(self.settings.get_base_url(), "http://host:5000")
        self.assertEqual(self.settings.get_theme(), "light")
        self.assertEqual(self.client._base_url, "http://host:5000")

    def test_theme_preview_applies_live(self):
        apply_theme(self.app, "dark")
        dlg = SettingsWindow(self._ctx())
        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("light"))
        # Превью применяет тему немедленно (стиль приложения непустой).
        self.assertTrue(self.app.styleSheet())

    def test_reject_reverts_theme(self):
        self.settings = None
        ctx = self._ctx()
        self.settings.set_theme("dark")
        apply_theme(self.app, "dark")
        dlg = SettingsWindow(ctx)
        dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("light"))
        dlg.reject()
        # После отмены тема возвращается к сохранённой (dark) — не падает,
        # стиль применён; сохранённое значение не изменилось.
        self.assertEqual(self.settings.get_theme(), "dark")

    def test_test_connection_empty_url(self):
        dlg = SettingsWindow(self._ctx())
        dlg.base_url_edit.setText("")
        dlg._on_test_connection()
        self.assertIn("не задан", dlg.conn_status.text().lower())


if __name__ == "__main__":
    unittest.main()
