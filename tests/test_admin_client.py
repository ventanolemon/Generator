"""
AdminClient (десктоп, headless): формирование вызовов users/groups,
маршрутизация методов (GET/POST/DELETE), гейтинг can_use по роли и адресу,
оборачивание ошибок сервера (401/403/400) в AdminError со status.

Запуск: python -m unittest tests.test_admin_client
"""

from __future__ import annotations
import unittest

from core.admin import AdminClient, AdminError


class FakeAdminServer:
    """Фейк /admin в памяти: та же семантика, что routers/admin.py +
    routers/groups.py (роль вызывающего берём из заголовков, зашитых в
    транспорт клиента)."""

    def __init__(self, *, role="admin"):
        self.role = role
        self.users = {
            "root": {"login": "root", "fio": "Админ", "group": "",
                     "role": "admin", "created_at": 0.0},
            "alla": {"login": "alla", "fio": "Алла", "group": "",
                     "role": "teacher", "created_at": 0.0},
        }
        self.groups: dict[int, dict] = {}
        self.next_gid = 1
        self.calls: list[tuple[str, str]] = []

    # transport(path, payload, method) -> dict
    def transport(self, path: str, payload, method: str) -> dict:
        self.calls.append((path, method))
        if self.role != "admin" and not path.startswith("/groups/mine"):
            raise AdminError("HTTP 403: Доступно только администратору.",
                             status=403)
        parts = [p for p in path.split("/") if p]

        if path == "/admin/users" and method == "GET":
            return {"users": list(self.users.values())}
        if parts[:2] == ["admin", "users"] and parts[-1] == "role":
            login = parts[2]
            if login == "root":
                raise AdminError("HTTP 400: Нельзя изменить собственную роль.",
                                 status=400)
            self.users[login]["role"] = payload["role"]
            return {"login": login, "role": payload["role"]}

        if path == "/admin/groups" and method == "GET":
            return {"groups": list(self.groups.values())}
        if path == "/admin/groups" and method == "POST":
            gid = self.next_gid
            self.next_gid += 1
            self.groups[gid] = {"id": gid, "name": payload["name"],
                                "members": [], "teachers": [],
                                "member_count": 0}
            return self.groups[gid]
        if parts[:2] == ["admin", "groups"] and "members" in parts:
            gid = int(parts[2])
            g = self.groups[gid]
            if method == "POST":
                g["members"].append(payload["login"])
            else:  # DELETE .../members/{login}
                g["members"] = [m for m in g["members"] if m != parts[-1]]
            g["member_count"] = len(g["members"])
            return g
        if parts[:2] == ["admin", "groups"] and "teachers" in parts:
            gid = int(parts[2])
            g = self.groups[gid]
            if method == "POST":
                g["teachers"].append(payload["login"])
            else:
                g["teachers"] = [t for t in g["teachers"] if t != parts[-1]]
            return g
        if path == "/groups/mine":
            return {"groups": []}
        raise AssertionError(f"неизвестный путь {method} {path}")


def _client(server, *, base_url="http://x", role="admin", login="root"):
    return AdminClient(base_url=base_url, transport=server.transport,
                       user_id_provider=lambda: login,
                       user_role_provider=lambda: role)


class CanUseTests(unittest.TestCase):
    def test_needs_server_and_admin(self):
        srv = FakeAdminServer()
        self.assertTrue(_client(srv).can_use())
        self.assertFalse(_client(srv, base_url="").can_use())     # нет сервера
        self.assertFalse(_client(srv, role="teacher").can_use())  # не admin


class UsersTests(unittest.TestCase):
    def test_list_users(self):
        srv = FakeAdminServer()
        users = _client(srv).list_users()
        self.assertEqual({u["login"] for u in users}, {"root", "alla"})

    def test_change_role(self):
        srv = FakeAdminServer()
        out = _client(srv).change_role("alla", "admin")
        self.assertEqual(out, {"login": "alla", "role": "admin"})
        self.assertEqual(srv.users["alla"]["role"], "admin")

    def test_change_role_guardrail_surfaces_400(self):
        srv = FakeAdminServer()
        with self.assertRaises(AdminError) as cm:
            _client(srv).change_role("root", "teacher")
        self.assertEqual(cm.exception.status, 400)

    def test_non_admin_gets_403(self):
        srv = FakeAdminServer(role="teacher")
        with self.assertRaises(AdminError) as cm:
            _client(srv, role="teacher").list_users()
        self.assertEqual(cm.exception.status, 403)


class GroupsTests(unittest.TestCase):
    def test_create_add_remove_flow_and_methods(self):
        srv = FakeAdminServer()
        c = _client(srv)
        g = c.create_group("Поток А")
        gid = g["id"]
        c.add_member(gid, "alla")
        c.assign_teacher(gid, "alla")
        groups = c.list_groups()
        self.assertEqual(groups[0]["members"], ["alla"])
        self.assertEqual(groups[0]["teachers"], ["alla"])
        c.remove_member(gid, "alla")
        c.unassign_teacher(gid, "alla")
        groups = c.list_groups()
        self.assertEqual(groups[0]["members"], [])
        self.assertEqual(groups[0]["teachers"], [])
        # DELETE реально ушёл методом DELETE (а не POST).
        methods = {m for p, m in srv.calls if "members/alla" in p}
        self.assertIn("DELETE", methods)

    def test_transport_error_wrapped(self):
        def boom(path, payload, method):
            raise ConnectionError("сеть")
        c = AdminClient(base_url="http://x", transport=boom,
                        user_id_provider=lambda: "root",
                        user_role_provider=lambda: "admin")
        with self.assertRaises(AdminError):
            c.list_users()


if __name__ == "__main__":
    unittest.main()
