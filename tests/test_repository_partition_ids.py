"""
Регрессия: раздел constracted=4 (граф), севший на id из динамического
диапазона «1000 + число словарей», молча вытесняется английским генератором
в bootstrap.build_registry (id словарей пересчитывается заново при каждом
запуске из resources/words/*.json — растёт вместе с числом файлов и никак не
согласован с id остальных разделов).

Баг воспроизводился так: seed-скрипт вставлял «Ряды»/«Комплексный анализ»
через upsert_partition БЕЗ явного id → SQLite подбирал следующий свободный
rowid (1019+) — свободный в момент сева, но не защищённый от того, что у
пользователя окажется больше словарей и диапазон 1000+i дорастёт до тех же
чисел. Раздел не пропадал из БД (список показывал верное имя), но при клике
открывался чужой (английский) генератор — `build_registry` регистрирует
словари первыми, а строка `if registry.has(part.id): continue` тихо
пропускает раздел с совпавшим id.

Тесты проверяют: (1) upsert_partition с partition_id вставляет ровно в
указанный id; (2) даже при большом числе «словарей» явный id вне диапазона
1000+i не перехватывается; (3) collision (когда её всё же намеренно
устроить) теперь не тихая — build_registry-подобный цикл предупреждает
через warnings.
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import unittest
import warnings
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import GeneratorRegistry, Repository


def _fresh_repo() -> tuple[Repository, str]:
    """Пустая БД со схемой Subjects/Partitions во временном файле."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE Subjects (
            id INTEGER PRIMARY KEY, subject_name TEXT UNIQUE, pra_subject TEXT
        );
        CREATE TABLE Partitions (
            id INTEGER PRIMARY KEY, subject_id INTEGER, partition_name TEXT,
            constracted INTEGER, generation_parametrs TEXT
        );
    """)
    conn.commit()
    conn.close()
    return Repository(path), path


class UpsertPartitionExplicitIdTests(unittest.TestCase):
    def setUp(self):
        self.repo, self.path = _fresh_repo()

    def tearDown(self):
        os.unlink(self.path)

    def test_explicit_partition_id_is_used(self):
        sid = self.repo.ensure_subject(1, "Тест", "Тест")
        pid = self.repo.upsert_partition(
            subject_id=sid, name="A", constracted=4,
            generation_params={"nodes": [], "edges": []}, partition_id=9000,
        )
        self.assertEqual(pid, 9000)
        part = self.repo.get_partition(9000)
        self.assertEqual(part.name, "A")
        self.assertEqual(part.constracted, 4)

    def test_without_explicit_id_uses_autoincrement(self):
        sid = self.repo.ensure_subject(1, "Тест", "Тест")
        pid = self.repo.upsert_partition(
            subject_id=sid, name="B", constracted=4,
            generation_params={"nodes": [], "edges": []},
        )
        self.assertIsInstance(pid, int)
        self.assertIsNone(self.repo.get_partition(9000))  # не занял чужой id

    def test_second_upsert_by_same_name_keeps_original_id(self):
        sid = self.repo.ensure_subject(1, "Тест", "Тест")
        pid1 = self.repo.upsert_partition(
            subject_id=sid, name="C", constracted=4,
            generation_params={"nodes": [1], "edges": []}, partition_id=9005,
        )
        pid2 = self.repo.upsert_partition(
            subject_id=sid, name="C", constracted=4,
            generation_params={"nodes": [1, 2], "edges": []}, partition_id=9999,
        )
        self.assertEqual(pid1, pid2, "id не должен сдвигаться при повторном upsert")
        self.assertEqual(self.repo.get_partition(9005).generation_params["nodes"],
                         [1, 2])

    def test_explicit_id_conflicting_with_existing_row_raises(self):
        sid = self.repo.ensure_subject(1, "Тест", "Тест")
        self.repo.upsert_partition(
            subject_id=sid, name="D", constracted=4,
            generation_params={}, partition_id=9010,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.upsert_partition(
                subject_id=sid, name="E", constracted=4,
                generation_params={}, partition_id=9010,
            )


class DynamicIdCollisionRegressionTests(unittest.TestCase):
    """Воспроизводит именно баг: словари 1000+i против сида без явного id."""

    def setUp(self):
        self.repo, self.path = _fresh_repo()

    def tearDown(self):
        os.unlink(self.path)

    def _fake_registry_with_dictionaries(self, count: int) -> GeneratorRegistry:
        """N словарей, зарегистрированных как построит их build_registry."""
        from core.generator import TaskGenerator

        class _FakeDictGenerator(TaskGenerator):
            def __init__(self, partition_id, name):
                self.partition_id = partition_id
                self.name = name

            def generate(self):
                raise NotImplementedError

        registry = GeneratorRegistry()
        for i in range(count):
            registry.register(_FakeDictGenerator(1000 + i, f"словарь-{i}"))
        return registry

    def _seed_up_to_id(self, sid: int, last_id: int) -> None:
        """Затравка: как в реальной БД, где до сева уже существовал раздел с
        id=1018 (пользовательская «Группа_2») — следующий upsert без явного
        id продолжит нумерацию оттуда, а не с 1."""
        self.repo.upsert_partition(
            subject_id=sid, name="filler", constracted=2,
            generation_params={}, partition_id=last_id,
        )

    def test_autoincrement_seed_can_collide_with_many_dictionaries(self):
        """Демонстрация бага (без фикса): сид без явного id может утонуть."""
        sid = self.repo.ensure_subject(1, "Ряды", "Матан")
        # Как в реальной БД: до сева уже существует раздел с id=1018 —
        # следующий upsert без явного id продолжит нумерацию оттуда (1019).
        self._seed_up_to_id(sid, 1018)
        pid = self.repo.upsert_partition(
            subject_id=sid, name="№1. Сходимость", constracted=4,
            generation_params={"nodes": [], "edges": []},
        )
        # Если у пользователя окажется >= (pid - 999) словарей, id столкнётся.
        registry = self._fake_registry_with_dictionaries(count=pid - 999)
        self.assertTrue(registry.has(pid),
                        "воспроизведение бага: id сида перекрыт словарями")

    def test_explicit_safe_range_never_collides(self):
        """Фикс: явный id из диапазона 9000+ не пересекается даже с 500
        'словарями' — используется вместо автоинкремента для библиотек-сидов."""
        sid = self.repo.ensure_subject(1, "Ряды", "Матан")
        for i in range(19):
            self.repo.upsert_partition(
                subject_id=sid, name=f"filler-{i}", constracted=2,
                generation_params={},
            )
        pid = self.repo.upsert_partition(
            subject_id=sid, name="№1. Сходимость", constracted=4,
            generation_params={"nodes": [], "edges": []}, partition_id=9000,
        )
        self.assertEqual(pid, 9000)
        registry = self._fake_registry_with_dictionaries(count=500)
        self.assertFalse(registry.has(pid),
                         "фикс: явный id 9000+ должен быть вне зоны словарей")

    def test_build_registry_style_loop_warns_on_collision(self):
        """Воспроизводит цикл шага 3 bootstrap.build_registry: раздел с
        занятым id должен теперь предупреждать через warnings, не молчать."""
        sid = self.repo.ensure_subject(1, "Ряды", "Матан")
        self._seed_up_to_id(sid, 1018)
        pid = self.repo.upsert_partition(
            subject_id=sid, name="№1. Сходимость", constracted=4,
            generation_params={"nodes": [], "edges": []},
        )
        registry = self._fake_registry_with_dictionaries(count=pid - 999)
        self.assertTrue(registry.has(pid))

        # Тот же паттерн, что в bootstrap.build_registry шаг 3.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for part in self.repo.list_partitions_for_subject(sid):
                if registry.has(part.id):
                    warnings.warn(
                        f"partition_id={part.id} раздела {part.name!r} "
                        f"уже занят другим генератором в реестре."
                    )
                    continue
        messages = [str(w.message) for w in caught]
        self.assertTrue(any(str(pid) in m for m in messages),
                        f"ожидал предупреждение про id={pid}, получил {messages}")


if __name__ == "__main__":
    unittest.main()
