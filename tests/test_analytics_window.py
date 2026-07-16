"""
AnalyticsWindow (offscreen Qt): доступность (заглушка без сервера/студенту),
загрузка и рендер KPI/динамики/распределения/таблиц, пустое состояние,
смена периода → повторный запрос.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_analytics_window
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.analytics import AnalyticsClient

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


def _overview(*, attempts=1284, days=30, group=None):
    return {
        "generated_at": "2026-07-12T09:00:00Z",
        "scope": {"role": "teacher", "owner": "alla", "range_days": days,
                  "group": group},
        "totals": {"attempts": attempts, "students_active": 47,
                   "correct_rate": 0.71, "tasks_active": 18,
                   "attempts_delta_pct": 0.12, "correct_rate_delta": 0.03},
        "timeseries": [{"date": "2026-07-10", "attempts": 59, "correct": 45},
                       {"date": "2026-07-11", "attempts": 48, "correct": 37}],
        "correctness_distribution": [
            {"bucket": "0–20%", "students": 3},
            {"bucket": "80–100%", "students": 14}],
        "tasks": [{"partition_id": 12, "name": "Сила F=ma", "subject": "Физика",
                   "type": "graph", "attempts": 210, "correct_rate": 0.64,
                   "avg_attempts_to_correct": 2.3, "students": 41,
                   "difficulty": "medium"}],
        "students": [{"login": "s_ivanov", "fio": "Иванов И. А.",
                      "group": "КСБО-11-24", "attempts": 63,
                      "correct_rate": 0.58, "status": "struggling"}],
        "groups": [{"group": "КСБО-11-24", "students": 24,
                    "correct_rate": 0.73, "attempts": 512, "coverage": 0.86}],
    }


class FakeServer:
    def __init__(self, data=None):
        self.data = data if data is not None else _overview()
        self.calls: list[str] = []

    def transport(self, path: str) -> dict:
        self.calls.append(path)
        return self.data


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AnalyticsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, role="teacher", base_url="http://x", server=None):
        from types import SimpleNamespace
        from ui.windows.analytics_window import AnalyticsWindow

        srv = server or FakeServer()
        client = AnalyticsClient(base_url=base_url, transport=srv.transport,
                                 user_id_provider=lambda: "alla",
                                 user_role_provider=lambda: role)
        ctx = SimpleNamespace(analytics_client=client,
                              settings=SimpleNamespace(get_theme=lambda: "dark"),
                              user_id_provider=lambda: "alla",
                              user_role_provider=lambda: role)
        w = AnalyticsWindow(ctx)
        self.addCleanup(w.deleteLater)
        self._srv = srv
        return w

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "условие не наступило")
            self.app.processEvents()
            time.sleep(0.01)

    def _settle(self, w):
        self._spin(lambda: w._worker is None)

    # ---------- доступность ----------

    def test_disabled_without_server(self):
        w = self._window(base_url="")
        self.assertFalse(w.notice_label.isHidden())
        self.assertIn("адрес сервера", w.notice_label.text())

    def test_disabled_for_student(self):
        w = self._window(role="student")
        self.assertFalse(w.notice_label.isHidden())
        self.assertIn("студент", w.notice_label.text())

    # ---------- рендер ----------

    def test_kpis_and_tables_populate(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: w.tasks_table.rowCount() == 1)
        self.assertEqual(w.tile_attempts.value_label.text(), "1284")
        self.assertEqual(w.tile_rate.value_label.text(), "71%")
        self.assertIn("+12%", w.tile_attempts.delta_label.text())
        self.assertIn("п.п.", w.tile_rate.delta_label.text())
        # Таблицы.
        self.assertEqual(w.students_table.rowCount(), 1)
        self.assertEqual(w.groups_table.rowCount(), 1)
        # Тип/сложность локализованы.
        row_texts = [w.tasks_table.item(0, c).text()
                     for c in range(w.tasks_table.columnCount())]
        self.assertIn("Граф", row_texts)
        self.assertIn("среднее", row_texts)

    def test_charts_receive_data(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: len(w.timeseries_chart.bars) == 2)
        self.assertEqual(len(w.dist_chart.bars), 2)
        # У динамики есть «верная» часть (filled), у распределения — нет.
        self.assertIsNotNone(w.timeseries_chart.bars[0].filled)
        self.assertIsNone(w.dist_chart.bars[0].filled)

    def test_group_combo_synced_from_data(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: w.group_combo.count() == 2)  # «Все группы» + 1
        names = [w.group_combo.itemText(i)
                 for i in range(w.group_combo.count())]
        self.assertIn("КСБО-11-24", names)

    def test_empty_state_keeps_controls(self):
        srv = FakeServer(_overview(attempts=0))
        w = self._window(server=srv)
        self._settle(w)
        self._spin(lambda: not w.notice_label.isHidden())
        self.assertIn("Пока нет", w.notice_label.text())
        # Селектор периода остаётся доступен (можно сменить диапазон).
        self.assertFalse(w.range_combo.isHidden())

    def test_range_change_refetches(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: len(self._srv.calls) >= 1)
        before = len(self._srv.calls)
        w.range_combo.setCurrentIndex(0)   # 7 дней → повторный запрос
        self._settle(w)
        self._spin(lambda: len(self._srv.calls) > before)
        self.assertIn("range_days=7", self._srv.calls[-1])


if __name__ == "__main__":
    unittest.main()
