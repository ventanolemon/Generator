"""
Вход на сервер ради токена сессии.

Десктоп аутентифицируется ЛОКАЛЬНО — по своей БД, и так должно остаться:
приложение обязано работать без сети, это его смысл. Но у сервера с
недавних пор своя, заверенная идентичность: роль он читает у себя, а не
из заголовка, который прислал клиент (см. organizations_readiness.md в
GenerationWeb). Значит десктопу нужен токен, и взять его можно только у
сервера.

Отсюда устройство: локальный вход — главный и обязательный, серверный —
дополнительный и НЕОБЯЗАТЕЛЬНЫЙ. Не вышло (нет сети, не задан адрес,
сервер не знает такого пользователя) — приложение работает как работало,
просто без токена. Ошибка здесь не должна мешать войти: человек садится
за ноутбук в аудитории без интернета, и «сервер недоступен» — не повод
не пустить его к своим заданиям.

Чем это кончается на стороне сервера: без токена запись в общий каталог
перестанет проходить, когда там снимут GEN_TRUST_IDENTITY_HEADERS. Это
правильно — учётная запись, которой сервер не знает, и не должна писать
в общий каталог, — но означает, что офлайн-правки такого пользователя
останутся локальными.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Callable, Optional

log = logging.getLogger(__name__)

#: Короткий: вход не должен подвешивать окно, если сервер не отвечает.
TIMEOUT_SECONDS = 10


class AuthError(Exception):
    """Сервер отказал во входе (в отличие от «сервер недоступен»)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


Transport = Callable[[str, dict], dict]


class ServerAuthClient:
    """Один клиент = один адрес сервера."""

    def __init__(self, *, base_url: str = "",
                 transport: Optional[Transport] = None):
        self._base_url = base_url
        self._transport = transport or self._http_transport()

    def _http_transport(self) -> Transport:
        def post(path: str, payload: dict) -> dict:
            url = self._base_url.rstrip("/") + path
            body = json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            try:
                with urllib.request.urlopen(req,
                                            timeout=TIMEOUT_SECONDS) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = json.loads(exc.read().decode()).get("error", "")
                except Exception:
                    pass
                raise AuthError(detail or f"HTTP {exc.code}",
                                status=exc.code) from exc
        return post

    def login(self, login: str, password: str) -> Optional[str]:
        """
        Токен сессии или None, если сервер его не выдал.

        Пустой `base_url` — не ошибка, а «сервер не задан»: у десктопа это
        обычный режим работы.
        """
        if not self._base_url.strip():
            return None
        data = self._transport("/api/auth/login",
                               {"login": login, "password": password})
        token = data.get("token")
        return str(token) if token else None


def login_to_server(base_url: str, login: str, password: str) -> Optional[str]:
    """
    Попытаться получить токен. НИКОГДА не бросает: вход в приложение не
    должен зависеть от доступности сервера.
    """
    try:
        return ServerAuthClient(base_url=base_url).login(login, password)
    except AuthError as exc:
        # Отказ сервера — обычное дело: на сервере может не быть такой
        # учётной записи, а локально она есть.
        log.info("Сервер не выдал токен для %r: %s", login, exc)
    except Exception as exc:
        log.info("Сервер недоступен, работаем без токена: %s", exc)
    return None
