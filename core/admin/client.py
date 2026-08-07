"""
AdminClient — HTTP-клиент администрирования (пользователи/роли + группы).

Зеркалит серверные роутеры generator_service:
  routers/admin.py  — /admin/users, /admin/users/{login}/role
  routers/groups.py — /admin/groups (+ members/teachers), /groups/mine

Идентичность — заголовки X-User-Id / X-User-Role (как синк/контур). Права
server-authoritative: клиент лишь удобная оболочка, сервер перепроверяет
роль на каждом вызове и отдаёт 401/403/400. can_use() гейтит кнопку в UI
(сервер настроен + роль admin), но не заменяет серверную проверку.

Транспорт инжектируем: callable(path, payload, method) -> dict (боевой —
urllib; тестовый — фейк в памяти). payload=None у GET/DELETE.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

# path, payload (None у GET/DELETE), method → JSON-ответ
Transport = Callable[[str, Optional[dict], str], dict]


class AdminError(RuntimeError):
    """Ошибка вызова админ-API (сеть/HTTP/протокол) — для показа в UI.

    По возможности несёт HTTP-код (403 — не хватает прав, 400 — нарушено
    доменное правило вроде «нельзя понизить последнего администратора»),
    чтобы окно показало осмысленное сообщение сервера, а не «сбой»."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class AdminClient:
    """Один клиент = одна admin-сессия + транспорт до web_layer."""

    def __init__(
        self,
        *,
        base_url: str = "",
        transport: Optional[Transport] = None,
        user_id_provider: Optional[Callable[[], Optional[str]]] = None,
        user_role_provider: Optional[Callable[[], str]] = None,
        user_token_provider: Optional[Callable[[], Optional[str]]] = None,
    ):
        self._base_url = base_url
        self._user_id_provider = user_id_provider or (lambda: None)
        self._user_role_provider = user_role_provider or (lambda: "student")
        self._user_token_provider = user_token_provider or (lambda: None)
        self._transport = transport or self._http_transport()

    # ---------- конфигурация ----------

    def set_base_url(self, url: str) -> None:
        self._base_url = url or ""

    def has_server(self) -> bool:
        return bool(self._base_url.strip())

    def can_use(self) -> bool:
        """Доступно ли администрирование: сервер настроен и роль admin.
        Не заменяет серверную проверку — только гейтит кнопку/окно."""
        return self.has_server() and self._user_role_provider() == "admin"

    # ---------- пользователи ----------

    def list_users(self) -> list[dict]:
        resp = self._call("/admin/users", None, "GET")
        return list(resp.get("users") or [])

    def change_role(self, login: str, role: str) -> dict:
        return self._call(f"/admin/users/{login}/role", {"role": role}, "POST")

    # ---------- группы ----------

    def list_groups(self) -> list[dict]:
        resp = self._call("/admin/groups", None, "GET")
        return list(resp.get("groups") or [])

    def create_group(self, name: str) -> dict:
        return self._call("/admin/groups", {"name": name}, "POST")

    def add_member(self, group_id: int, login: str) -> dict:
        return self._call(f"/admin/groups/{int(group_id)}/members",
                          {"login": login}, "POST")

    def remove_member(self, group_id: int, login: str) -> dict:
        return self._call(f"/admin/groups/{int(group_id)}/members/{login}",
                          None, "DELETE")

    def assign_teacher(self, group_id: int, login: str) -> dict:
        return self._call(f"/admin/groups/{int(group_id)}/teachers",
                          {"login": login}, "POST")

    def unassign_teacher(self, group_id: int, login: str) -> dict:
        return self._call(f"/admin/groups/{int(group_id)}/teachers/{login}",
                          None, "DELETE")

    def my_groups(self) -> list[dict]:
        """Свои группы (для преподавателя): read-view /groups/mine."""
        resp = self._call("/groups/mine", None, "GET")
        return list(resp.get("groups") or [])

    # ---------- транспорт ----------

    def _call(self, path: str, payload: Optional[dict], method: str) -> dict:
        try:
            return self._transport(path, payload, method)
        except AdminError:
            raise
        except Exception as e:
            raise AdminError(f"администрирование: {e}") from e

    def _http_transport(self) -> Transport:
        def call(path: str, payload: Optional[dict], method: str) -> dict:
            url = self._base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json"}
            uid = self._user_id_provider()
            if uid is not None:
                headers["X-User-Id"] = str(uid)
                headers["X-User-Role"] = self._user_role_provider()
            # Заверенная личность. Сервер при её наличии не смотрит
            # на X-User-Role вовсе — роль он читает у себя в БД.
            token = self._user_token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
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
                raise AdminError(f"HTTP {e.code}: {detail or e.reason}",
                                 status=e.code) from e
        return call
