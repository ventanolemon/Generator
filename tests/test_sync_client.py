"""
Тесты клиента offline-sync (core/sync/): outbox, переживающий рестарт и
логаут; идемпотентная повторная отправка; конфликт двух устройств
(стэшируется, не перезаписывается тихо); tombstone применяется как
локальное удаление; курсорная пагинация без потерь и дублей при обрыве.

Сервер — фейк в памяти с той же семантикой протокола, что
GenerationWeb/core/sync_api.py (version-check, глобально монотонный
row_version, tombstones, страницы + has_more). Серверная сторона проверена
своими тестами в репо GenerationWeb (core/test_sync_protocol.py) — здесь
предмет проверки именно КЛИЕНТ.

Запуск: python -m unittest tests.test_sync_client -v  (headless, без Qt)
"""

from __future__ import annotations
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.repository import Repository  # noqa: E402
from core.sync import SyncClient, SyncStore  # noqa: E402


# ---------- Фейк-сервер протокола ----------

class FakeServer:
    """Минимальный сервер sync-протокола в памяти (семантика §2–§4)."""

    def __init__(self):
        self.version_seq = {"subject": 0, "partition": 0}
        # kind -> id -> {данные..., row_version, deleted}
        self.entities = {"subject": {}, "partition": {}}
        self.next_id = {"subject": 100, "partition": 100}
        self.attempts: dict[str, dict] = {}
        self.push_calls = 0
        self.pull_calls = 0
        self.fail_next_push = False
        self.fail_after_push_applied = False
        self.fail_next_pull = False

    # -- наполнение сервера напрямую (правки «другого устройства») --

    def seed(self, kind: str, entity_id: int, data: dict) -> int:
        ver = self._next_version(kind)
        self.entities[kind][entity_id] = {**data, "id": entity_id,
                                          "row_version": ver, "deleted": False}
        return ver

    def server_delete(self, kind: str, entity_id: int) -> None:
        e = self.entities[kind][entity_id]
        e["deleted"] = True
        e["row_version"] = self._next_version(kind)

    def _next_version(self, kind: str) -> int:
        self.version_seq[kind] += 1
        return self.version_seq[kind]

    # -- транспорт --

    def transport(self, path: str, payload: dict) -> dict:
        if path == "/sync/push":
            return self._push(payload)
        if path == "/sync/pull":
            return self._pull(payload)
        raise AssertionError(f"неизвестный путь {path}")

    def _push(self, payload: dict) -> dict:
        self.push_calls += 1
        if self.fail_next_push:
            self.fail_next_push = False
            raise ConnectionError("сеть оборвалась до сервера")
        for a in payload.get("attempts", []):
            self.attempts.setdefault(a["client_uuid"], a)
        accepted, conflicts = [], []
        for ch in payload.get("changed_entities", []):
            kind, eid = ch["kind"], ch.get("id")
            row = self.entities[kind].get(eid) if eid is not None else None
            if row is None:
                new_id = self.next_id[kind]
                self.next_id[kind] += 1
                ver = self._next_version(kind)
                self.entities[kind][new_id] = {**(ch.get("data") or {}),
                                               "id": new_id,
                                               "row_version": ver,
                                               "deleted": False}
                accepted.append({"kind": kind, "id": new_id,
                                 "local_ref": ch.get("local_ref"),
                                 "row_version": ver, "created": True})
            elif row["row_version"] != ch.get("base_version"):
                conflicts.append({"kind": kind, "id": eid,
                                  "mine": ch.get("data"),
                                  "theirs": dict(row)})
            else:
                ver = self._next_version(kind)
                if ch.get("deleted"):
                    row["deleted"] = True
                else:
                    row.update(ch.get("data") or {})
                row["row_version"] = ver
                accepted.append({"kind": kind, "id": eid,
                                 "local_ref": ch.get("local_ref"),
                                 "row_version": ver,
                                 "deleted": bool(ch.get("deleted"))})
        if self.fail_after_push_applied:
            self.fail_after_push_applied = False
            raise ConnectionError("ответ push потерян по дороге")
        return {"attempts_received": len(payload.get("attempts", [])),
                "attempts_new": 0, "accepted": accepted, "conflicts": conflicts}

    def _pull(self, payload: dict) -> dict:
        self.pull_calls += 1
        if self.fail_next_pull:
            self.fail_next_pull = False
            raise ConnectionError("обрыв посреди pull")
        cursors = payload.get("cursors") or {}
        limit = int(payload.get("limit") or 200)
        out = {"subjects": [], "partitions": [], "deleted": [],
               "new_cursors": dict(cursors), "has_more": False,
               "resources": {"catalog_version": "fake"}}
        for kind, plural in (("subject", "subjects"), ("partition", "partitions")):
            cur = int(cursors.get(plural) or 0)
            rows = sorted(
                (e for e in self.entities[kind].values()
                 if e["row_version"] > cur),
                key=lambda e: e["row_version"],
            )
            if len(rows) > limit:
                rows = rows[:limit]
                out["has_more"] = True
            new_cur = cur
            for e in rows:
                new_cur = max(new_cur, e["row_version"])
                if e["deleted"]:
                    out["deleted"].append({"kind": kind, "id": e["id"],
                                           "row_version": e["row_version"]})
                else:
                    out[plural].append(dict(e))
            out["new_cursors"][plural] = new_cur
        return out


# ---------- База тестов ----------

def _make_local_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE Subjects (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_name  TEXT NOT NULL DEFAULT '',
                pra_subject   TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE Partitions (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_id           INTEGER NOT NULL DEFAULT 0,
                partition_name       TEXT NOT NULL DEFAULT '',
                constracted          INTEGER NOT NULL DEFAULT 0,
                generation_parametrs TEXT NOT NULL DEFAULT ''
            );
        """)


class SyncClientTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        _make_local_db(self.db_path)
        self.repo = Repository(self.db_path)
        self.store = SyncStore(self.db_path)
        self.server = FakeServer()
        self.client = SyncClient(self.repo, self.store,
                                 transport=self.server.transport)

    def tearDown(self):
        os.unlink(self.db_path)

    def _local_partition_names(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            return [r[0] for r in conn.execute(
                "SELECT partition_name FROM Partitions ORDER BY id")]


class OutboxPersistenceTests(SyncClientTestBase):
    """§5: outbox переживает логаут и перезапуск, уходит при первом sync."""

    def test_outbox_survives_restart_and_logout(self):
        self.client.queue_attempt(7, {"answer": "42"}, correct=True)
        self.client.queue_partition_change(
            None, {"subject_id": 1, "partition_name": "Офлайн",
                   "constracted": 0, "generation_parametrs": ""},
            local_ref="1")
        device_before = self.store.device_id()

        # «Перезапуск приложения + логаут»: все объекты пересоздаются с нуля
        # от того же файла БД; токенов у нас нет вовсе — очередь в БД.
        store2 = SyncStore(self.db_path)
        repo2 = Repository(self.db_path)
        client2 = SyncClient(repo2, store2, transport=self.server.transport,
                             user_id=None)

        self.assertEqual(len(store2.pending()), 2, "outbox не потерялся")
        self.assertEqual(store2.device_id(), device_before,
                         "device_id стабилен между запусками")

        report = client2.sync()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(store2.pending(), [], "очередь ушла при первом sync")
        self.assertEqual(len(self.server.attempts), 1)

    def test_push_failure_keeps_outbox_intact(self):
        self.client.queue_attempt(7, {"answer": "x"})
        self.server.fail_next_push = True

        report = self.client.sync()
        self.assertFalse(report.ok)
        self.assertEqual(len(self.store.pending()), 1, "ничего не потеряно")

        report = self.client.sync()   # сеть вернулась
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(self.store.pending(), [])


class IdempotencyTests(SyncClientTestBase):
    """§3: повторная отправка после потерянного ответа не дублирует."""

    def test_lost_ack_resend_is_not_duplicated(self):
        self.client.queue_attempt(7, {"answer": "42"})
        # Сервер применил пуш, но ответ до клиента не дошёл.
        self.server.fail_after_push_applied = True

        report = self.client.sync()
        self.assertFalse(report.ok)
        self.assertEqual(len(self.store.pending()), 1,
                         "без подтверждения запись остаётся в очереди")
        self.assertEqual(len(self.server.attempts), 1,
                         "сервер пуш уже применил")

        report = self.client.sync()   # повторная отправка того же пакета
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(self.store.pending(), [])
        self.assertEqual(len(self.server.attempts), 1,
                         "upsert по client_uuid: дубля нет")


class ConflictTests(SyncClientTestBase):
    """§2: конфликт стэшируется с обеими версиями, сервер авторитетен."""

    def test_concurrent_edit_conflict_is_stashed_not_silent(self):
        # Начальное состояние: сервер знает партицию, клиент её притянул.
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Общая",
            "constracted": 0, "generation_parametrs": ""})
        self.assertTrue(self.client.sync().ok)
        base = self.store.get_version("partition", 10)
        self.assertGreater(base, 0)

        # Устройство B (напрямую на сервере) успело раньше.
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Правка устройства B",
            "constracted": 0, "generation_parametrs": ""})

        # Наша офлайн-правка от старой базовой версии.
        self.client.queue_partition_change(10, {
            "subject_id": 1, "partition_name": "Правка устройства A",
            "constracted": 0, "generation_parametrs": ""})

        report = self.client.sync()
        self.assertTrue(report.ok, report.errors)
        self.assertEqual(report.conflicts, 1)

        conflicts = self.store.unresolved_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["mine"]["partition_name"],
                         "Правка устройства A")
        self.assertEqual(conflicts[0]["theirs"]["partition_name"],
                         "Правка устройства B")

        # Pull применил серверную версию (сервер авторитетен, §2);
        # моя правка не потеряна — она в стэше конфликтов.
        self.assertIn("Правка устройства B", self._local_partition_names())

    def test_accepted_edit_updates_base_version(self):
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Моя",
            "constracted": 0, "generation_parametrs": ""})
        self.client.sync()
        v1 = self.store.get_version("partition", 10)

        self.client.queue_partition_change(10, {
            "subject_id": 1, "partition_name": "Моя v2",
            "constracted": 0, "generation_parametrs": ""})
        report = self.client.sync()
        self.assertEqual(report.accepted_entities, 1)
        self.assertEqual(report.conflicts, 0)
        self.assertGreater(self.store.get_version("partition", 10), v1)

    def test_created_offline_entity_remaps_to_server_id(self):
        # Локально созданная партиция с локальным id.
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "INSERT INTO Partitions (subject_id, partition_name, "
                " constracted, generation_parametrs) VALUES (1, 'Новая', 0, '')")
            local_id = cur.lastrowid
            conn.commit()
        self.client.queue_partition_change(
            None, {"subject_id": 1, "partition_name": "Новая",
                   "constracted": 0, "generation_parametrs": ""},
            local_ref=str(local_id))

        report = self.client.sync()
        self.assertTrue(report.ok, report.errors)
        server_id = next(iter(self.server.entities["partition"]))
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id FROM Partitions WHERE partition_name = 'Новая'"
            ).fetchone()
        self.assertEqual(row[0], server_id, "локальный id перепривязан")


class TombstoneTests(SyncClientTestBase):
    """§2: tombstone сервера применяется как локальное удаление."""

    def test_tombstone_applied_as_local_delete(self):
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Обречённая",
            "constracted": 0, "generation_parametrs": ""})
        self.client.sync()
        self.assertIn("Обречённая", self._local_partition_names())

        # Другое устройство удалило на сервере.
        self.server.server_delete("partition", 10)

        report = self.client.sync()
        self.assertEqual(report.deleted_applied, 1)
        self.assertNotIn("Обречённая", self._local_partition_names())
        self.assertEqual(self.store.get_version("partition", 10), 0,
                         "версия сущности забыта")


class PaginationTests(SyncClientTestBase):
    """§4: страницы pull; обрыв между страницами не теряет и не дублирует."""

    def test_pull_pages_all_rows_once(self):
        for i in range(7):
            self.server.seed("partition", 10 + i, {
                "subject_id": 1, "partition_name": f"P{i}",
                "constracted": 0, "generation_parametrs": ""})
        # Мелкие страницы, чтобы пагинация точно случилась.
        import core.sync.client as client_mod
        old = client_mod.PULL_PAGE_LIMIT
        client_mod.PULL_PAGE_LIMIT = 3
        try:
            report = self.client.sync()
        finally:
            client_mod.PULL_PAGE_LIMIT = old
        self.assertTrue(report.ok, report.errors)
        self.assertGreaterEqual(report.pages, 3)
        names = self._local_partition_names()
        self.assertEqual(sorted(names), [f"P{i}" for i in range(7)])
        self.assertEqual(len(names), len(set(names)), "без дублей")

    def test_interrupted_pull_resumes_from_saved_cursor(self):
        for i in range(4):
            self.server.seed("partition", 10 + i, {
                "subject_id": 1, "partition_name": f"P{i}",
                "constracted": 0, "generation_parametrs": ""})
        import core.sync.client as client_mod
        old = client_mod.PULL_PAGE_LIMIT
        client_mod.PULL_PAGE_LIMIT = 2
        try:
            # Первая страница применяется, вторая обрывается.
            orig = self.server.transport
            calls = {"pull": 0}

            def flaky(path, payload):
                if path == "/sync/pull":
                    calls["pull"] += 1
                    if calls["pull"] == 2:
                        raise ConnectionError("обрыв между страницами")
                return orig(path, payload)

            self.client._transport = flaky
            report = self.client.sync()
            self.assertFalse(report.ok)
            self.assertEqual(report.pulled_partitions, 2,
                             "первая страница применена")

            # Возобновление: курсор пережил обрыв, вторая страница доехала.
            self.client._transport = orig
            report = self.client.sync()
            self.assertTrue(report.ok, report.errors)
        finally:
            client_mod.PULL_PAGE_LIMIT = old

        names = self._local_partition_names()
        self.assertEqual(sorted(names), ["P0", "P1", "P2", "P3"])
        self.assertEqual(len(names), len(set(names)),
                         "продолжение с курсора: без потерь и дублей")


if __name__ == "__main__":
    unittest.main()
