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
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from const import DB_TEMPLATE as DB_PATH
from core.tmpdb import temp_path  # noqa: E402


class ShippedDatabaseTests(unittest.TestCase):

    def setUp(self):
        if not Path(DB_PATH).exists():
            self.skipTest("поставочной БД нет в этой сборке")
        # Работаем с КОПИЕЙ: проверка не имеет права стать ещё одним
        # писателем в файл, который сама и защищает.
        self.copy = temp_path(suffix=".db")
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

    def test_file_is_unchanged_against_the_commit(self):
        """
        Заслон против того, что уже случалось: база меняется от любого
        прикосновения — слой доступа заводит служебные таблицы, переводит
        журнал, прогоняет миграции. Каждый раз это уезжало бы в коммит
        двоичной строкой, в которой не видно ничего.

        Правило: в разовых сценариях `Repository` открывают на КОПИИ, а
        не на `const.DB_PATH`.

        Проверка пропускается там, где git недоступен (собранная
        поставка): она про дисциплину разработки, а не про свойство файла.
        """
        import subprocess

        root = Path(__file__).resolve().parent.parent
        try:
            done = subprocess.run(
                ["git", "diff", "--quiet", "--",
                 str(Path(DB_PATH).relative_to(root))],
                cwd=root, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError, ValueError):
            self.skipTest("git недоступен — проверка только для рабочей копии")
        self.assertEqual(
            done.returncode, 0,
            "Поставочная база изменилась относительно коммита. Если "
            "правка НЕ намеренная — верните файл: git checkout -- "
            "resources/users_database.db.")

    def test_shipped_resources_are_unchanged_against_the_commit(self):
        """
        То же самое, но про ВСЮ поставку, а не только про базу.

        Проверка расширена по случаю: тест задания на произношение
        подставил виджету записи поставочный эталон, а очистка после
        ответа удалила файл — и так ушло восемь WAV из `resources/audio/`.
        Прежний заслон этого не увидел, потому что смотрел на один файл.

        Класс тот же, что у базы: рабочая копия — это ещё и ПОСТАВКА, и
        всё, что в ней лежит, прогон обязан оставить нетронутым. Заслон
        стоит здесь, рядом с родственным, а не заводится третьим местом,
        где помнят про это правило.
        """
        import subprocess

        root = Path(__file__).resolve().parent.parent
        try:
            done = subprocess.run(
                ["git", "status", "--porcelain", "--", "resources"],
                cwd=root, capture_output=True, timeout=30, text=True)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git недоступен — проверка только для рабочей копии")
        touched = [line for line in done.stdout.splitlines() if line.strip()]
        self.assertEqual(
            touched, [],
            "Поставочные ресурсы изменились относительно коммита:\n"
            + "\n".join(touched)
            + "\nЕсли правка НЕ намеренная — верните: git checkout -- resources")

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
