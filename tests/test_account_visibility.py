"""
Персональная видимость и ролевое удаление предметов.

Три независимых поведения, которые раньше были общими на весь файл БД или
на всех пользователей:

  1. Скрытие предмета/раздела — настройка КОНКРЕТНОГО аккаунта. Раньше это
     была колонка `hidden` прямо в Subjects/Partitions, одна на файл: гость
     скрывал предмет — предмет пропадал и у преподавателей, работающих на
     этой же машине. Гость тоже получает свой бакет, а не «общий».
  2. Унаследованные скрытия из колонки переносятся гостю разово, колонка
     обнуляется (миграция идемпотентна).
  3. Удаление предмета из БД — только администратору; остальным вместо него
     персональное скрытие.

Плюс регрессия на предупреждения старта: build_registry не должен ругаться
на code-only разделы, записи которых создаёт sync_database из тех же самых
CODE_GENERATORS (раньше это давало ~40 строк варнингов при каждом запуске).

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_account_visibility
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.repository import GUEST_VISIBILITY_KEY, Repository
from tests.test_sync_client import _make_local_db
from core.tmpdb import temp_path  # noqa: E402

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


class VisibilityIsPerAccountTests(unittest.TestCase):
    """Скрытие живёт в бакете аккаунта и не течёт к соседям."""

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.commit()
        self.pid = self.repo.upsert_partition(
            subject_id=1, name="Раздел А", constracted=0, generation_params={})

    def tearDown(self):
        os.remove(self.db)

    def _visible_subject_ids(self, login):
        return [s.id for s in self.repo.list_subjects(user_login=login)]

    def test_guest_hiding_subject_does_not_hide_it_for_teacher(self):
        """Ровно сообщённый баг: гость скрыл — пропало у преподавателей."""
        self.repo.set_subject_hidden(1, True, user_login=None)

        self.assertEqual(self._visible_subject_ids(None), [],
                         "у самого гостя предмет скрылся")
        self.assertEqual(self._visible_subject_ids("teacher1"), [1],
                         "скрытие гостя не должно доставать преподавателя")
        self.assertEqual(self._visible_subject_ids("teacher2"), [1])

    def test_teacher_hiding_subject_does_not_hide_it_for_others(self):
        self.repo.set_subject_hidden(1, True, user_login="teacher1")

        self.assertEqual(self._visible_subject_ids("teacher1"), [])
        self.assertEqual(self._visible_subject_ids("teacher2"), [1])
        self.assertEqual(self._visible_subject_ids(None), [1])

    def test_hidden_flag_reported_per_viewer(self):
        """include_hidden отдаёт hidden с точки зрения запрашивающего."""
        self.repo.set_subject_hidden(1, True, user_login="teacher1")

        by_owner = self.repo.list_subjects(include_hidden=True,
                                           user_login="teacher1")[0]
        by_other = self.repo.list_subjects(include_hidden=True,
                                           user_login="teacher2")[0]
        self.assertTrue(by_owner.hidden)
        self.assertFalse(by_other.hidden)

    def test_partition_hiding_is_per_account_too(self):
        self.repo.set_partition_hidden(self.pid, True, user_login="teacher1")

        self.assertEqual(
            self.repo.list_partitions_for_subject(1, user_login="teacher1"), [])
        self.assertEqual(
            len(self.repo.list_partitions_for_subject(1, user_login="teacher2")), 1)
        self.assertEqual(
            len(self.repo.list_partitions_for_subject(1, user_login=None)), 1)

    def test_unhide_removes_only_own_row(self):
        self.repo.set_subject_hidden(1, True, user_login="teacher1")
        self.repo.set_subject_hidden(1, True, user_login="teacher2")
        self.repo.set_subject_hidden(1, False, user_login="teacher1")

        self.assertEqual(self._visible_subject_ids("teacher1"), [1])
        self.assertEqual(self._visible_subject_ids("teacher2"), [])

    def test_hiding_twice_is_idempotent(self):
        """Повторное скрытие не должно падать на первичном ключе."""
        self.repo.set_subject_hidden(1, True, user_login="teacher1")
        self.repo.set_subject_hidden(1, True, user_login="teacher1")
        self.assertEqual(self._visible_subject_ids("teacher1"), [])

    def test_guest_bucket_survives_across_repository_instances(self):
        """Гость — не «никто»: его выбор переживает перезапуск."""
        self.repo.set_subject_hidden(1, True, user_login=None)
        fresh = Repository(self.db)
        self.assertEqual([s.id for s in fresh.list_subjects(user_login=None)],
                         [])

    def test_visibility_rows_die_with_the_subject(self):
        """Удалённый предмет не должен оставлять скрытий: id переиспользуются."""
        self.repo.set_subject_hidden(1, True, user_login="teacher1")
        self.repo.set_partition_hidden(self.pid, True, user_login="teacher1")
        self.repo.delete_subject(1)

        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM SubjectVisibility").fetchone()[0], 0)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM PartitionVisibility").fetchone()[0], 0)


class LegacyHiddenMigrationTests(unittest.TestCase):
    """Перенос старой общей колонки hidden в персональные таблицы."""

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        repo = Repository(self.db)
        repo.ensure_hidden_columns()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (2, 'Матан', 'Матан')")
            conn.commit()
        # Имитируем состояние старой копии БД: скрытие проставлено в колонке.
        with sqlite3.connect(self.db) as conn:
            conn.execute("UPDATE Subjects SET hidden = 1 WHERE id = 1")
            conn.commit()

    def tearDown(self):
        os.remove(self.db)

    def test_legacy_hidden_goes_to_guest_and_column_is_cleared(self):
        repo = Repository(self.db)
        repo.ensure_visibility_tables()

        with sqlite3.connect(self.db) as conn:
            rows = conn.execute(
                "SELECT user_login, subject_id FROM SubjectVisibility").fetchall()
            self.assertEqual(rows, [(GUEST_VISIBILITY_KEY, 1)])
            # Колонка обнулена — иначе перенос повторялся бы и колонка
            # продолжала бы жить второй, конфликтующей правдой.
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM Subjects WHERE hidden = 1").fetchone()[0],
                0)

    def test_after_migration_teacher_sees_everything(self):
        """Смысл переноса: чужие скрытия перестают действовать на вошедших."""
        repo = Repository(self.db)
        self.assertEqual(
            sorted(s.id for s in repo.list_subjects(user_login="teacher1")),
            [1, 2])
        self.assertEqual([s.id for s in repo.list_subjects(user_login=None)],
                         [2])

    def test_migration_is_idempotent(self):
        Repository(self.db).ensure_visibility_tables()
        # Второй экземпляр — свой кэш, миграция отработает заново.
        Repository(self.db).ensure_visibility_tables()

        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM SubjectVisibility").fetchone()[0], 1)

    def test_migration_does_not_resurrect_unhidden_choice(self):
        """Гость показал предмет обратно — повторный прогон не прячет снова."""
        repo = Repository(self.db)
        repo.ensure_visibility_tables()
        repo.set_subject_hidden(1, False, user_login=None)

        Repository(self.db).ensure_visibility_tables()
        self.assertEqual(
            sorted(s.id for s in repo.list_subjects(user_login=None)), [1, 2])


class StartupWarningsTests(unittest.TestCase):
    """build_registry ругается только на настоящие коллизии id."""

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Линейная алгебра', 'Линейная алгебра')")
            conn.commit()
        # Пустой каталог словарей: английские разделы (id 1000+) не мешают.
        self.words = Path(tempfile.mkdtemp())

    def tearDown(self):
        os.remove(self.db)
        os.rmdir(self.words)

    def _warnings_from_build(self):
        from bootstrap import build_registry
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            build_registry(self.repo, self.words)
        return [str(w.message) for w in caught]

    def test_code_only_partition_is_not_a_collision(self):
        """id=1 занят Linal2DGenerator — но это тот же самый раздел."""
        self.repo.ensure_code_partition(
            partition_id=1, subject_id=1, name="Задания на 2D плоскость")
        self.assertEqual(self._warnings_from_build(), [])

    def test_real_collision_still_warns(self):
        """Конструкторный раздел на занятом id действительно потерялся бы."""
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO Partitions (id, subject_id, partition_name, "
                "constracted, generation_parametrs) VALUES (1, 1, 'Моя группа', 2, '[]')")
            conn.commit()

        messages = self._warnings_from_build()
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("partition_id=1", messages[0])
        self.assertIn("Моя группа", messages[0])


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SubjectDeletionIsAdminOnlyTests(unittest.TestCase):
    """Удаление предмета из БД — привилегия админа; остальным — скрытие."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self, role: str, login: str | None = "u"):
        import tempfile as tf
        from PyQt6.QtCore import QSettings
        from core.settings import Settings
        from ui.app_context import AppContext
        from ui.windows import GeneratorWindow

        class FakeReg:
            def get(self, *a, **k):
                raise KeyError("нет генератора")

        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=self.repo, settings=s,
                         user_id_provider=lambda: login,
                         user_role_provider=lambda: role)
        win = GeneratorWindow(context=ctx, registry=FakeReg(),
                              registry_builder=lambda: FakeReg())
        self.addCleanup(win.deleteLater)
        return win

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.commit()

    def tearDown(self):
        os.remove(self.db)

    def test_delete_action_disabled_for_teacher(self):
        win = self._make_window("teacher")
        self.assertFalse(win._subj_delete_action.isEnabled())
        self.assertIn("администратор", win._subj_delete_action.toolTip())

    def test_delete_action_enabled_for_admin(self):
        win = self._make_window("admin")
        self.assertTrue(win._subj_delete_action.isEnabled())

    def test_teacher_cannot_delete_even_if_handler_is_called(self):
        """Гейт не только в виджете: сам обработчик отказывает."""
        win = self._make_window("teacher")
        win.subject_combo.setCurrentIndex(0)

        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "information") as info, \
                mock.patch.object(QMessageBox, "question") as question:
            win._on_delete_subject()

        info.assert_called_once()
        question.assert_not_called()   # до подтверждения удаления не дошло
        self.assertEqual(len(self.repo.list_subjects(user_login="u")), 1,
                         "предмет остался в базе")

    def test_admin_deletes_after_confirmation(self):
        win = self._make_window("admin")
        win.subject_combo.setCurrentIndex(0)

        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.Yes):
            win._on_delete_subject()

        self.assertEqual(self.repo.list_subjects(user_login="u"), [])

    def test_guest_hides_subject_only_for_itself_through_the_window(self):
        """Сквозной путь окна: гость скрывает — преподаватель по-прежнему видит."""
        guest_win = self._make_window("student", login=None)
        guest_win.subject_combo.setCurrentIndex(0)
        guest_win._on_toggle_subject_hidden()

        self.assertEqual(guest_win.subject_combo.count(), 0)
        teacher_win = self._make_window("teacher", login="teacher1")
        self.assertEqual(teacher_win.subject_combo.count(), 1)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GuestReturnsToAuthTests(unittest.TestCase):
    """Гостю нужен вход, а не выход — подпись и отсутствие подтверждения."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self, login: str | None, role: str):
        import tempfile as tf
        from PyQt6.QtCore import QSettings
        from core.settings import Settings
        from ui.app_context import AppContext
        from ui.windows import GeneratorWindow

        class FakeReg:
            def get(self, *a, **k):
                raise KeyError("нет генератора")

        s = Settings(QSettings(temp_path(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=self.repo, settings=s,
                         user_id_provider=lambda: login,
                         user_role_provider=lambda: role)
        self.logged_out = []
        win = GeneratorWindow(context=ctx, registry=FakeReg(),
                              registry_builder=lambda: FakeReg(),
                              on_logout=lambda: self.logged_out.append(True))
        self.addCleanup(win.deleteLater)
        return win

    def setUp(self):
        self.db = temp_path(suffix=".db")
        _make_local_db(self.db)
        self.repo = Repository(self.db)

    def tearDown(self):
        os.remove(self.db)

    def test_guest_button_says_login(self):
        win = self._make_window(None, "student")
        win._refresh_identity_badge()
        self.assertEqual(win._logout_btn.text(), "Войти")

    def test_user_button_says_logout(self):
        win = self._make_window("ivan", "teacher")
        win._refresh_identity_badge()
        self.assertEqual(win._logout_btn.text(), "Выйти")

    def test_guest_goes_back_without_confirmation(self):
        win = self._make_window(None, "student")

        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question") as question:
            win._on_logout_clicked()

        question.assert_not_called()
        self.assertEqual(self.logged_out, [True])

    def test_logged_in_user_is_still_asked(self):
        win = self._make_window("ivan", "teacher")

        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.StandardButton.No):
            win._on_logout_clicked()

        self.assertEqual(self.logged_out, [], "отказ от выхода не сработал")


if __name__ == "__main__":
    unittest.main()
