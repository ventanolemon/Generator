"""
Перенос словарей английского со старых позиционных номеров на выведенные
из имени — и то, ради чего перенос затевался.

Проверяемое свойство одно, и оно про ДВЕ машины: каталоги словарей у
сервера и десктопа разной длины, и при старой схеме `1000 + место в
списке` один и тот же номер означал разные словари. Синхронизация
переносит разделы по номеру — значит, задание, выданное на сервере,
открывало на десктопе другой словарь, ничего об этом не сообщая.

Отдельно проверяется, что перенос не ломает то, что работало: личные
скрытия и состав групп ссылаются на номер раздела, и строка, переехавшая
без своих ссылок, была бы хуже исходного дефекта.

Запуск:
    python -m unittest tests.test_partition_id_migration
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import bootstrap
from core import Repository, partition_ids
from core.tmpdb import temp_path  # noqa: E402


DICTIONARY = json.dumps(
    {"title": "Проверочный словарь", "words": {"cat": "кошка", "dog": "собака"}},
    ensure_ascii=False,
)


def _words_dir(stems: list[str]) -> Path:
    directory = Path(tempfile.mkdtemp())
    for stem in stems:
        (directory / f"{stem}.json").write_text(DICTIONARY, encoding="utf-8")
    return directory


def _fresh_db() -> str:
    path = temp_path(suffix=".db")
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT, pra_subject TEXT
        );
        CREATE TABLE Partitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_id INTEGER REFERENCES Subjects (id),
            partition_name NOT NULL, constracted INTEGER,
            generation_parametrs
        );
        CREATE TABLE users (
            login TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
            FIO TEXT, "group" TEXT
        );
    """)
    conn.commit()
    conn.close()
    return path


class TwoMachinesTests(unittest.TestCase):
    """Тот самый дефект: разные каталоги — одинаковые номера."""

    SHARED = ["unit1_history", "unit2_types", "unit3_hardware"]

    def test_same_dictionary_gets_the_same_id_on_both_sides(self):
        server = _words_dir(["aaa_extra", *self.SHARED, "zzz_extra"])
        desktop = _words_dir(self.SHARED)
        on_server = bootstrap.english_partition_ids(server)
        on_desktop = bootstrap.english_partition_ids(desktop)
        for stem in self.SHARED:
            with self.subTest(stem=stem):
                self.assertEqual(on_server[stem], on_desktop[stem])

    def test_the_old_scheme_did_diverge(self):
        """
        Регрессия наоборот: без неё проверка выше не отличается от
        «схема всегда работала».
        """
        server = sorted(["aaa_extra", *self.SHARED, "zzz_extra"])
        desktop = sorted(self.SHARED)
        old_server = {s: 1000 + i for i, s in enumerate(server)}
        old_desktop = {s: 1000 + i for i, s in enumerate(desktop)}
        diverged = [s for s in self.SHARED
                    if old_server[s] != old_desktop[s]]
        self.assertTrue(diverged, "старая схема должна была расходиться")


class MigrationTests(unittest.TestCase):

    def setUp(self):
        self.db = _fresh_db()
        self.repo = Repository(self.db)
        self.words = _words_dir(["unit1_history", "unit2_types"])
        self.addCleanup(lambda: os.path.exists(self.db) and os.unlink(self.db))

    def _seed_legacy(self) -> dict[str, int]:
        """Разложить словари по СТАРОЙ схеме, как в существующих установках."""
        self.repo.ensure_subject(2, "Английский", "Английский")
        legacy: dict[str, int] = {}
        for i, path in enumerate(sorted(self.words.glob("*.json"))):
            pid = 1000 + i
            self.repo.ensure_code_partition(
                partition_id=pid, subject_id=2,
                name=bootstrap._english_display_name(path))
            legacy[path.stem] = pid
        return legacy

    def _sync(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bootstrap.sync_database(self.repo, self.words)

    def test_legacy_rows_move_to_their_name_derived_id(self):
        legacy = self._seed_legacy()
        self._sync()
        ids = {p.name: p.id for p in self.repo.list_partitions_for_subject(2)}
        for stem, old in legacy.items():
            expected = partition_ids.english_words_id(stem)
            with self.subTest(stem=stem):
                self.assertIn(f"Английский: {stem}", ids)
                self.assertEqual(ids[f"Английский: {stem}"], expected)
                self.assertNotEqual(expected, old)

    def test_no_duplicate_row_is_left_behind(self):
        """Перенос, а не копия: словарь не должен появиться в списке дважды."""
        self._seed_legacy()
        self._sync()
        names = [p.name for p in self.repo.list_partitions_for_subject(2)]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(names), 2)

    def test_dictionary_without_a_file_is_removed(self):
        """
        Пять таких разделов лежали в поставочной БД: файлы переименованы,
        записи остались. Открыть нельзя, а в списке стоят наравне
        с рабочими.
        """
        self.repo.ensure_subject(2, "Английский", "Английский")
        self.repo.ensure_code_partition(
            partition_id=1050, subject_id=2,
            name="Английский: dictionary_that_was_renamed")
        self._sync()
        names = [p.name for p in self.repo.list_partitions_for_subject(2)]
        self.assertNotIn("Английский: dictionary_that_was_renamed", names)

    def test_group_membership_follows_the_move(self):
        """
        Состав группы ссылается на номер раздела. Строка, переехавшая без
        своих ссылок, оставила бы группу указывающей в пустоту.
        """
        legacy = self._seed_legacy()
        moved = legacy["unit1_history"]
        group_id = self.repo.upsert_partition(
            subject_id=2, name="Группа со словарём", constracted=2,
            generation_params=[{"task_id": moved, "task_name": "словарь",
                                "constracted": 0}],
        )
        self._sync()
        group = [p for p in self.repo.list_partitions_for_subject(2)
                 if p.id == group_id][0]
        # Repository нормализует список в {"data": [...]}.
        members = group.generation_params.get("data", group.generation_params)
        self.assertEqual(members[0]["task_id"],
                         partition_ids.english_words_id("unit1_history"))

    def test_personal_hiding_follows_the_move(self):
        legacy = self._seed_legacy()
        moved = legacy["unit2_types"]
        self.repo.set_partition_hidden(moved, True, user_login="teacher")
        self._sync()
        new_id = partition_ids.english_words_id("unit2_types")
        hidden = {p.id: p.hidden for p in self.repo.list_partitions_for_subject(
            2, include_hidden=True, user_login="teacher")}
        self.assertTrue(hidden.get(new_id),
                        "скрытие осталось на старом номере")

    def test_migration_is_idempotent(self):
        self._seed_legacy()
        self._sync()
        first = sorted(p.id for p in self.repo.list_partitions_for_subject(2))
        self._sync()
        second = sorted(p.id for p in self.repo.list_partitions_for_subject(2))
        self.assertEqual(first, second)


class CoverageTests(unittest.TestCase):
    """«У каждого раздела есть чем его обслужить» — проверка на старте."""

    def setUp(self):
        self.db = _fresh_db()
        self.repo = Repository(self.db)
        self.words = _words_dir(["unit1_history"])
        self.addCleanup(lambda: os.path.exists(self.db) and os.unlink(self.db))

    def test_code_partition_without_a_generator_is_reported(self):
        self.repo.ensure_subject(3, "Физика", "Физика")
        self.repo.ensure_code_partition(
            partition_id=777, subject_id=3, name="раздел без кода")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            registry = bootstrap.build_registry(self.repo, self.words)
        found = bootstrap.unserved_partitions(self.repo, registry)
        self.assertIn((777, "раздел без кода", "Физика"), found)

    def test_shipped_database_is_clean_after_sync(self):
        """Ради этого всё и делалось: после старта открывается всё."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bootstrap.sync_database(self.repo, self.words)
            registry = bootstrap.build_registry(self.repo, self.words)
        self.assertEqual(bootstrap.unserved_partitions(self.repo, registry), [])


class PhysicsConstructorTests(unittest.TestCase):
    """Раздел «конструктор» Физики: constracted=0 без кода — и клик падал."""

    def setUp(self):
        self.db = _fresh_db()
        self.repo = Repository(self.db)
        self.addCleanup(lambda: os.path.exists(self.db) and os.unlink(self.db))
        self.repo.ensure_subject(3, "Физика", "Физика")

    def test_unconfigured_constructor_becomes_editable_and_generates(self):
        self.repo.ensure_code_partition(
            partition_id=2, subject_id=3, name="конструктор")
        self.assertTrue(bootstrap._repair_physics_constructor(self.repo))
        part = [p for p in self.repo.list_partitions_for_subject(3)
                if p.id == 2][0]
        self.assertEqual(part.constracted, 1)

        words = _words_dir(["unit1_history"])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            registry = bootstrap.build_registry(self.repo, words)
        task = registry.get(2, part.generation_params).generate()
        self.assertTrue(task.statement[0].render_plain().strip())
        self.assertIsNotNone(task.answer_spec)

    def test_configured_section_is_left_alone(self):
        """Настроенный раздел — работа преподавателя, её не перезаписывают."""
        self.repo.upsert_partition(
            subject_id=3, name="конструктор", constracted=1,
            generation_params={"condition": "моё условие #x#",
                               "result_letter": "y", "formula": "x",
                               "dimension": "",
                               "variables": {"x": {"min": 1, "max": 2}}},
            partition_id=2,
        )
        self.assertFalse(bootstrap._repair_physics_constructor(self.repo))
        part = [p for p in self.repo.list_partitions_for_subject(3)][0]
        self.assertEqual(part.generation_params["condition"], "моё условие #x#")


if __name__ == "__main__":
    unittest.main()
