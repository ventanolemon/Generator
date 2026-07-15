"""
AnalyticsClient (десктоп, headless): формирование запроса overview с
параметрами периода/группы, гейтинг can_use, оборачивание ошибок сервера в
AnalyticsError со status.

Запуск: python -m unittest tests.test_analytics_client
"""

from __future__ import annotations
import unittest
import urllib.parse

from core.analytics import AnalyticsClient, AnalyticsError


class FakeAnalyticsServer:
    def __init__(self):
        self.paths: list[str] = []

    def transport(self, path: str) -> dict:
        self.paths.append(path)
        query = urllib.parse.parse_qs(path.split("?", 1)[1]) if "?" in path else {}
        return {
            "scope": {"range_days": int(query.get("range_days", ["30"])[0]),
                      "group": query.get("group", [None])[0]},
            "totals": {"attempts": 10, "correct_rate": 0.7},
            "timeseries": [], "correctness_distribution": [],
            "tasks": [], "students": [], "groups": [],
        }


def _client(server=None, *, base_url="http://x", role="teacher"):
    return AnalyticsClient(
        base_url=base_url,
        transport=(server.transport if server else None),
        user_id_provider=lambda: "alla",
        user_role_provider=lambda: role)


class CanUseTests(unittest.TestCase):
    def test_needs_server_and_teacher_or_admin(self):
        srv = FakeAnalyticsServer()
        self.assertTrue(_client(srv).can_use())
        self.assertTrue(_client(srv, role="admin").can_use())
        self.assertFalse(_client(srv, base_url="").can_use())
        self.assertFalse(_client(srv, role="student").can_use())


class OverviewTests(unittest.TestCase):
    def test_default_range_and_no_group(self):
        srv = FakeAnalyticsServer()
        out = _client(srv).overview()
        self.assertEqual(out["scope"]["range_days"], 30)
        self.assertNotIn("group=", srv.paths[0])

    def test_range_and_group_encoded(self):
        srv = FakeAnalyticsServer()
        _client(srv).overview(7, group="КСБО-11-24")
        path = srv.paths[0]
        self.assertIn("range_days=7", path)
        self.assertIn("group=", path)
        # Кириллица корректно urlencoded.
        self.assertIn(urllib.parse.quote("КСБО-11-24"), path)

    def test_http_error_wrapped_with_status(self):
        def boom(path):
            raise AnalyticsError("HTTP 401: Нет заголовка X-User-Id.",
                                 status=401)
        c = AnalyticsClient(base_url="http://x", transport=boom,
                            user_id_provider=lambda: "alla",
                            user_role_provider=lambda: "teacher")
        with self.assertRaises(AnalyticsError) as cm:
            c.overview()
        self.assertEqual(cm.exception.status, 401)

    def test_transport_error_wrapped(self):
        def boom(path):
            raise ConnectionError("сеть")
        c = AnalyticsClient(base_url="http://x", transport=boom,
                            user_id_provider=lambda: "alla",
                            user_role_provider=lambda: "teacher")
        with self.assertRaises(AnalyticsError):
            c.overview()


if __name__ == "__main__":
    unittest.main()
