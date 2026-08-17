"""
Поставочная БД: она уезжает пользователю как есть, и трогать её нельзя.

Зачем проверка
--------------
`resources/users_database.db` — не рабочий файл, а РЕСУРС ПОСТАВКИ. При
этом приложение открывает его по месту и пишет в него: запуск проекта из
рабочей копии заводит в нём таблицы, переводит журнал в WAL и меняет
файл. Дальше файл попадает в коммит вместе с настоящей правкой — молча,
двоичной строкой «Bin 139264 -> 147456 bytes», в которой не видно
ничего.

Это уже происходило в этой сессии: разбор дефекта завёл в поставочной БД
две пустые таблицы, и они попали в коммит. Содержания в них не было —
но тот же путь ведёт и к файлу, который у пользователя не откроется.
У нас есть незакрытый отчёт ровно об этом: `database disk image is
malformed` на его машине при работающей копии в репозитории.

Проверяется поэтому не «правильные ли данные», а пригодность файла к
поставке:

  * структура цела (`PRAGMA integrity_check`);
  * журнал `delete`, а не `wal` — файл в режиме WAL зависит от соседних
    `-wal`/`-shm`, которых в поставке нет и быть не должно;
  * рядом не лежит хвостов журнала;
  * содержимое, на которое опирается код, на месте.

Запуск:
    python -m unittest tests.test_shipped_database
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from const import DB_PATH


class ShippedDatabaseTests(unittest.TestCase):

    def setUp(self):
        if not Path(DB_PATH).exists():
            self.skipTest("поставочной БД нет в этой сборке")
        # Работаем с КОПИЕЙ: проверка не имеет права стать ещё одним
        # писателем в файл, который сама и защищает.
        self.copy = tempfile.mktemp(suffix=".db")
        shutil.copyfile(DB_PATH, self.copy)
        self.addCleanup(
            lambda: os.path.exists(self.copy) and os.unlink(self.copy))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.copy)
        self.addCleanup(conn.close)
        return conn

    def test_structure_is_intact(self):
        result = self._connect().execute("PRAGMA integrity_check").fetchone()[0]
        self.assertEqual(result, "ok")

    def test_journal_mode_is_not_wal(self):
        """
        В WAL файл БД неполон без соседнего `-wal`: часть страниц лежит
        там. Поставить такой файл без хвоста — значит поставить БД,
        которая на чужой машине может не открыться.
        """
        mode = self._connect().execute(
            "PRAGMA journal_mode").fetchone()[0].lower()
        self.assertEqual(mode, "delete",
                         "поставочная БД переведена в WAL — вероятно, "
                         "приложение запускали из рабочей копии")

    def test_no_journal_leftovers_next_to_it(self):
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(хвост=suffix):
                self.assertFalse(
                    Path(str(DB_PATH) + suffix).exists(),
                    f"рядом с поставочной БД лежит {suffix} — файл в этом "
                    f"состоянии в поставку не годится")

    def test_it_opens_and_carries_what_the_code_expects(self):
        conn = self._connect()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("Subjects", tables)
        self.assertIn("Partitions", tables)
        self.assertGreater(
            conn.execute("SELECT COUNT(*) FROM Partitions").fetchone()[0], 0)

    def test_every_code_partition_has_a_generator(self):
        """
        Раздел с `constracted = 0` заявляет, что его обслуживает КОД.
        Если кода нет, клик по нему даёт `KeyError` — так и вышло с
        разделом «конструктор» предмета Физика.
        """
        import warnings

        import bootstrap
        from const import WORDS_DIR
        from core import Repository

        repo = Repository(self.copy)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bootstrap.sync_database(repo, WORDS_DIR)
            registry = bootstrap.build_registry(repo, WORDS_DIR)
        self.assertEqual(bootstrap.unserved_partitions(repo, registry), [])


if __name__ == "__main__":
    unittest.main()
