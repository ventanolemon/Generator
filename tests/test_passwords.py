"""
D1 плана docs/ui_rework_plan.md — пароли: PBKDF2-хэширование, прозрачная
миграция унаследованных plain-text при первом входе, смена пароля,
регистрация (create_user).

Запуск: python -m unittest tests.test_passwords  (headless, без Qt)
"""

from __future__ import annotations
import os
import sqlite3
import unittest

from core.repository import Repository
from tests.tmpdb import temp_path  # noqa: E402


def _db_with_user(password_value: str) -> str:
    path = temp_path(suffix=".db")
    conn = sqlite3.connect(path)
    conn.execute(
        'CREATE TABLE users (login TEXT PRIMARY KEY, password TEXT, '
        'FIO TEXT, "group" TEXT, role TEXT NOT NULL DEFAULT \'teacher\')')
    conn.execute("INSERT INTO users VALUES ('t', ?, 'ФИО', 'Г1', 'admin')",
                 (password_value,))
    conn.commit()
    conn.close()
    return path


def _stored_password(path: str, login: str = "t") -> str:
    conn = sqlite3.connect(path)
    row = conn.execute("SELECT password FROM users WHERE login = ?",
                       (login,)).fetchone()
    conn.close()
    return row[0]


class HashFormatTests(unittest.TestCase):
    def test_hash_roundtrip(self):
        stored = Repository._hash_password("секрет123")
        self.assertTrue(stored.startswith("pbkdf2$"))
        self.assertTrue(Repository._verify_password("секрет123", stored))
        self.assertFalse(Repository._verify_password("не тот", stored))

    def test_hashes_are_salted(self):
        a = Repository._hash_password("одинаковый")
        b = Repository._hash_password("одинаковый")
        self.assertNotEqual(a, b, "разная соль → разные хэши")

    def test_malformed_stored_rejected(self):
        self.assertFalse(Repository._verify_password("x", "pbkdf2$мусор"))


class LegacyMigrationTests(unittest.TestCase):
    def test_plain_login_works_and_migrates(self):
        path = _db_with_user("старыйплейн")
        repo = Repository(path)
        row = repo.find_user("t", "старыйплейн")
        self.assertIsNotNone(row)
        self.assertEqual(row[3], "admin")
        # После успешного входа plain переписан хэшем...
        stored = _stored_password(path)
        self.assertTrue(stored.startswith("pbkdf2$"))
        # ...и вход продолжает работать, а старая строка больше не пароль.
        self.assertIsNotNone(repo.find_user("t", "старыйплейн"))
        os.remove(path)

    def test_wrong_password_does_not_migrate(self):
        path = _db_with_user("старыйплейн")
        repo = Repository(path)
        self.assertIsNone(repo.find_user("t", "неверный"))
        self.assertEqual(_stored_password(path), "старыйплейн",
                         "неудачный вход ничего не переписывает")
        os.remove(path)

    def test_unknown_login_none(self):
        path = _db_with_user("x")
        self.assertIsNone(Repository(path).find_user("нет", "x"))
        os.remove(path)


class SetPasswordTests(unittest.TestCase):
    def test_change_with_correct_old(self):
        path = _db_with_user("старый")
        repo = Repository(path)
        self.assertTrue(repo.set_password("t", "старый", "новый"))
        self.assertIsNone(repo.find_user("t", "старый"))
        self.assertIsNotNone(repo.find_user("t", "новый"))
        self.assertTrue(_stored_password(path).startswith("pbkdf2$"))
        os.remove(path)

    def test_change_rejected_with_wrong_old(self):
        path = _db_with_user("старый")
        repo = Repository(path)
        self.assertFalse(repo.set_password("t", "не тот", "новый"))
        self.assertIsNotNone(repo.find_user("t", "старый"))
        os.remove(path)

    def test_empty_new_rejected(self):
        path = _db_with_user("старый")
        self.assertFalse(Repository(path).set_password("t", "старый", ""))
        os.remove(path)

    def test_change_after_hash_migration(self):
        # Цепочка: plain → вход (миграция) → смена → вход новым.
        path = _db_with_user("плейн")
        repo = Repository(path)
        repo.find_user("t", "плейн")
        self.assertTrue(repo.set_password("t", "плейн", "свежий"))
        self.assertIsNotNone(repo.find_user("t", "свежий"))
        os.remove(path)


class CreateUserTests(unittest.TestCase):
    def test_create_and_login(self):
        path = _db_with_user("x")
        repo = Repository(path)
        self.assertTrue(repo.create_user("новичок", "пароль",
                                         fio="Иванов И.", group="Б-21",
                                         role="teacher"))
        row = repo.find_user("новичок", "пароль")
        self.assertIsNotNone(row)
        self.assertEqual(row[1], "Иванов И.")
        self.assertEqual(row[3], "teacher")
        self.assertTrue(_stored_password(path, "новичок")
                        .startswith("pbkdf2$"), "пароль сразу хэширован")
        os.remove(path)

    def test_duplicate_login_rejected(self):
        path = _db_with_user("x")
        repo = Repository(path)
        self.assertFalse(repo.create_user("t", "другой"))
        os.remove(path)

    def test_empty_credentials_rejected(self):
        path = _db_with_user("x")
        repo = Repository(path)
        self.assertFalse(repo.create_user("  ", "p"))
        self.assertFalse(repo.create_user("ok", ""))
        os.remove(path)


if __name__ == "__main__":
    unittest.main()
