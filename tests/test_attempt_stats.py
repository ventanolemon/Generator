"""
Статистика попыток решения (пункт 1 обсуждения после волны E плана
docs/ui_rework_plan.md): BaseTaskView.attach_stats/queue_attempt +
InteractiveTaskView пишет каждую попытку в outbox синка через
SyncClient.queue_attempt — ортогонально словарной WordStatsStore
(генератор пишет туда сам себе, эту статистику не трогаем).

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_attempt_stats
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    from core import Capability, InteractiveTask, TaskGenerator, TextBlock, TurnResult
    from ui.views import InteractiveTaskView, StaticTaskView
    from ui.views.base_view import BaseTaskView

    class _FakeSession(InteractiveTask):
        """Сессия из 2 вопросов; 'ok' — правильный ответ."""

        def __init__(self):
            self.turns = 0

        def initial_prompt(self):
            return [TextBlock("вопрос 1")]

        def submit(self, user_input: str) -> TurnResult:
            self.turns += 1
            nxt = [TextBlock("вопрос 2")] if self.turns < 2 else None
            return TurnResult(correct=(user_input == "ok"),
                              feedback=[TextBlock("фидбек")],
                              next_prompt=nxt)

        def is_finished(self) -> bool:
            return self.turns >= 2

    class _FakeInteractiveGen(TaskGenerator):
        name = "Фейк-сессия"
        capabilities = Capability.INTERACTIVE

        def generate(self):
            return _FakeSession()

    class _FakeStaticGen(TaskGenerator):
        name = "Фейк-статик"
        capabilities = Capability.STATIC

        def generate(self):
            from core import StaticTask
            return StaticTask([TextBlock("условие")], [TextBlock("ответ")])

    class _FakeSyncClient:
        """Заглушка SyncClient — фиксирует вызовы queue_attempt."""

        def __init__(self, *, raises: bool = False):
            self.calls: list[tuple[int, dict, bool | None]] = []
            self._raises = raises

        def queue_attempt(self, partition_id, payload, correct=None,
                          assignment_id=None):
            if self._raises:
                raise RuntimeError("диск переполнен")
            self.calls.append((partition_id, dict(payload), correct))
            self.last_assignment_id = assignment_id


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class BaseTaskViewStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_queue_attempt_noop_without_attach(self):
        v = StaticTaskView(_FakeStaticGen())
        self.addCleanup(v.deleteLater)
        v.queue_attempt({"x": 1}, correct=True)  # не падает, тихий no-op

    def test_attach_then_queue_attempt_forwards_to_client(self):
        v = StaticTaskView(_FakeStaticGen())
        self.addCleanup(v.deleteLater)
        client = _FakeSyncClient()
        v.attach_stats(partition_id=42, sync_client=client)
        v.queue_attempt({"input": "x"}, correct=True)
        self.assertEqual(client.calls, [(42, {"input": "x"}, True)])

    def test_attach_with_none_client_is_noop(self):
        v = StaticTaskView(_FakeStaticGen())
        self.addCleanup(v.deleteLater)
        v.attach_stats(partition_id=1, sync_client=None)
        v.queue_attempt({"x": 1}, correct=False)  # не падает

    def test_queue_attempt_swallows_client_errors(self):
        v = StaticTaskView(_FakeStaticGen())
        self.addCleanup(v.deleteLater)
        client = _FakeSyncClient(raises=True)
        v.attach_stats(partition_id=1, sync_client=client)
        v.queue_attempt({"x": 1}, correct=True)  # не пробрасывает исключение


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class InteractiveViewAttemptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_submit_queues_one_attempt(self):
        v = InteractiveTaskView(_FakeInteractiveGen())
        self.addCleanup(v.deleteLater)
        client = _FakeSyncClient()
        v.attach_stats(partition_id=7, sync_client=client)

        v.input_field.setText("ok")
        v._on_submit()
        v.input_field.setText("плохой ответ")
        v._on_submit()

        self.assertEqual(len(client.calls), 2)
        pid1, payload1, correct1 = client.calls[0]
        self.assertEqual(pid1, 7)
        self.assertEqual(payload1, {"input": "ok"})
        self.assertTrue(correct1)
        pid2, payload2, correct2 = client.calls[1]
        self.assertEqual(payload2, {"input": "плохой ответ"})
        self.assertFalse(correct2)

    def test_no_attach_means_no_crash_on_submit(self):
        v = InteractiveTaskView(_FakeInteractiveGen())
        self.addCleanup(v.deleteLater)
        v.input_field.setText("ok")
        v._on_submit()  # без attach_stats — тихий no-op, сессия продолжается
        self.assertEqual(v.score_correct, 1)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GeneratorWindowWiringTests(unittest.TestCase):
    """attach_stats получает верный partition_id и sync_client при клике."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_click_attaches_stats_with_partition_id_and_client(self):
        import sqlite3
        import tempfile
        from PyQt6.QtCore import QSettings, Qt
        from core.repository import Repository
        from core.settings import Settings
        from tests.test_sync_client import _make_local_db
        from ui.app_context import AppContext
        from ui.windows import GeneratorWindow

        db = tempfile.mktemp(suffix=".db")
        self.addCleanup(lambda: os.path.exists(db) and os.remove(db))
        _make_local_db(db)
        repo = Repository(db)
        repo.ensure_hidden_columns()
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO Subjects (id, subject_name, pra_subject) "
                         "VALUES (1, 'Физика', 'Физика')")
            conn.commit()
        pid = repo.upsert_partition(subject_id=1, name="Раздел",
                                    constracted=0, generation_params={})

        client = _FakeSyncClient()
        s = Settings(QSettings(tempfile.mktemp(suffix=".ini"),
                               QSettings.Format.IniFormat))
        ctx = AppContext(repo=repo, settings=s,
                         user_id_provider=lambda: "u",
                         user_role_provider=lambda: "teacher",
                         sync_client=client)

        gen = _FakeStaticGen()

        class _Reg:
            def get(self, partition_id, params=None):
                assert partition_id == pid
                return gen

        w = GeneratorWindow(context=ctx, registry=_Reg(),
                            registry_builder=lambda: _Reg())
        self.addCleanup(w.deleteLater)
        w.subject_combo.setCurrentIndex(0)
        self.app.processEvents()
        item = w.partition_list.item(0)
        w._on_partition_clicked(item)

        # attach_stats был вызван на реально показанном view с верными
        # partition_id/sync_client — проверяем через сквозной queue_attempt.
        view = w.view_layout.itemAt(0).widget()
        view.queue_attempt({"probe": True}, correct=True)
        self.assertEqual(client.calls, [(pid, {"probe": True}, True)])


if __name__ == "__main__":
    unittest.main()
