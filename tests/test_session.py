"""
Пункт 1 (унификация идентичности): core.session.Session — единый источник
правды об идентичности пользователя. Канонический id = login.

Запуск: python -m unittest tests.test_session  (headless, без Qt)
"""

from __future__ import annotations
import unittest

from core.session import DEFAULT_USER_ROLE, GUEST_ROLE, Session


class SessionTests(unittest.TestCase):
    def test_default_is_guest(self):
        s = Session()
        self.assertTrue(s.is_guest)
        self.assertIsNone(s.user_id)
        self.assertEqual(s.role, GUEST_ROLE)
        self.assertFalse(s.is_admin)

    def test_set_user_canonical_id_is_login(self):
        s = Session()
        s.set_user("ivanov", "teacher")
        self.assertFalse(s.is_guest)
        self.assertEqual(s.user_id, "ivanov")   # id == login
        self.assertEqual(s.login, "ivanov")
        self.assertEqual(s.role, "teacher")

    def test_set_user_none_role_defaults(self):
        s = Session()
        s.set_user("ivanov", None)
        self.assertEqual(s.role, DEFAULT_USER_ROLE)  # 'teacher'

    def test_admin_flag(self):
        s = Session()
        s.set_user("root", "admin")
        self.assertTrue(s.is_admin)

    def test_relogin_and_guest_roundtrip(self):
        s = Session()
        s.set_user("a", "admin")
        s.set_guest()
        self.assertTrue(s.is_guest)
        self.assertEqual(s.role, GUEST_ROLE)
        self.assertFalse(s.is_admin)
        # Перелогин в того же объекта сессии (реестр/окна не пересоздаются).
        s.set_user("b", "teacher")
        self.assertEqual(s.user_id, "b")
        self.assertEqual(s.role, "teacher")


if __name__ == "__main__":
    unittest.main()
