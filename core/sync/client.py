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
        self._transport = transport or self._http_transport(base_url)

    # ---------- Публичное API постановки в очередь ----------

    def queue_attempt(self, partition_id: int, payload: dict,
                      correct: Optional[bool] = None) -> None:
        """Записать попытку в outbox (уйдёт при первом успешном sync)."""
        self.store.enqueue_attempt({
            "partition_id": partition_id,
            "payload": payload,
            "correct": correct,
        })

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
            for s in resp.get("subjects", []):
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

    # ---------- боевой транспорт ----------

    def _http_transport(self, base_url: str) -> Transport:
        def post(path: str, payload: dict) -> dict:
            url = base_url.rstrip("/") + path
            body = json.dumps(payload, ensure_ascii=False).encode()
            headers = {"Content-Type": "application/json"}
            if self.user_id is not None:
                headers["X-User-Id"] = str(self.user_id)
                headers["X-User-Role"] = self.user_role
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        return post
