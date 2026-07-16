"""
AssignmentsClient — HTTP-клиент домашек.

Зеркалит серверный роутер generator_service/routers/assignments.py (+ читает
/groups/mine для формы выдачи). Идентичность — заголовки X-User-Id/Role.
Права проверяет сервер (teacher — свои задачи своим группам; снять —
автор/admin); can_use() гейтит окно (нужен сервер и не гость).

Транспорт инжектируем: callable(path, payload, method) -> dict.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

Transport = Callable[[str, Optional[dict], str], dict]


class AssignmentsError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class AssignmentsClient:
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
        self._user_role_provider = user_role_provider or (lambda: "student")
        self._transport = transport or self._http_transport()

    # ---------- конфигурация ----------

    def set_base_url(self, url: str) -> None:
        self._base_url = url or ""

    def has_server(self) -> bool:
        return bool(self._base_url.strip())

    def is_guest(self) -> bool:
        return self._user_id_provider() is None

    def can_use(self) -> bool:
        """Окно домашек доступно вошедшему пользователю с сервером (teacher/
        admin выдают, student смотрит — ветвление в самом окне)."""
        return self.has_server() and not self.is_guest()

    def can_assign(self) -> bool:
        return self.can_use() and \
            self._user_role_provider() in ("teacher", "admin")

    # ---------- API ----------

    def create(self, partition_id: int, group_id: int,
               due_at: Optional[float] = None) -> dict:
        payload = {"partition_id": int(partition_id),
                   "group_id": int(group_id)}
        if due_at is not None:
            payload["due_at"] = float(due_at)
        return self._call("/assignments", payload, "POST")

    def teaching(self) -> list[dict]:
        resp = self._call("/assignments/teaching", None, "GET")
        return list(resp.get("assignments") or [])

    def mine(self) -> list[dict]:
        resp = self._call("/assignments/mine", None, "GET")
        return list(resp.get("assignments") or [])

    def delete(self, assignment_id: int) -> dict:
        return self._call(f"/assignments/{int(assignment_id)}", None, "DELETE")

    def progress(self, assignment_id: int) -> dict:
        """Пофамильный прогресс по выдаче (автор/admin): кто сдал."""
        return self._call(f"/assignments/{int(assignment_id)}/progress",
                          None, "GET")

    def my_groups(self) -> list[dict]:
        """Группы преподавателя — для выбора в форме выдачи (/groups/mine)."""
        resp = self._call("/groups/mine", None, "GET")
        return list(resp.get("groups") or [])

    # ---------- транспорт ----------

    def _call(self, path: str, payload: Optional[dict], method: str) -> dict:
        try:
            return self._transport(path, payload, method)
        except AssignmentsError:
            raise
        except Exception as e:
            raise AssignmentsError(f"домашки: {e}") from e

    def _http_transport(self) -> Transport:
        def call(path: str, payload: Optional[dict], method: str) -> dict:
            url = self._base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json"}
            uid = self._user_id_provider()
            if uid is not None:
                headers["X-User-Id"] = str(uid)
                headers["X-User-Role"] = self._user_role_provider()
            body = None
            if payload is not None:
                body = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(url, data=body, headers=headers,
                                         method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise AssignmentsError(f"HTTP {e.code}: {detail or e.reason}",
                                       status=e.code) from e
        return call
