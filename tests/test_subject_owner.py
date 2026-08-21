"""
Задача 3 (владение предметами, десктопная половина): колонка
Subjects.owner_user_id, round-trip через sync-pull, разграничение витрины
list_subjects(owned_by=...). NB: это НЕ access-control — настоящее
разграничение доступа на сервере (pull-scope); фильтр здесь для удобства и
пока не включён в UI (см. docs/ui_rework_plan.md, «Владение и роли»).

Запуск: python -m unittest tests.test_subject_owner  (headless, без Qt)
"""

from __future__ import annotations
import os
import sqlite3
import unittest

from core.repository import Repository
from core.sync import SyncClient, SyncStore
from tests.test_sync_client import FakeServer, _make_local_db
from tests.tmpdb import temp_path  # noqa: E402


def _db_with_subjects() -> str:
    path = temp_path(suffix=".db")
    _make_local_db(path)
    repo = Repository(path)
    repo.ensure_hidden_columns()
    repo.ensure_owner_column()
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                     "VALUES (1, 'Встроенный', 'Встроенный')")  # owner NULL
        conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                     "VALUES (2, 'Аллы', 'x')")
        conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                     "VALUES (3, 'Бориса', 'x')")
        conn.commit()
    repo.set_subject_owner(2, "alla")
    repo.set_subject_owner(3, "boris")
    return path


class OwnerColumnTests(unittest.TestCase):
    def test_ensure_owner_idempotent(self):
        path = temp_path(suffix=".db")
        _make_local_db(path)
        repo = Repository(path)
        repo.ensure_owner_column()
        repo.ensure_owner_column()
        with sqlite3.connect(path) as conn:
            cols = [r[1] for r in
                    conn.execute("PRAGMA table_info(Subjects)").fetchall()]
        self.assertEqual(cols.count("owner_user_id"), 1)
        os.remove(path)

    def test_builtin_vs_owned(self):
        path = _db_with_subjects()
        repo = Repository(path)
        by_id = {s.id: s for s in repo.list_subjects()}
        self.assertTrue(by_id[1].is_builtin)
        self.assertIsNone(by_id[1].owner_user_id)
        self.assertFalse(by_id[2].is_builtin)
        self.assertEqual(by_id[2].owner_user_id, "alla")
        os.remove(path)

    def test_owned_by_filter_shows_builtin_plus_own(self):
        path = _db_with_subjects()
        repo = Repository(path)
        names = sorted(s.name for s in repo.list_subjects(owned_by="alla"))
        self.assertEqual(names, ["Аллы", "Встроенный"])   # НЕ «Бориса»
        # Без фильтра — видно всё (текущее поведение UI).
        self.assertEqual(len(repo.list_subjects()), 3)
        os.remove(path)

    def test_owner_survives_old_db_without_column(self):
        # list_subjects по БД без колонки owner — не падает, owner=None.
        path = temp_path(suffix=".db")
        _make_local_db(path)
        with sqlite3.connect(path) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'X', 'X')")
            conn.commit()
        repo = Repository(path)
        subs = repo.list_subjects()
        self.assertEqual(len(subs), 1)
        self.assertTrue(subs[0].is_builtin)
        os.remove(path)


class OwnerSyncRoundTripTests(unittest.TestCase):
    """owner_user_id, присланный сервером в pull, применяется локально."""

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        self.repo.ensure_owner_column()
        self.store = SyncStore(self.db)
        self.server = FakeServer()
        self.client = SyncClient(self.repo, self.store,
                                 transport=self.server.transport)

    def tearDown(self):
        os.remove(self.db)

    def test_pull_applies_owner_when_server_sends_it(self):
        # Сервер знает предмет с владельцем.
        ver = self.server.seed("subject", 10, {
            "subject_name": "Предмет Аллы", "pra_subject": "x",
            "owner_user_id": "alla"})
        self.assertGreater(ver, 0)
        report = self.client.sync()
        self.assertTrue(report.ok, report.errors)
        by_id = {s.id: s for s in self.repo.list_subjects()}
        self.assertIn(10, by_id)
        self.assertEqual(by_id[10].owner_user_id, "alla")
        self.assertFalse(by_id[10].is_builtin)

    def test_pull_without_owner_leaves_builtin(self):
        # «Старый» сервер владельца не шлёт — предмет остаётся встроенным.
        self.server.seed("subject", 11, {
            "subject_name": "Общий", "pra_subject": "x"})
        self.client.sync()
        by_id = {s.id: s for s in self.repo.list_subjects()}
        self.assertTrue(by_id[11].is_builtin)


try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class OwnerScopeWindowTests(unittest.TestCase):
    """generator_window применяет owner-фильтр по роли (id = login)."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, login, role):
        import tempfile as tf
        from PyQt6.QtCore import QSettings
        from core.settings import Settings
        from ui.app_context import AppContext
        from ui.windows import GeneratorWindow

        db = _db_with_subjects()          # 1 встроенный + предметы alla/boris
        self._db = db
        repo = Repository(db)

        class FakeReg:
            def get(self, *a, **k):
                raise KeyError("нет")

        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=repo, settings=s,
                         user_id_provider=lambda: login,
                         user_role_provider=lambda: role)
        w = GeneratorWindow(context=ctx, registry=FakeReg(),
                            registry_builder=lambda: FakeReg())
        self.addCleanup(w.deleteLater)
        return w

    def tearDown(self):
        if hasattr(self, "_db") and os.path.exists(self._db):
            os.remove(self._db)

    def _combo_names(self, w):
        return {w.subject_combo.itemText(i)
                for i in range(w.subject_combo.count())}

    def test_teacher_sees_builtin_plus_own(self):
        w = self._window(login="alla", role="teacher")
        names = self._combo_names(w)
        self.assertIn("Встроенный", names)
        self.assertIn("Аллы", names)
        self.assertNotIn("Бориса", names)

    def test_admin_sees_all(self):
        w = self._window(login="root", role="admin")
        names = self._combo_names(w)
        self.assertEqual(names, {"Встроенный", "Аллы", "Бориса"})

    def test_guest_no_owner_filter(self):
        # Гость (login None) — витрина без фильтра владения (всё локальное).
        w = self._window(login=None, role="student")
        self.assertEqual(len(self._combo_names(w)), 3)


if __name__ == "__main__":
    unittest.main()
