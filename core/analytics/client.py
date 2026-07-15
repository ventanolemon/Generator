"""
AnalyticsClient — HTTP-клиент аналитики успеваемости.

Зеркалит серверный роутер generator_service/routers/analytics.py:
  GET /analytics/overview?range_days=&group= → totals/timeseries/
      correctness_distribution/tasks/students/groups (форма контракта
      зафиксирована при проектировании визуального слоя).

Идентичность — заголовки X-User-Id / X-User-Role (как синк/контур/админка).
Скоуп считает сервер (visible_subject_ids): teacher — свои + системные
предметы, admin — все. can_use() гейтит кнопку в UI (сервер настроен +
роль teacher/admin), но не заменяет серверную проверку.

Транспорт инжектируем: callable(path) -> dict (боевой — urllib; тестовый —
фейк в памяти). Только GET, поэтому транспорт проще, чем у админки.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional

# path (с query) → JSON-ответ
Transport = Callable[[str], dict]


class AnalyticsError(RuntimeError):
    """Ошибка вызова аналитики (сеть/HTTP/протокол) — для показа в UI."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class AnalyticsClient:
    """Один клиент = одна teacher/admin-сессия + транспорт до web_layer."""

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

    def can_use(self) -> bool:
        """Доступна ли аналитика: сервер настроен и роль teacher/admin."""
        return self.has_server() and \
            self._user_role_provider() in ("teacher", "admin")

    # ---------- API ----------

    def overview(self, range_days: int = 30,
                 group: Optional[str] = None) -> dict:
        """Агрегаты за период (по умолчанию 30 дней), опционально по группе."""
        params = {"range_days": int(range_days)}
        if group:
            params["group"] = group
        query = urllib.parse.urlencode(params)
        return self._call(f"/analytics/overview?{query}")

    # ---------- транспорт ----------

    def _call(self, path: str) -> dict:
        try:
            return self._transport(path)
        except AnalyticsError:
            raise
        except Exception as e:
            raise AnalyticsError(f"аналитика: {e}") from e

    def _http_transport(self) -> Transport:
        def call(path: str) -> dict:
            url = self._base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json"}
            uid = self._user_id_provider()
            if uid is not None:
                headers["X-User-Id"] = str(uid)
                headers["X-User-Role"] = self._user_role_provider()
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise AnalyticsError(f"HTTP {e.code}: {detail or e.reason}",
                                     status=e.code) from e
        return call
