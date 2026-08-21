"""
Выход из аккаунта в GeneratorWindow: кнопка «Выйти» вызывает колбэк
on_logout только после подтверждения, плашка "логин · роль" обновляется
при показе окна, открытые немодальные окна-синглтоны закрываются перед
выходом (иначе они остались бы поверх экрана входа с данными старой сессии).

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_logout
"""

from __future__ import annotations
import os
import unittest
from unittest.mock import patch
from tests.tmpdb import temp_path  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QMessageBox
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core.repository import Repository
    from core.settings import Settings
    from tests.test_sync_client import _make_local_db
    from ui.app_context import AppContext
    from ui.windows import GeneratorWindow


class _FakeReg:
    def get(self, *a, **k):
        raise KeyError("нет генератора")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class LogoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, role="teacher", login="alice", on_logout=None):
        db = temp_path(suffix=".db")
        self._db = db
        _make_local_db(db)
        repo = Repository(db)
        repo.ensure_hidden_columns()
        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        # Мутабельный бокс, а не замыкание на параметры — тесту повторного
        # входа нужно поменять identity ПОСЛЕ создания окна, как это
        # происходит в реальном приложении (session переживает logout).
        self._identity = {"login": login, "role": role}
        ctx = AppContext(repo=repo, settings=s,
                         user_id_provider=lambda: self._identity["login"],
                         user_role_provider=lambda: self._identity["role"])
        w = GeneratorWindow(context=ctx, registry=_FakeReg(),
                            registry_builder=lambda: _FakeReg(),
                            on_logout=on_logout)
        self.addCleanup(w.deleteLater)
        return w

    def tearDown(self):
        if hasattr(self, "_db") and os.path.exists(self._db):
            os.remove(self._db)

    def test_no_logout_button_without_callback(self):
        w = self._window(on_logout=None)
        # Без колбэка кнопка не добавляется вовсе — ищем по тексту среди
        # добавленных ролевых/безролевых кнопок TopBar.
        texts = [btn.text() for btn, _roles in w.top_bar._role_gated]
        self.assertNotIn("Выйти", texts)

    def test_confirm_yes_calls_callback_and_hides_subwindows(self):
        calls = []
        w = self._window(on_logout=lambda: calls.append(True))
        w.show()
        self.app.processEvents()

        # Открываем окно-синглтон (Sync — не требует сервера, чтобы
        # открыться без сети) и проверяем, что выход прячет его немедленно
        # (close() синхронный; фактическое уничтожение — deleteLater,
        # см. следующий тест на пересборку с новой identity).
        w._open_sync_window()
        self.app.processEvents()
        self.assertIsNotNone(w._sync_window)
        self.assertTrue(w._sync_window.isVisible())

        stale_ref = w._sync_window
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            w._on_logout_clicked()

        self.assertEqual(calls, [True])
        # Атрибут обнуляется синхронно в _close_sub_windows — не ждём
        # цикла событий (см. следующий тест на гонку с deleteLater).
        self.assertIsNone(w._sync_window)
        self.assertFalse(stale_ref.isVisible())
        self.app.processEvents()  # прогнать отложенное deleteLater

    def test_admin_window_rebuilt_with_fresh_identity_after_relogin(self):
        # Регрессия: AdminWindow._viewer_login захватывается один раз в
        # конструкторе (self-lock «нельзя менять свою роль»). Без
        # deleteLater() в _close_sub_windows синглтон пережил бы logout, и
        # после входа другим админом self-lock всё ещё бил бы по старому
        # логину. admin_client не нужен — _viewer_login ставится до любых
        # сетевых вызовов.
        w = self._window(role="admin", login="alice", on_logout=lambda: None)
        w._open_admin_window()
        self.app.processEvents()
        first = w._admin_window
        self.assertIsNotNone(first)
        self.assertEqual(first._viewer_login, "alice")

        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            w._on_logout_clicked()
        self.assertIsNone(w._admin_window)  # обнулено синхронно, без ожидания

        self._identity["login"] = "bob"  # "повторный вход" другим админом
        w._open_admin_window()
        self.app.processEvents()
        second = w._admin_window
        self.assertIsNotNone(second)
        self.assertIsNot(second, first)
        self.assertEqual(second._viewer_login, "bob")
        self.app.processEvents()  # прогнать отложенное deleteLater первого

    def test_confirm_no_does_not_call_callback(self):
        calls = []
        w = self._window(on_logout=lambda: calls.append(True))
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            w._on_logout_clicked()
        self.assertEqual(calls, [])

    def test_whoami_badge_reflects_identity(self):
        w = self._window(role="admin", login="root",
                         on_logout=lambda: None)
        w.show()
        self.app.processEvents()
        self.assertEqual(w.top_bar._badges["whoami"].text(),
                         "root · администратор")

    def test_whoami_badge_shows_guest(self):
        w = self._window(role="student", login=None,
                         on_logout=lambda: None)
        w.show()
        self.app.processEvents()
        self.assertEqual(w.top_bar._badges["whoami"].text(), "Гость")


if __name__ == "__main__":
    unittest.main()
