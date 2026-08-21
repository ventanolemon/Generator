"""
E1 плана docs/ui_rework_plan.md — реструктуризация главного экрана (сайдбар,
метки типа разделов, пустые состояния) и кнопка регистрации на экране входа.
Структурные инварианты и поведение; визуальную полировку ведёт Fable.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_main_screen
"""

from __future__ import annotations
import os
import sqlite3
import unittest
from tests.tmpdb import temp_path  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QLabel
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core.repository import Repository
    from core.settings import Settings
    from tests.test_sync_client import _make_local_db
    from ui.app_context import AppContext
    from ui.windows import GeneratorWindow
    from ui.windows.auth_window import AuthWindow


class _FakeReg:
    def get(self, *a, **k):
        raise KeyError("нет генератора")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class MainScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, with_partitions=True):
        db = temp_path(suffix=".db")
        self._db = db
        _make_local_db(db)
        repo = Repository(db)
        repo.ensure_hidden_columns()
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.commit()
        if with_partitions:
            repo.upsert_partition(subject_id=1, name="Кинематика",
                                  constracted=4, generation_params={})
            repo.upsert_partition(subject_id=1, name="Статика",
                                  constracted=3, generation_params={})
        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=repo, settings=s,
                         user_id_provider=lambda: "u",
                         user_role_provider=lambda: "teacher")
        w = GeneratorWindow(context=ctx, registry=_FakeReg(),
                            registry_builder=lambda: _FakeReg())
        self.addCleanup(w.deleteLater)
        return w

    def tearDown(self):
        if hasattr(self, "_db") and os.path.exists(self._db):
            os.remove(self._db)

    def test_type_label_in_partition_rows(self):
        w = self._window()
        w.subject_combo.setCurrentIndex(0)
        self.app.processEvents()
        texts = [w.partition_list.item(i).text()
                 for i in range(w.partition_list.count())]
        joined = " ".join(texts)
        self.assertIn("[Граф]", joined)
        self.assertIn("[Тест]", joined)
        self.assertIn("Кинематика", joined)

    def test_empty_state_when_no_partitions(self):
        w = self._window(with_partitions=False)
        w.subject_combo.setCurrentIndex(0)
        self.app.processEvents()
        self.assertEqual(w.partition_list.count(), 0)
        self.assertFalse(w.partition_list.isVisible())
        self.assertTrue(w.partitions_empty.isVisibleTo(w))
        self.assertIn("нет разделов", w.partitions_empty.text())

    def test_content_placeholder_present_on_start(self):
        w = self._window()
        # До выбора раздела правая область показывает подсказку (не пустоту).
        labels = w.view_holder.findChildren(QLabel)
        empties = [l for l in labels if l.property("class") == "empty"]
        self.assertTrue(empties, "есть placeholder пустого состояния")
        self.assertIn("Выберите раздел", empties[0].text())

    def test_sidebar_has_brand_and_primary_create(self):
        w = self._window()
        brands = [l for l in w.findChildren(QLabel)
                  if l.property("class") == "brand"]
        self.assertTrue(brands)
        self.assertEqual(w.create_btn.property("class"), "primary")


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AuthRegisterLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _repo(self):
        db = temp_path(suffix=".db")
        self._db = db
        conn = sqlite3.connect(db)
        conn.execute('CREATE TABLE users (login TEXT, password TEXT, '
                     'FIO TEXT, "group" TEXT, role TEXT)')
        conn.commit()
        conn.close()
        return Repository(db)

    def tearDown(self):
        if hasattr(self, "_db") and os.path.exists(self._db):
            os.remove(self._db)

    def test_register_link_present_with_handler(self):
        opened = []
        w = AuthWindow(self._repo(), on_success=lambda u, t=None: None,
                       on_register=lambda: opened.append(True))
        self.addCleanup(w.deleteLater)
        self.assertTrue(hasattr(w, "register_btn"))
        w._on_register()
        self.assertEqual(opened, [True])

    def test_no_register_link_without_handler(self):
        w = AuthWindow(self._repo(), on_success=lambda u, t=None: None)
        self.addCleanup(w.deleteLater)
        self.assertFalse(hasattr(w, "register_btn"))


if __name__ == "__main__":
    unittest.main()
