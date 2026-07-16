"""
SyncClient — цикл синхронизации десктопа: push → pull (protocol §4).

Порядок жёсткий: сначала push (иначе pull затёр бы base_version живых
правок), затем pull страницами до пустоты, курсор сохраняется ПОСЛЕ
применения каждой страницы (обрыв посреди pull — следующий sync продолжит
с последней применённой страницы, ничего не потеряв и не задвоив:
повторное применение той же страницы идемпотентно — это upsert по id).

Отказоустойчивость outbox: записи удаляются из очереди только после
успешного ответа сервера. Обрыв после отправки, но до подтверждения →
повторная отправка того же пакета при следующем sync; безвредно:
attempts идемпотентны по client_uuid, правки сущностей — по version-check
(повтор уже принятой правки вернёт конфликт с идентичным содержимым
theirs == mine, который клиент распознаёт и молча закрывает).

Транспорт инжектируем: callable(path, payload) -> dict. Боевой — urllib
(без внешних зависимостей), тестовый — фейк-сервер в памяти.
"""

from __future__ import annotations
import json
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..repository import Repository
from .store import SyncStore

Transport = Callable[[str, dict], dict]

PULL_PAGE_LIMIT = 200


class RepositorySyncListener:
    """
    Адаптер Repository → outbox: превращает мутации разделов (создание/правку/
    удаление через UI) в записи очереди синхронизации. Repository остаётся
    слоем данных без прямой зависимости от sync — он лишь дёргает утиный
    интерфейс listener'а. Подключается в main.py ПОСЛЕ bootstrap.sync_database,
    чтобы стартовые сиды (ensure_*) не сыпались в outbox при каждом запуске —
    в очередь попадают только пользовательские изменения.
    """

    def __init__(self, client: "SyncClient"):
        self.client = client

    def partition_changed(self, partition_id: int, data: dict, *,
                          created: bool) -> None:
        # Созданной офлайн сущности id локальный → local_ref, серверный id
        # назначит сервер (client._remap_local_id перепривяжет).
        self.client.queue_partition_change(
            None if created else partition_id, data,
            local_ref=str(partition_id) if created else None)

    def partition_deleted(self, partition_id: int) -> None:
        self.client.queue_partition_change(partition_id, {}, deleted=True)

    def subject_deleted(self, subject_id: int) -> None:
        self.client.queue_subject_change(subject_id, {}, deleted=True)


@dataclass
class SyncReport:
    """Итог одного прогона sync() — для статус-строки UI и тестов."""
    pushed_attempts: int = 0
    accepted_entities: int = 0
    conflicts: int = 0
    pulled_subjects: int = 0
    pulled_partitions: int = 0
    deleted_applied: int = 0
    pages: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class SyncClient:
    """Один клиент = одна локальная БД (+ её SyncStore) + транспорт."""

    def __init__(
        self,
        repo: Repository,
        store: SyncStore,
        *,
        base_url: str = "",
        transport: Optional[Transport] = None,
        user_id: Optional[int] = None,
        user_role: str = "teacher",
    ):
        self.repo = repo
        self.store = store
        self.user_id = user_id
        self.user_role = user_role
        self._base_url = base_url
        self._transport = transport or self._http_transport()

    def set_base_url(self, url: str) -> None:
        """Сменить адрес backend (из диалога настроек) — боевой транспорт
        читает его при каждом запросе, так что переключение мгновенно."""
        self._base_url = url or ""

    def has_server(self) -> bool:
        """Настроен ли адрес backend — иначе синкать некуда (только копим outbox)."""
        return bool(self._base_url.strip())

    # ---------- Публичное API постановки в очередь ----------

    def queue_attempt(self, partition_id: int, payload: dict,
                      correct: Optional[bool] = None,
                      assignment_id: Optional[int] = None) -> None:
        """Записать попытку в outbox (уйдёт при первом успешном sync).
        assignment_id (опц.) привязывает попытку к выданной домашке — сервер
        сохраняет его в attempts.assignment_id."""
        attempt = {
            "partition_id": partition_id,
            "payload": payload,
            "correct": correct,
        }
        if assignment_id is not None:
            attempt["assignment_id"] = int(assignment_id)
        self.store.enqueue_attempt(attempt)

    def queue_partition_change(self, partition_id: Optional[int],
                               data: dict, *, deleted: bool = False,
                               local_ref: Optional[str] = None) -> None:
        self.store.enqueue_entity_change(
            "partition", partition_id, data,
            deleted=deleted, local_ref=local_ref)

    def queue_subject_change(self, subject_id: Optional[int],
                             data: dict, *, deleted: bool = False,
                             local_ref: Optional[str] = None) -> None:
        self.store.enqueue_entity_change(
            "subject", subject_id, data,
            deleted=deleted, local_ref=local_ref)

    # ---------- Цикл синхронизации ----------

    def sync(self) -> SyncReport:
        report = SyncReport()
        try:
            self._push(report)
        except Exception as e:  # сеть/сервер: outbox нетронут, повторим позже
            report.errors.append(f"push: {e}")
            return report
        try:
            self._pull(report)
        except Exception as e:  # курсоры сохранены по применённым страницам
            report.errors.append(f"pull: {e}")
        return report

    # ---------- push ----------

    def _push(self, report: SyncReport) -> None:
        pending = self.store.pending()
        if not pending:
            return
        attempts, entities, outbox_ids = [], [], []
        for item in pending:
            outbox_ids.append(item["outbox_id"])
            if item["kind"] == "attempt":
                attempts.append(item["payload"])
            else:
                change = dict(item["payload"])
                # base_version — версия последнего sync: то, от чего правили.
                if change.get("id") is not None:
                    change["base_version"] = self.store.get_version(
                        change["kind"], int(change["id"]))
                else:
                    change["base_version"] = 0
                entities.append(change)

        resp = self._transport("/sync/push", {
            "device_id": self.store.device_id(),
            "attempts": attempts,
            "word_stats_deltas": [],
            "changed_entities": entities,
        })

        # Ответ получен — очередь можно чистить (сервер принял или
        # аргументированно отверг каждую позицию).
        self.store.remove(outbox_ids)
        report.pushed_attempts = len(attempts)

        for acc in resp.get("accepted", []):
            kind, new_ver = acc["kind"], int(acc["row_version"])
            if acc.get("created") and acc.get("local_ref"):
                # Созданной офлайн сущности сервер назначил id — перепривязать
                # локальную строку (local_ref = str(локальный id)).
                local_id = int(acc["local_ref"])
                self._remap_local_id(kind, local_id, int(acc["id"]))
            if acc.get("deleted"):
                self.store.drop_version(kind, int(acc["id"]))
            else:
                self.store.set_version(kind, int(acc["id"]), new_ver)
            report.accepted_entities += 1

        for conflict in resp.get("conflicts", []):
            # Обе версии целиком — в локальный стэш для будущего диалога
            # (LWW с конфликт-UI, §2; сам диалог — вне этого модуля).
            self.store.record_conflict(conflict)
            report.conflicts += 1

    def _remap_local_id(self, kind: str, local_id: int, server_id: int) -> None:
        if local_id == server_id:
            return
        table = "Subjects" if kind == "subject" else "Partitions"
        with self.repo._connect() as conn:  # noqa: SLF001 — слой данных
            conn.execute(
                f"UPDATE {table} SET id = ? WHERE id = ?",
                (server_id, local_id),
            )
            if kind == "subject":
                conn.execute(
                    "UPDATE Partitions SET subject_id = ? WHERE subject_id = ?",
                    (server_id, local_id),
                )
            conn.commit()
        self.store.remap_entity_id(kind, local_id, server_id)

    # ---------- pull ----------

    def _pull(self, report: SyncReport) -> None:
        cursors = self.store.get_cursors()
        while True:
            resp = self._transport("/sync/pull", {
                "device_id": self.store.device_id(),
                "cursors": cursors,
                "limit": PULL_PAGE_LIMIT,
            })
            self._apply_page(resp, report)
            cursors = resp.get("new_cursors") or cursors
            # Курсор сохраняется после ПРИМЕНЕНИЯ страницы — обрыв между
            # страницами безопасен.
            self.store.set_cursors(cursors)
            report.pages += 1
            if not resp.get("has_more"):
                return

    def _apply_page(self, resp: dict, report: SyncReport) -> None:
        with self.repo._connect() as conn:  # noqa: SLF001
            # Переносим owner_user_id, только если сервер его прислал И колонка
            # есть локально — так десктоп совместим и со «старым» сервером (без
            # владельца), и со «старой» локальной БД (без колонки).
            has_owner_col = any(
                r[1] == "owner_user_id" for r in
                conn.execute("PRAGMA table_info(Subjects)").fetchall())
            for s in resp.get("subjects", []):
                if has_owner_col and "owner_user_id" in s:
                    conn.execute(
                        "INSERT INTO Subjects (id, subject_name, pra_subject, "
                        " owner_user_id) VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        "  subject_name = excluded.subject_name, "
                        "  pra_subject = excluded.pra_subject, "
                        "  owner_user_id = excluded.owner_user_id",
                        (s["id"], s["subject_name"], s["pra_subject"],
                         s.get("owner_user_id")),
                    )
                else:
                    conn.execute(
                        "INSERT INTO Subjects (id, subject_name, pra_subject) "
                        "VALUES (?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        "  subject_name = excluded.subject_name, "
                        "  pra_subject = excluded.pra_subject",
                        (s["id"], s["subject_name"], s["pra_subject"]),
                    )
                report.pulled_subjects += 1
            for p in resp.get("partitions", []):
                params = p.get("generation_parametrs")
                raw = params if isinstance(params, str) else json.dumps(
                    params or {}, ensure_ascii=False)
                conn.execute(
                    "INSERT INTO Partitions (id, subject_id, partition_name, "
                    " constracted, generation_parametrs) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  subject_id = excluded.subject_id, "
                    "  partition_name = excluded.partition_name, "
                    "  constracted = excluded.constracted, "
                    "  generation_parametrs = excluded.generation_parametrs",
                    (p["id"], p["subject_id"], p["partition_name"],
                     p["constracted"], raw),
                )
                report.pulled_partitions += 1
            for d in resp.get("deleted", []):
                # Tombstone сервера = локальное удаление: локально tombstones
                # не нужны, историю удалений хранит сервер.
                table = "Subjects" if d["kind"] == "subject" else "Partitions"
                cur = conn.execute(
                    f"DELETE FROM {table} WHERE id = ?", (d["id"],))
                report.deleted_applied += cur.rowcount
            conn.commit()

        # Версии — вне соединения приложения (SyncStore сам коммитит).
        for s in resp.get("subjects", []):
            self.store.set_version("subject", s["id"], int(s["row_version"]))
        for p in resp.get("partitions", []):
            self.store.set_version("partition", p["id"], int(p["row_version"]))
        for d in resp.get("deleted", []):
            self.store.drop_version(d["kind"], int(d["id"]))

    # ---------- разрешение конфликтов (для диалога UI) ----------

    def resolve_conflict(self, conflict_id: int, keep: str) -> None:
        """
        Разрешить стэшированный конфликт (protocol §2). keep:
          "theirs" — принять серверную версию: она уже применена pull'ом на том
                     же sync (сервер авторитетен), локальная БД = theirs; просто
                     закрываем конфликт, мою правку отбрасываем.
          "mine"   — оставить мою: пишем мою версию локально, ставим
                     base_version = версию theirs и пере-ставим правку в outbox,
                     чтобы следующий push прошёл version-check и перекрыл сервер.
        """
        if keep not in ("mine", "theirs"):
            raise ValueError(f"keep должен быть 'mine'|'theirs', не {keep!r}")
        conflict = self.store.get_conflict(conflict_id)
        if conflict is None:
            return
        if keep == "mine":
            kind = conflict["entity_kind"]
            entity_id = conflict["entity_id"]
            mine = conflict["mine"] or {}
            theirs_version = int((conflict["theirs"] or {}).get("row_version") or 0)
            self.store.set_version(kind, entity_id, theirs_version)
            self._apply_local_entity(kind, entity_id, mine)
            self.store.enqueue_entity_change(kind, entity_id, mine)
        self.store.mark_conflict_resolved(conflict_id)

    def _apply_local_entity(self, kind: str, entity_id: int, data: dict) -> None:
        """Upsert одной сущности в локальную БД (для resolve keep='mine')."""
        with self.repo._connect() as conn:  # noqa: SLF001 — слой данных
            if kind == "subject":
                conn.execute(
                    "INSERT INTO Subjects (id, subject_name, pra_subject) "
                    "VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                    "  subject_name = excluded.subject_name, "
                    "  pra_subject = excluded.pra_subject",
                    (entity_id, data.get("subject_name", ""),
                     data.get("pra_subject", "")),
                )
            else:
                params = data.get("generation_parametrs")
                raw = params if isinstance(params, str) else json.dumps(
                    params or {}, ensure_ascii=False)
                conn.execute(
                    "INSERT INTO Partitions (id, subject_id, partition_name, "
                    " constracted, generation_parametrs) VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "  subject_id = excluded.subject_id, "
                    "  partition_name = excluded.partition_name, "
                    "  constracted = excluded.constracted, "
                    "  generation_parametrs = excluded.generation_parametrs",
                    (entity_id, data.get("subject_id", 0),
                     data.get("partition_name", ""),
                     data.get("constracted", 0), raw),
                )
            conn.commit()

    # ---------- боевой транспорт ----------

    def _http_transport(self) -> Transport:
        def post(path: str, payload: dict) -> dict:
            url = self._base_url.rstrip("/") + path
            body = json.dumps(payload, ensure_ascii=False).encode()
            headers = {"Content-Type": "application/json"}
            if self.user_id is not None:
                headers["X-User-Id"] = str(self.user_id)
                headers["X-User-Role"] = self.user_role
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        return post
