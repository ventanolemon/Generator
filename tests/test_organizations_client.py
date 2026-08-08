"""
Принадлежность к организации в десктопе.

Главное здесь — что НЕзнание организации ничего не ломает: десктоп входит
локально, и офлайн-пользователь про организацию узнать не может. Это
обычная работа, а не сбой.

Запуск:
    python -m unittest tests.test_organizations_client
"""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.organizations import (Membership, OrganizationsClient,  # noqa: E402
                                OrganizationsError)

_OWNER = {"login": "boris", "role": "admin", "is_owner": True,
          "is_superuser": False,
          "organization": {"id": 2, "name": "Кафедра химии"}}


class DescribeTests(unittest.TestCase):
    """Строка пишется словами: «admin, org=2» человеку не говорит ничего."""

    def test_owner(self):
        self.assertEqual(Membership.from_dict(_OWNER).describe(),
                         "Кафедра химии — вы её владелец")

    def test_plain_member(self):
        data = {**_OWNER, "is_owner": False}
        self.assertEqual(Membership.from_dict(data).describe(),
                         "Кафедра химии")

    def test_superuser_is_a_separate_axis(self):
        data = {**_OWNER, "is_superuser": True}
        text = Membership.from_dict(data).describe()
        self.assertIn("Кафедра химии", text)
        self.assertIn("администратор развёртывания", text)

    def test_outsider_is_told_what_to_do(self):
        data = {"login": "x", "role": "teacher", "organization": None}
        m = Membership.from_dict(data)
        self.assertFalse(m.belongs)
        self.assertIn("попросите администратора", m.describe())


class FetchQuietlyTests(unittest.TestCase):
    def test_returns_membership_when_the_server_answers(self):
        client = OrganizationsClient(
            base_url="http://server", transport=lambda p: _OWNER,
            user_id_provider=lambda: "boris")
        self.assertEqual(client.fetch_quietly().organization_name,
                         "Кафедра химии")

    def test_no_server_means_no_question_asked(self):
        called = []
        client = OrganizationsClient(
            base_url="", transport=lambda p: called.append(p) or _OWNER,
            user_id_provider=lambda: "boris")
        self.assertIsNone(client.fetch_quietly())
        self.assertEqual(called, [], "спросили, хотя адреса сервера нет")

    def test_guest_asks_nothing(self):
        called = []
        client = OrganizationsClient(
            base_url="http://server",
            transport=lambda p: called.append(p) or _OWNER,
            user_id_provider=lambda: None)
        self.assertIsNone(client.fetch_quietly())
        self.assertEqual(called, [])

    def test_server_failure_is_not_fatal(self):
        # Старый сервер этой ручки не знает; офлайн до неё не дотянуться.
        def boom(path):
            raise OrganizationsError("HTTP 404", status=404)

        client = OrganizationsClient(base_url="http://server", transport=boom,
                                     user_id_provider=lambda: "boris")
        self.assertIsNone(client.fetch_quietly())

    def test_mine_does_raise(self):
        # Тихая обёртка — не повод прятать ошибку от того, кто спросил прямо.
        def boom(path):
            raise OrganizationsError("HTTP 500", status=500)

        client = OrganizationsClient(base_url="http://server", transport=boom,
                                     user_id_provider=lambda: "boris")
        with self.assertRaises(OrganizationsError):
            client.mine()


class HeadersTests(unittest.TestCase):
    def test_token_is_sent(self):
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
        urllib.request.urlopen = lambda req, timeout=None: (
            captured.update(dict(req.header_items())) or FakeResponse())
        try:
            OrganizationsClient(
                base_url="http://server", user_id_provider=lambda: "boris",
                user_role_provider=lambda: "admin",
                user_token_provider=lambda: "gws_abc").mine()
        finally:
            urllib.request.urlopen = original
        lower = {k.lower(): v for k, v in captured.items()}
        self.assertEqual(lower.get("authorization"), "Bearer gws_abc")


if __name__ == "__main__":
    unittest.main()
