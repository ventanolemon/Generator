"""
SyncStore — локальное состояние синхронизации в ТОЙ ЖЕ SQLite-БД десктопа.

Схема приложения (Subjects/Partitions) не трогается: вся бухгалтерия sync —
в отдельных таблицах. Это сознательная граница: приложение работает с БД
как раньше и без модуля sync, а сам модуль самодостаточен.

  sync_state     key/value: device_id, курсоры pull, идентификация
  sync_outbox    очередь исходящих изменений (attempts + правки сущностей);
                 переживает и логаут, и перезапуск (protocol §5) — это
                 просто строки в БД, токены здесь ни при чём
  sync_versions  серверный row_version каждой сущности = base_version
                 для push (то, от чего пользователь правил, — состояние
                 последнего sync)
  sync_conflicts обе версии конфликтной сущности целиком — материал для
                 будущего диалога разрешения (UI вне этого модуля)
"""

from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


class SyncStore:
    """Локальный журнал синхронизации поверх файла БД десктопа."""

    def __init__(self, db_path: "str | Path"):
        self.db_path = Path(db_path)
        self._ensure_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_outbox (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind       TEXT    NOT NULL,   -- attempt | entity
                    payload    TEXT    NOT NULL,   -- JSON
                    created_at REAL    NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sync_versions (
                    kind        TEXT    NOT NULL,  -- subject | partition
                    entity_id   INTEGER NOT NULL,
                    row_version INTEGER NOT NULL,
                    PRIMARY KEY (kind, entity_id)
                );
                CREATE TABLE IF NOT EXISTS sync_conflicts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_kind TEXT NOT NULL,
                    entity_id   INTEGER,
                    mine        TEXT NOT NULL,     -- JSON: моя версия целиком
                    theirs      TEXT NOT NULL,     -- JSON: серверная целиком
                    created_at  REAL NOT NULL,
                    resolved_at REAL
                );
            """)
            conn.commit()

    # ---------- key/value ----------

    def _get(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM sync_state WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()

    def device_id(self) -> str:
        """Стабильный идентификатор устройства (protocol §5): генерируется
        один раз, дальше живёт в БД — переживает логаут и переустановку
        аккаунта, привязан к копии данных."""
        did = self._get("device_id")
        if not did:
            did = uuid.uuid4().hex
            self._set("device_id", did)
        return did

    def get_cursors(self) -> dict:
        raw = self._get("cursors")
        return json.loads(raw) if raw else {}

    def set_cursors(self, cursors: dict) -> None:
        self._set("cursors", json.dumps(cursors))

    # ---------- outbox ----------

    def enqueue_attempt(self, attempt: dict) -> int:
        """Поставить попытку в очередь. client_uuid назначается здесь —
        идемпотентность повторной отправки обеспечена до первого ухода
        в сеть."""
        payload = dict(attempt)
        payload.setdefault("client_uuid", str(uuid.uuid4()))
        payload.setdefault("created_at", time.time())
        return self._enqueue("attempt", payload)

    def enqueue_entity_change(
        self,
        kind: str,
        entity_id: Optional[int],
        data: dict,
        *,
        deleted: bool = False,
        local_ref: Optional[str] = None,
    ) -> int:
        """
        Поставить правку сущности. base_version НЕ фиксируется здесь: он
        резолвится в момент push из sync_versions — «версия последнего
        sync» и есть та, от которой пользователь правил. Несколько правок
        одной сущности до sync схлопываются в одну (последняя побеждает —
        это одна и та же локальная сущность).
        """
        with self._connect() as conn:
            # Схлопывание: предыдущая незакрытая правка той же сущности
            # заменяется (иначе push отправит устаревшие промежуточные).
            if entity_id is not None:
                conn.execute(
                    "DELETE FROM sync_outbox WHERE kind = 'entity' AND "
                    "json_extract(payload, '$.kind') = ? AND "
                    "json_extract(payload, '$.id') = ?",
                    (kind, entity_id),
                )
            payload = {
                "kind": kind, "id": entity_id, "deleted": deleted,
                "data": data, "local_ref": local_ref,
            }
            cur = conn.execute(
                "INSERT INTO sync_outbox (kind, payload, created_at) "
                "VALUES ('entity', ?, ?)",
                (json.dumps(payload, ensure_ascii=False), time.time()),
            )
            conn.commit()
            return cur.lastrowid

    def _enqueue(self, kind: str, payload: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sync_outbox (kind, payload, created_at) "
                "VALUES (?, ?, ?)",
                (kind, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            conn.commit()
            return cur.lastrowid

    def pending(self) -> list[dict]:
        """Все неотправленные записи outbox (порядок постановки)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, kind, payload FROM sync_outbox ORDER BY id"
            ).fetchall()
        return [
            {"outbox_id": r[0], "kind": r[1], "payload": json.loads(r[2])}
            for r in rows
        ]

    def remove(self, outbox_ids: list[int]) -> None:
        if not outbox_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM sync_outbox WHERE id = ?",
                [(i,) for i in outbox_ids],
            )
            conn.commit()

    # ---------- версии сущностей (base_version) ----------

    def get_version(self, kind: str, entity_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT row_version FROM sync_versions "
                "WHERE kind = ? AND entity_id = ?",
                (kind, entity_id),
            ).fetchone()
        return int(row[0]) if row else 0

    def set_version(self, kind: str, entity_id: int, version: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_versions (kind, entity_id, row_version) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(kind, entity_id) DO UPDATE SET "
                "row_version = excluded.row_version",
                (kind, entity_id, version),
            )
            conn.commit()

    def drop_version(self, kind: str, entity_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM sync_versions WHERE kind = ? AND entity_id = ?",
                (kind, entity_id),
            )
            conn.commit()

    def remap_entity_id(self, kind: str, old_id: int, new_id: int) -> None:
        """Созданная офлайн сущность получила серверный id."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE sync_versions SET entity_id = ? "
                "WHERE kind = ? AND entity_id = ?",
                (new_id, kind, old_id),
            )
            conn.commit()

    # ---------- конфликты (материал для будущего UI) ----------

    def record_conflict(self, conflict: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sync_conflicts "
                "(entity_kind, entity_id, mine, theirs, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(conflict.get("kind") or ""),
                    conflict.get("id"),
                    json.dumps(conflict.get("mine"), ensure_ascii=False),
                    json.dumps(conflict.get("theirs"), ensure_ascii=False),
                    time.time(),
                ),
            )
            conn.commit()
            return cur.lastrowid

    def unresolved_conflicts(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, entity_kind, entity_id, mine, theirs, created_at "
                "FROM sync_conflicts WHERE resolved_at IS NULL ORDER BY id"
            ).fetchall()
        return [
            {
                "id": r[0], "entity_kind": r[1], "entity_id": r[2],
                "mine": json.loads(r[3]), "theirs": json.loads(r[4]),
                "created_at": r[5],
            }
            for r in rows
        ]

    def get_conflict(self, conflict_id: int) -> Optional[dict]:
        """Один конфликт по id (для диалога разрешения). None — если нет."""
        with self._connect() as conn:
            r = conn.execute(
                "SELECT id, entity_kind, entity_id, mine, theirs, "
                "       created_at, resolved_at "
                "FROM sync_conflicts WHERE id = ?", (conflict_id,)
            ).fetchone()
        if r is None:
            return None
        return {
            "id": r[0], "entity_kind": r[1], "entity_id": r[2],
            "mine": json.loads(r[3]), "theirs": json.loads(r[4]),
            "created_at": r[5], "resolved_at": r[6],
        }

    def mark_conflict_resolved(self, conflict_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sync_conflicts SET resolved_at = ? WHERE id = ?",
                (time.time(), conflict_id),
            )
            conn.commit()
