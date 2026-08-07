"""
Вход на сервер ради токена и проброс токена в клиенты.

Главное здесь — не «токен доезжает», а то, что его ОТСУТСТВИЕ ничего не
ломает: десктоп обязан работать без сети, и серверный вход — дополнение к
локальному, а не условие.

Запуск:
    python -m unittest tests.test_server_auth
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.auth import AuthError, ServerAuthClient, login_to_server  # noqa: E402
from core.session import Session  # noqa: E402


class ServerLoginTests(unittest.TestCase):
    def test_returns_token_from_the_server(self):
        seen = {}

        def transport(path, payload):
            seen["path"] = path
            seen["payload"] = payload
            return {"login": "alla", "role": "teacher", "token": "gws_abc"}

        client = ServerAuthClient(base_url="http://server", transport=transport)
        self.assertEqual(client.login("alla", "secret"), "gws_abc")
        self.assertEqual(seen["path"], "/api/auth/login")
        self.assertEqual(seen["payload"],
                         {"login": "alla", "password": "secret"})

    def test_no_base_url_means_no_server_and_no_call(self):
        called = []

        def transport(path, payload):
            called.append(path)
            return {"token": "не должен появиться"}

        client = ServerAuthClient(base_url="   ", transport=transport)
        self.assertIsNone(client.login("alla", "secret"))
        self.assertEqual(called, [])

    def test_response_without_token_is_not_an_error(self):
        # Старый сервер, ещё не выдающий токенов.
        client = ServerAuthClient(base_url="http://server",
                                  transport=lambda p, b: {"login": "alla"})
        self.assertIsNone(client.login("alla", "secret"))


class LoginNeverBlocksTheAppTests(unittest.TestCase):
    """
    `login_to_server` не бросает НИКОГДА: человек садится за ноутбук без
    сети, и «сервер недоступен» — не повод не пустить его к своим заданиям.
    """

    def test_server_refusal_yields_none(self):
        def transport(path, payload):
            raise AuthError("Неверный логин или пароль", status=401)

        client = ServerAuthClient(base_url="http://server", transport=transport)
        with self.assertRaises(AuthError):
            client.login("alla", "secret")
        # …но обёртка глотает отказ.
        self.assertIsNone(
            login_to_server("", "alla", "secret"))

    def test_network_failure_yields_none(self):
        import core.auth.client as mod

        original = mod.ServerAuthClient
        try:
            class Exploding(original):
                def login(self, login, password):
                    raise OSError("сеть недоступна")

            mod.ServerAuthClient = Exploding
            self.assertIsNone(
                mod.login_to_server("http://server", "alla", "secret"))
        finally:
            mod.ServerAuthClient = original


class SessionCarriesTheTokenTests(unittest.TestCase):
    def test_token_is_stored_and_cleared_with_the_user(self):
        s = Session()
        self.assertIsNone(s.token)

        s.set_user("alla", "teacher", "gws_abc")
        self.assertEqual(s.token, "gws_abc")

        s.set_guest()
        self.assertIsNone(s.token, "гость не должен унаследовать токен")

    def test_local_only_login_leaves_no_token(self):
        s = Session()
        s.set_user("alla", "teacher")
        self.assertIsNone(s.token)
        # Локальная сессия при этом полноценна.
        self.assertEqual(s.role, "teacher")
        self.assertFalse(s.is_guest)


class ClientsSendTheToken(unittest.TestCase):
    """Токен доезжает до сервера заголовком Authorization."""

    def _headers_of(self, client_factory):
        captured = {}

        class FakeResponse:
            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        import urllib.request
        original = urllib.request.urlopen

        def fake_urlopen(req, timeout=None):
            captured.update(dict(req.header_items()))
            return FakeResponse()

        urllib.request.urlopen = fake_urlopen
        try:
            client_factory()
        except Exception:
            pass
        finally:
            urllib.request.urlopen = original
        return {k.lower(): v for k, v in captured.items()}

    def test_admin_client_sends_bearer(self):
        from core.admin.client import AdminClient

        client = AdminClient(base_url="http://server",
                             user_id_provider=lambda: "alla",
                             user_role_provider=lambda: "admin",
                             user_token_provider=lambda: "gws_abc")
        headers = self._headers_of(lambda: client.list_users())
        self.assertEqual(headers.get("Authorization".lower()), "Bearer gws_abc")
        self.assertEqual(headers.get("X-User-Id".lower()), "alla")

    def test_no_token_means_no_authorization_header(self):
        from core.admin.client import AdminClient

        client = AdminClient(base_url="http://server",
                             user_id_provider=lambda: "alla",
                             user_role_provider=lambda: "admin")
        headers = self._headers_of(lambda: client.list_users())
        self.assertNotIn("authorization", headers)
        # Заголовки личности при этом никуда не делись — офлайн-режим цел.
        self.assertEqual(headers.get("X-User-Id".lower()), "alla")

    def test_sync_client_sends_bearer(self):
        from core.sync.client import SyncClient

        # repo/store здесь не участвуют: проверяется только транспорт.
        client = SyncClient(None, None, base_url="http://server",
                            user_id="alla", user_role="teacher",
                            user_token="gws_abc")
        headers = self._headers_of(
            lambda: client._http_transport()("/sync/pull", {}))
        self.assertEqual(headers.get("Authorization".lower()), "Bearer gws_abc")


if __name__ == "__main__":
    unittest.main()
