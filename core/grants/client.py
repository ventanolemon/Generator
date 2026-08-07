"""
GrantsClient — HTTP-клиент выдач предметов (см. docs/subject_grants.md).

Зеркалит серверные роутеры generator_service:
  GET /subjects/grants/mine            — свои выдачи (витрина преподавателя)
  GET /admin/subject-grants            — данные матрицы (admin)
  PUT /admin/subject-grants/{login}    — выдачи преподавателя целиком (admin)
  PUT /admin/subject-grants/default-access  — режим умолчания (admin)

Права server-authoritative: клиент — удобная оболочка, сервер перепроверяет
роль на каждом вызове. Идентичность — заголовки X-User-Id / X-User-Role, как
у синка, контура и AdminClient.

Транспорт инжектируем: callable(path, payload, method) -> dict (боевой —
urllib; тестовый — фейк в памяти). payload=None у GET.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Optional

from ..repository import GrantsSnapshot, Repository

# path, payload (None у GET), method → JSON-ответ
Transport = Callable[[str, Optional[dict], str], dict]

DEFAULT_ACCESS_VALUES = ("all", "none")


class GrantsError(RuntimeError):
    """Ошибка вызова API выдач (сеть/HTTP/протокол) — для показа в UI.

    Несёт HTTP-код, когда он известен (403 — не хватает прав), чтобы окно
    показало сообщение сервера, а не «сбой»."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class GrantsClient:
    """Один клиент = одна сессия + транспорт до web_layer."""

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

    def can_manage(self) -> bool:
        """Доступно ли управление выдачами: сервер настроен и роль admin.
        Гейтит вкладку в UI, не заменяет серверную проверку."""
        return self.has_server() and self._user_role_provider() == "admin"

    # ---------- витрина преподавателя ----------

    def my_grants(self) -> GrantsSnapshot:
        """Свои выдачи с сервера. Бросает GrantsError при недоступности."""
        resp = self._call("/subjects/grants/mine", None, "GET")
        return self._snapshot_from(resp)

    def refresh_into(self, repo: Repository,
                     user_login: str | None) -> Optional[GrantsSnapshot]:
        """
        Обновить локальный снимок выдач пользователя с сервера.

        Возвращает снимок при успехе и None, если обновляться нечем или
        незачем: нет адреса сервера, нет логина (гость). ОШИБКА СЕТИ НЕ
        ГЛОТАЕТСЯ — она выходит GrantsError, потому что решение «оставить
        прежний снимок и работать офлайн» принимает вызывающий, а не клиент;
        молчаливое проглатывание прятало бы отзыв прав за неудачным опросом.
        """
        if not user_login or not self.has_server():
            return None
        snapshot = self.my_grants()
        repo.save_grants(user_login, snapshot.subject_ids,
                         scope_version=snapshot.scope_version,
                         default_access=snapshot.default_access)
        return snapshot

    # ---------- матрица администратора ----------

    def matrix(self) -> dict:
        """
        Данные вкладки «Предметы преподавателям» одним вызовом.

        Возвращает нормализованный словарь:
          {"default_access": "all"|"none",
           "teachers": [{"login", "fio"}, ...],
           "subjects": [{"id", "subject_name", "is_builtin"}, ...],
           "grants": {login: set(subject_id)}}
        """
        resp = self._call("/admin/subject-grants", None, "GET")
        raw_grants = resp.get("grants") or {}
        return {
            "default_access": self._normalized_access(
                resp.get("default_access")),
            "teachers": list(resp.get("teachers") or []),
            "subjects": list(resp.get("subjects") or []),
            "grants": {login: {int(s) for s in (ids or [])}
                       for login, ids in raw_grants.items()},
        }

    def set_teacher_grants(self, login: str, subject_ids) -> dict:
        """
        Заменить выдачи преподавателя целиком (не дельта).

        Матрица правится строкой, и полная замена идемпотентна: повторное
        применение того же набора ничего не меняет, а отзыв не требует
        отдельной операции.
        """
        ids = sorted({int(s) for s in subject_ids})
        return self._call(f"/admin/subject-grants/{login}",
                          {"subject_ids": ids}, "PUT")

    def set_default_access(self, default_access: str) -> dict:
        """Переключить режим умолчания ('all' — видно всё без выдач, 'none' —
        строгий). Сервер инкрементирует scope_version всем преподавателям."""
        if default_access not in DEFAULT_ACCESS_VALUES:
            raise ValueError(
                f"default_access: 'all'|'none', не {default_access!r}")
        return self._call("/admin/subject-grants/default-access",
                          {"default_access": default_access}, "PUT")

    # ---------- разбор ответов ----------

    @staticmethod
    def _normalized_access(value) -> str:
        """Неизвестное/отсутствующее значение → 'all'.

        Умолчание намеренно разрешающее: если сервер старый или ответ кривой,
        преподаватель должен остаться с полной витриной, а не с пустой."""
        return value if value in DEFAULT_ACCESS_VALUES else "all"

    def _snapshot_from(self, resp: dict) -> GrantsSnapshot:
        ids = {int(s) for s in (resp.get("subject_ids") or [])}
        return GrantsSnapshot(
            frozenset(ids),
            self._normalized_access(resp.get("default_access")),
            int(resp.get("scope_version") or 0),
        )

    # ---------- транспорт ----------

    def _call(self, path: str, payload: Optional[dict], method: str) -> dict:
        try:
            return self._transport(path, payload, method)
        except GrantsError:
            raise
        except Exception as e:
            raise GrantsError(f"выдачи предметов: {e}") from e

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
                raise GrantsError(f"HTTP {e.code}: {detail or e.reason}",
                                  status=e.code) from e
        return call
