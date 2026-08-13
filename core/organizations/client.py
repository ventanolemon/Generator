"""
OrganizationsClient — принадлежность вошедшего к организации (§8 плана).

Десктопу нужна не вся администрация организаций (она живёт в вебе), а один
ответ на один вопрос: **где я состою и что это значит**. С введением
организаций `admin` стал означать «админ СВОЕЙ организации», а видимость
контента ограничена её границей. Не показать этого в десктопе — значит
оставить человека гадать, почему предметов стало меньше или почему
кнопка администрирования отказывает.

Зеркалит один серверный роутер:
  GET /organizations/mine — логин, роль, организация, флаги

Ошибка НЕ фатальна: старый сервер этой ручки не знает, а офлайн-десктоп до
неё вовсе не дотянется. И то и другое — обычная работа, поэтому
`fetch_quietly` возвращает None вместо исключения.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

log = logging.getLogger(__name__)

Transport = Callable[[str], dict]


class OrganizationsError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Membership:
    """Принадлежность и полномочия — в форме, готовой для показа."""

    login: str
    role: str
    organization_id: Optional[int]
    organization_name: Optional[str]
    is_owner: bool
    is_superuser: bool

    @property
    def belongs(self) -> bool:
        return self.organization_id is not None

    def describe(self) -> str:
        """
        Одна строка для окна настроек.

        Пишется словами, а не полями: «admin, org=2» человеку ничего не
        говорит, а «Кафедра химии — вы её владелец» говорит.
        """
        if not self.belongs:
            return ("вне организаций — общий каталог недоступен, "
                    "попросите администратора принять вас")
        parts = [self.organization_name or f"#{self.organization_id}"]
        if self.is_owner:
            parts.append("вы её владелец")
        if self.is_superuser:
            parts.append("администратор развёртывания")
        return " — ".join(parts) if len(parts) > 1 else parts[0]

    @classmethod
    def from_dict(cls, data: dict) -> "Membership":
        org = data.get("organization") or {}
        return cls(
            login=str(data.get("login") or ""),
            role=str(data.get("role") or "student"),
            organization_id=org.get("id"),
            organization_name=org.get("name"),
            is_owner=bool(data.get("is_owner")),
            is_superuser=bool(data.get("is_superuser")),
        )


class OrganizationsClient:
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

    def set_base_url(self, url: str) -> None:
        self._base_url = url

    @property
    def can_use(self) -> bool:
        """Есть ли куда ходить: адрес задан и мы не гость."""
        return bool(self._base_url.strip()
                    and self._user_id_provider() is not None)

    def mine(self) -> Membership:
        """Принадлежность. Бросает OrganizationsError."""
        return Membership.from_dict(self._call("/api/organizations/mine"))

    def fetch_quietly(self) -> Optional[Membership]:
        """
        То же, но без исключений: None, если спросить не у кого или сервер
        не ответил. Принадлежность — справочная строка в настройках, и
        ронять из-за неё окно нельзя.
        """
        if not self.can_use:
            return None
        try:
            return self.mine()
        except Exception as exc:                       # noqa: BLE001
            log.info("организация не получена: %s", exc)
            return None

    # ---------- транспорт ----------

    def _call(self, path: str) -> dict:
        try:
            return self._transport(path)
        except OrganizationsError:
            raise
        except Exception as e:
            raise OrganizationsError(f"организация: {e}") from e

    def _http_transport(self) -> Transport:
        def call(path: str) -> dict:
            url = self._base_url.rstrip("/") + path
            headers = {"Content-Type": "application/json"}
            uid = self._user_id_provider()
            if uid is not None:
                headers["X-User-Id"] = str(uid)
                headers["X-User-Role"] = self._user_role_provider()
            token = self._user_token_provider()
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = urllib.request.Request(url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise OrganizationsError(detail or f"HTTP {e.code}",
                                         status=e.code) from e
        return call
