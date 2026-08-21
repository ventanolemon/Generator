"""
Хранение данных: WAL и проверка внешних ключей.

На одном файле БД десктопа работают два писателя — UI-поток (правки
разделов, попытки) и фоновый _SyncWorker (QThread), который ведёт outbox
через SyncStore(DB_PATH), то есть ту же самую БД. В журнале по умолчанию
(delete) писатель держит эксклюзивную блокировку файла, и параллельное
чтение из другого потока ловит SQLITE_BUSY «database is locked».

Запуск: python -m unittest tests.test_db_concurrency
"""

from __future__ import annotations

import shutil
import sqlite3
import threading
import unittest

from bootstrap import sync_database
from const import DB_TEMPLATE as DB_PATH, WORDS_DIR
from core.repository import Repository
from core.sync.store import SyncStore
from tests.tmpdb import temp_path


class DbConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = temp_path()
        # Схему десктоп не создаёт из кода — БД поставляется вместе с
        # приложением. Копируем поставочную, чтобы тест шёл тем же путём,
        # что и реальный запуск (Repository → sync_database).
        shutil.copyfile(DB_PATH, self.path)
        self.repo = Repository(self.path)

    def test_ensure_wal_mode_switches_journal(self):
        """ensure_wal_mode переводит файл в WAL и идемпотентна."""
        self.repo.ensure_wal_mode()
        with self.repo._connect() as conn:  # noqa: SLF001 — проверяем слой данных
            self.assertEqual(
                conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
        self.repo.ensure_wal_mode()          # повторный вызов не ломает режим
        with self.repo._connect() as conn:  # noqa: SLF001
            self.assertEqual(
                conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def test_sync_store_inherits_wal(self):
        """
        Режим журнала хранится в файле, поэтому SyncStore, открывающий ту же
        БД, наследует WAL — отдельной настройки в нём не требуется.
        """
        self.repo.ensure_wal_mode()
        store = SyncStore(self.path)
        with store._connect() as conn:  # noqa: SLF001
            self.assertEqual(
                conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")

    def _writer_commits_with_open_reader(self) -> bool:
        """
        Записать из второго потока, пока первый держит ОТКРЫТУЮ читающую
        транзакцию. True — коммит прошёл, False — «database is locked».

        Это и есть рабочий сценарий десктопа: UI-поток листает разделы
        (читающая транзакция открыта), фоновый _SyncWorker в это время
        пишет outbox в тот же файл.
        """
        reader = sqlite3.connect(self.path, timeout=0.5)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM probe").fetchall()   # берём SHARED-лок
        ok: dict = {}

        def writer() -> None:
            conn = sqlite3.connect(self.path, timeout=0.5)
            try:
                conn.execute("INSERT INTO probe (v) VALUES ('из фона')")
                conn.commit()
                ok["done"] = True
            except sqlite3.OperationalError:
                ok["done"] = False
            finally:
                conn.close()

        t = threading.Thread(target=writer)
        t.start()
        t.join(5)
        reader.close()
        return bool(ok.get("done"))

    def test_writer_not_blocked_by_open_reader(self):
        """
        Ради чего включается WAL: в журнале delete открытый читатель держит
        SHARED-лок, и коммит писателя падает с «database is locked». В WAL
        тот же коммит проходит.

        Проверяем оба режима на одном и том же сценарии — иначе тест
        зелёный независимо от того, включён WAL или нет.
        """
        with self.repo._connect() as conn:  # noqa: SLF001
            conn.execute(
                "CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, v TEXT)")
            conn.execute("INSERT INTO probe (v) VALUES ('до')")
            conn.commit()

        # Базовый журнал: писатель проигрывает открытому читателю.
        with self.repo._connect() as conn:  # noqa: SLF001
            conn.execute("PRAGMA journal_mode = DELETE")
        self.assertFalse(
            self._writer_commits_with_open_reader(),
            "в режиме delete коммит writer'а неожиданно прошёл — "
            "сценарий перестал быть показательным, тест нужно пересмотреть")

        # После ensure_wal_mode — проходит.
        self.repo.ensure_wal_mode()
        self.assertTrue(
            self._writer_commits_with_open_reader(),
            "в WAL коммит writer'а всё ещё блокируется открытым читателем")

    def test_foreign_keys_enforced_on_connections(self):
        """PRAGMA foreign_keys включена — объявленные REFERENCES проверяются."""
        with self.repo._connect() as conn:  # noqa: SLF001
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            conn.executescript("""
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES parent(id)
                );
            """)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO child (parent_id) VALUES (999)")

    def test_bootstrap_enables_wal(self):
        """sync_database включает WAL до первых записей."""
        sync_database(self.repo, WORDS_DIR)
        with self.repo._connect() as conn:  # noqa: SLF001
            self.assertEqual(
                conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")


if __name__ == "__main__":
    unittest.main()
