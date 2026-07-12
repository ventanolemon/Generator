"""
ContourClient — HTTP-клиент LLM-контура (C1 плана docs/ui_rework_plan.md).

Зеркалит серверный API contour_service/routers/jobs.py:

  create_job(description, subject_id, constraints) → {"job_id", "status"}
  get_job(job_id)      → статус + previews/flags/critic/rounds (экран S6)
  list_jobs()          → джобы пользователя («на утверждении» + история)
  approve(job_id, ...) → партиция constracted=4 (создаёт ТОЛЬКО человек)
  reject(job_id, reason)

Терминология статусов (contour_integration.md): queued → running →
awaiting_human → approved | rejected | failed. Клиент ничего не решает —
петля S1–S5 живёт на сервере, человек утверждает через approve.

Транспорт инжектируем: callable(path, payload|None) -> dict, где payload
None означает GET (боевой — urllib через web_layer, тестовый — фейк в
памяти). Идентичность — заголовки X-User-Id / X-User-Role, как у синка.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

# path, payload (None → GET, dict → POST JSON) → JSON-ответ
Transport = Callable[[str, Optional[dict]], dict]

# Статусы джобы (contour_integration.md §3).
QUEUED = "queued"
RUNNING = "running"
AWAITING_HUMAN = "awaiting_human"
APPROVED = "approved"
REJECTED = "rejected"
FAILED = "failed"

# Статусы, в которых джоба ещё меняется — поллинг продолжается.
ACTIVE_STATUSES = (QUEUED, RUNNING)
# Терминальные + ожидание человека: поллинг останавливается.
SETTLED_STATUSES = (AWAITING_HUMAN, APPROVED, REJECTED, FAILED)


class ContourError(RuntimeError):
    """Ошибка вызова контура (сеть/HTTP/протокол) — для показа в UI."""


class ContourClient:
    """Один клиент = один пользователь-сессия + транспорт до web_layer."""

    def __init__(
        self,
        *,
        base_url: str = "",
        transport: Optional[Transport] = None,
        user_id_provider: Optional[Callable[[], Optional[str]]] = None,
        user_role_provider: Optional[Callable[[], str]] = None,
    ):
        self._base_url = base_url
        self._user_id_provider = user_id_provider or (lambda: None)
        self._user_role_provider = user_role_provider or (lambda: "teacher")
        self._transport = transport or self._http_transport()

    # ---------- конфигурация ----------

    def set_base_url(self, url: str) -> None:
        """Сменить адрес backend (из диалога настроек) без перезапуска."""
        self._base_url = url or ""

    def has_server(self) -> bool:
        return bool(self._base_url.strip())

    def can_use(self) -> bool:
        """Доступен ли контур этой сессии: сервер настроен и роль позволяет
        (запускать петлю могут teacher и admin — правило API §4)."""
        return self.has_server() and \
            self._user_role_provider() in ("teacher", "admin")

    # ---------- API джоб ----------

    def create_job(self, description: str, subject_id: int,
                   constraints: Optional[dict] = None) -> dict:
        """Поставить джобу в очередь → {"job_id", "status": "queued"}."""
        return self._call("/contour/jobs", {
            "description": description,
            "subject_id": int(subject_id),
            "constraints": constraints or {},
        })

    def get_job(self, job_id: str) -> dict:
        """Статус + данные экрана утверждения (previews/flags/critic)."""
        return self._call(f"/contour/jobs/{job_id}", None)

    def list_jobs(self) -> list[dict]:
        """Джобы пользователя (admin — все), список сводок."""
        resp = self._call("/contour/jobs", None)
        return list(resp.get("jobs") or [])

    def approve(self, job_id: str, partition_name: str = "",
                note: str = "") -> dict:
        """S6: принять → сервер создаёт партицию constracted=4."""
        return self._call(f"/contour/jobs/{job_id}/approve", {
            "partition_name": partition_name, "note": note,
        })

    def reject(self, job_id: str, reason: str) -> dict:
        """S6: отклонить с причиной (уходит в лог эскалаций)."""
        return self._call(f"/contour/jobs/{job_id}/reject",
                          {"reason": reason})

    # ---------- транспорт ----------

    def _call(self, path: str, payload: Optional[dict]) -> dict:
        try:
            return self._transport(path, payload)
        except ContourError:
            raise
        except Exception as e:
            raise ContourError(f"контур: {e}") from e

    def _http_transport(self) -> Transport:
        def call(path: str, payload: Optional[dict]) -> dict:
            url = self._base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json"}
            uid = self._user_id_provider()
            if uid is not None:
                headers["X-User-Id"] = str(uid)
                headers["X-User-Role"] = self._user_role_provider()
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                # Тело ошибки FastAPI ({"detail": ...}) — в сообщение.
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise ContourError(
                    f"HTTP {e.code}: {detail or e.reason}") from e
        return call
