"""
D3 плана docs/ui_rework_plan.md — скрытие (локальный флаг hidden) и
необратимое удаление предметов/разделов.

Repo-слой: миграция hidden-колонок, фильтрация списков, hidden не мешает
get_partition (генераторы по скрытому продолжают работать), delete_subject
удаляет каскадом и шлёт tombstones в outbox синка. Qt-слой: чекбокс
«Показывать скрытые», пометки « · скрыт», меню предмета.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_hide_delete
"""

from __future__ import annotations
import os
import sqlite3
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.repository import Repository
from core.sync import RepositorySyncListener, SyncClient, SyncStore
from tests.test_sync_client import FakeServer, _make_local_db
from core.tmpdb import temp_path  # noqa: E402

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


class HideDeleteRepoTests(unittest.TestCase):
    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        self.repo.ensure_hidden_columns()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (2, 'Матан', 'Матан')")
            conn.commit()
        self.p1 = self.repo.upsert_partition(
            subject_id=1, name="Раздел А", constracted=0, generation_params={})
        self.p2 = self.repo.upsert_partition(
            subject_id=1, name="Раздел Б", constracted=0, generation_params={})

    def tearDown(self):
        os.remove(self.db)

    def test_ensure_hidden_idempotent(self):
        self.repo.ensure_hidden_columns()
        self.repo.ensure_hidden_columns()
        with sqlite3.connect(self.db) as conn:
            for table in ("Subjects", "Partitions"):
                cols = [r[1] for r in conn.execute(
                    f"PRAGMA table_info({table})").fetchall()]
                self.assertEqual(cols.count("hidden"), 1, table)

    def test_hidden_partition_filtered_but_loadable(self):
        self.repo.set_partition_hidden(self.p1, True)
        visible = self.repo.list_partitions_for_subject(1)
        self.assertEqual([p.name for p in visible], ["Раздел Б"])
        all_ = self.repo.list_partitions_for_subject(1, include_hidden=True)
        self.assertEqual(len(all_), 2)
        self.assertTrue(next(p for p in all_ if p.id == self.p1).hidden)
        # Скрытие не удаление: раздел открывается напрямую.
        self.assertIsNotNone(self.repo.get_partition(self.p1))
        # Обратимо.
        self.repo.set_partition_hidden(self.p1, False)
        self.assertEqual(len(self.repo.list_partitions_for_subject(1)), 2)

    def test_hidden_subject_filtered(self):
        self.repo.set_subject_hidden(2, True)
        self.assertEqual([s.name for s in self.repo.list_subjects()],
                         ["Физика"])
        both = self.repo.list_subjects(include_hidden=True)
        self.assertEqual(len(both), 2)
        self.assertTrue(next(s for s in both if s.id == 2).hidden)

    def test_lists_survive_db_without_hidden_column(self):
        # Старые копии БД без колонки hidden не должны ломать выборки.
        raw = temp_path(suffix=".db")
        _make_local_db(raw)
        with sqlite3.connect(raw) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (5, 'Старый', 'Старый')")
            conn.commit()
        repo = Repository(raw)
        self.assertEqual(len(repo.list_subjects()), 1)
        self.assertEqual(repo.list_partitions_for_subject(5), [])
        os.remove(raw)

    def test_delete_subject_cascades_and_tombstones(self):
        store = SyncStore(self.db)
        client = SyncClient(self.repo, store,
                            transport=FakeServer().transport)
        self.repo.sync_listener = RepositorySyncListener(client)

        self.repo.delete_subject(1)
        self.assertEqual(self.repo.list_subjects(include_hidden=True)[0].id, 2)
        self.assertEqual(
            self.repo.list_partitions_for_subject(1, include_hidden=True), [])
        # Tombstones: два раздела + предмет.
        deleted = [p["payload"] for p in store.pending()
                   if p["payload"].get("deleted")]
        kinds = sorted((d["kind"], d["id"]) for d in deleted)
        self.assertEqual(kinds, [("partition", self.p1),
                                 ("partition", self.p2), ("subject", 1)])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class HideDeleteWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile as tf
        from PyQt6.QtCore import QSettings
        from core.settings import Settings
        from ui.app_context import AppContext
        from ui.windows import GeneratorWindow

        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        self.repo.ensure_hidden_columns()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.commit()
        self.pid = self.repo.upsert_partition(
            subject_id=1, name="Раздел А", constracted=0, generation_params={})

        class FakeReg:
            def get(self, *a, **k):
                raise KeyError("нет генератора")

        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=self.repo, settings=s,
                         user_id_provider=lambda: "u",
                         user_role_provider=lambda: "teacher")
        self.win = GeneratorWindow(context=ctx, registry=FakeReg(),
                                   registry_builder=lambda: FakeReg())
        self.addCleanup(self.win.deleteLater)

    def tearDown(self):
        os.remove(self.db)

    def test_hidden_partition_disappears_until_checkbox(self):
        self.win.subject_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(self.win.partition_list.count(), 1)

        # Скрываем в бакете того же пользователя, от чьего имени построено
        # окно (user_id_provider → "u"): скрытие персональное.
        self.repo.set_partition_hidden(self.pid, True, user_login="u")
        self.win._refresh_current_subject()
        self.assertEqual(self.win.partition_list.count(), 0,
                         "скрытый раздел пропал из списка")

        self.win.show_hidden_cb.setChecked(True)
        self.app.processEvents()
        self.assertEqual(self.win.partition_list.count(), 1)
        self.assertIn("скрыт", self.win.partition_list.item(0).text())

    def test_hidden_subject_disappears_until_checkbox(self):
        self.repo.set_subject_hidden(1, True, user_login="u")
        self.win._load_subjects()
        self.assertEqual(self.win.subject_combo.count(), 0)
        self.win.show_hidden_cb.setChecked(True)
        self.app.processEvents()
        self.assertEqual(self.win.subject_combo.count(), 1)
        self.assertIn("скрыт", self.win.subject_combo.itemText(0))

    def test_toggle_subject_hidden_via_menu_handler(self):
        self.win.subject_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.win._on_toggle_subject_hidden()
        self.assertTrue(self.repo.list_subjects(
            include_hidden=True, user_login="u")[0].hidden)
        # Скрытие персональное: у другого аккаунта предмет остался видимым.
        self.assertFalse(self.repo.list_subjects(
            include_hidden=True, user_login="другой")[0].hidden)
        # Повторный вызов при включённом показе скрытых — разскрытие.
        self.win.show_hidden_cb.setChecked(True)
        self.app.processEvents()
        self.win.subject_combo.setCurrentIndex(0)
        self.win._on_toggle_subject_hidden()
        self.assertFalse(self.repo.list_subjects(
            include_hidden=True, user_login="u")[0].hidden)


if __name__ == "__main__":
    unittest.main()
