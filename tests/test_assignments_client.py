"""
AssignmentsClient (десктоп, headless): create/teaching/mine/delete/my_groups,
маршрутизация GET/POST/DELETE, гейтинг can_use/can_assign, ошибки сервера.

Запуск: python -m unittest tests.test_assignments_client
"""

from __future__ import annotations
import unittest

from core.assignments import AssignmentsClient, AssignmentsError


class FakeServer:
    def __init__(self):
        self.assignments: dict[int, dict] = {}
        self.next_id = 1
        self.calls: list[tuple[str, str]] = []

    def transport(self, path: str, payload, method: str) -> dict:
        self.calls.append((path, method))
        if path == "/assignments" and method == "POST":
            aid = self.next_id
            self.next_id += 1
            rec = {"id": aid, "partition_name": "Задача",
                   "group_name": "Г1", **payload}
            self.assignments[aid] = rec
            return rec
        if path == "/assignments/teaching":
            items = [{**a, "member_count": 2, "solved_count": 1}
                     for a in self.assignments.values()]
            return {"assignments": items}
        if path == "/assignments/mine":
            return {"assignments": list(self.assignments.values())}
        if path.endswith("/progress") and method == "GET":
            aid = int(path.split("/")[2])
            return {"assignment": self.assignments.get(aid, {"id": aid}),
                    "students": [
                        {"login": "s1", "fio": "Иванов", "attempts": 2,
                         "solved": True, "last_at": 1.0},
                        {"login": "s2", "fio": "Петров", "attempts": 1,
                         "solved": False, "last_at": 1.0}],
                    "summary": {"members": 2, "attempted": 2, "solved": 1}}
        if path.startswith("/assignments/") and method == "DELETE":
            aid = int(path.rsplit("/", 1)[1])
            self.assignments.pop(aid, None)
            return {"deleted": aid}
        if path == "/groups/mine":
            return {"groups": [{"id": 1, "name": "Г1", "members": [],
                                "teachers": ["alla"]}]}
        raise AssertionError(f"неизвестный путь {method} {path}")


def _client(server=None, *, base_url="http://x", role="teacher", login="alla"):
    return AssignmentsClient(
        base_url=base_url,
        transport=(server.transport if server else None),
        user_id_provider=lambda: login,
        user_role_provider=lambda: role)


class GatingTests(unittest.TestCase):
    def test_can_use_requires_server_and_login(self):
        srv = FakeServer()
        self.assertTrue(_client(srv).can_use())
        self.assertFalse(_client(srv, base_url="").can_use())
        self.assertFalse(_client(srv, login=None).can_use())  # гость

    def test_can_assign_requires_teacher_or_admin(self):
        srv = FakeServer()
        self.assertTrue(_client(srv, role="teacher").can_assign())
        self.assertTrue(_client(srv, role="admin").can_assign())
        self.assertFalse(_client(srv, role="student").can_assign())


class ApiTests(unittest.TestCase):
    def test_create_teaching_delete_flow_methods(self):
        srv = FakeServer()
        c = _client(srv)
        out = c.create(10, 1, due_at=1000.0)
        aid = out["id"]
        self.assertEqual(out["partition_id"], 10)
        self.assertEqual(len(c.teaching()), 1)
        c.delete(aid)
        self.assertEqual(c.teaching(), [])
        methods = {m for p, m in srv.calls if p.startswith("/assignments/")}
        self.assertIn("DELETE", methods)

    def test_create_omits_due_when_none(self):
        srv = FakeServer()
        _client(srv).create(10, 1)
        # payload без due_at (проверяем через сохранённую запись).
        rec = list(srv.assignments.values())[0]
        self.assertNotIn("due_at", rec)

    def test_my_groups(self):
        srv = FakeServer()
        groups = _client(srv).my_groups()
        self.assertEqual([g["name"] for g in groups], ["Г1"])

    def test_teaching_carries_completion_counts(self):
        srv = FakeServer()
        c = _client(srv)
        c.create(10, 1)
        item = c.teaching()[0]
        self.assertEqual(item["member_count"], 2)
        self.assertEqual(item["solved_count"], 1)

    def test_progress(self):
        srv = FakeServer()
        c = _client(srv)
        out = c.create(10, 1)
        prog = c.progress(out["id"])
        self.assertEqual(prog["summary"]["solved"], 1)
        self.assertEqual(len(prog["students"]), 2)

    def test_error_wrapped(self):
        def boom(path, payload, method):
            raise ConnectionError("сеть")
        c = AssignmentsClient(base_url="http://x", transport=boom,
                              user_id_provider=lambda: "alla",
                              user_role_provider=lambda: "teacher")
        with self.assertRaises(AssignmentsError):
            c.teaching()


if __name__ == "__main__":
    unittest.main()
