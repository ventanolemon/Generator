"""
B3 плана docs/ui_rework_plan.md — окно синхронизации: статус (сервер/очередь),
фоновый прогон sync() с отчётом SyncReport, разрешение конфликтов из списка,
бейдж-помощник для TopBar.

Транспорт — in-memory FakeServer из tests.test_sync_client (тот же протокол,
без сети), поэтому «фоновый» прогон детерминированно быстрый: тест крутит
цикл событий до прихода сигнала воркера — проверяется РЕАЛЬНЫЙ путь
QThread → сигнал → слот, а не подмена слота.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_sync_window
"""

from __future__ import annotations
import os
import time
import unittest
from tests.tmpdb import temp_path  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QPushButton
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    import tempfile

    from core.repository import Repository
    from core.settings import Settings
    from core.sync import SyncClient, SyncReport, SyncStore
    from tests.test_sync_client import FakeServer, _make_local_db
    from ui.app_context import AppContext
    from ui.windows.sync_window import SyncWindow, pending_badge_text


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class SyncWindowTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.db_path = temp_path(suffix=".db")
        _make_local_db(self.db_path)
        self.repo = Repository(self.db_path)
        self.store = SyncStore(self.db_path)
        self.server = FakeServer()
        # base_url задан → has_server() истинен; транспорт при этом фейковый
        # (инжекция выигрывает у боевого urllib).
        self.client = SyncClient(self.repo, self.store,
                                 base_url="http://fake-server",
                                 transport=self.server.transport)
        self.settings = Settings(QSettings(temp_path(suffix=".ini"),
                                           QSettings.Format.IniFormat))
        self.settings.set_base_url("http://fake-server")

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _ctx(self, client=None) -> "AppContext":
        return AppContext(repo=self.repo, settings=self.settings,
                          user_id_provider=lambda: "u1",
                          user_role_provider=lambda: "teacher",
                          sync_client=client if client is not None
                          else self.client)

    def _window(self, client=None) -> "SyncWindow":
        w = SyncWindow(self._ctx(client))
        self.addCleanup(w.deleteLater)
        return w

    def _wait_sync_done(self, window: "SyncWindow", timeout: float = 5.0):
        """Крутить цикл событий, пока воркер не доставит отчёт в слот."""
        deadline = time.monotonic() + timeout
        while window._worker is not None:
            self.assertLess(time.monotonic(), deadline,
                            "воркер не завершился за отведённое время")
            self.app.processEvents()
            time.sleep(0.01)

    def _seed_conflict(self) -> None:
        """Один неразрешённый конфликт по партиции 10 (обе версии в стэше)."""
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Общая",
            "constracted": 0, "generation_parametrs": ""})
        self.client.sync()
        self.server.seed("partition", 10, {
            "subject_id": 1, "partition_name": "Версия сервера",
            "constracted": 0, "generation_parametrs": ""})
        self.client.queue_partition_change(10, {
            "subject_id": 1, "partition_name": "Моя версия",
            "constracted": 0, "generation_parametrs": ""})
        self.client.sync()
        assert len(self.store.unresolved_conflicts()) == 1

    def _conflict_cards(self, window: "SyncWindow") -> list:
        return [w for w in window._conflicts_host.findChildren(QFrame)
                if w.property("conflict_id") is not None]


class StatusTests(SyncWindowTestBase):
    """Статус-зона: адрес сервера, счётчик очереди, доступность кнопки."""

    def test_pending_count_and_server_shown(self):
        self.client.queue_attempt(7, {"answer": "42"})
        self.client.queue_partition_change(10, {"partition_name": "X"})
        w = self._window()
        self.assertIn("2", w.pending_label.text())
        self.assertIn("http://fake-server", w.server_label.text())
        self.assertTrue(w.sync_btn.isEnabled())

    def test_no_server_disables_button_and_hints(self):
        self.settings.set_base_url("")
        client = SyncClient(self.repo, self.store, base_url="",
                            transport=self.server.transport)
        w = self._window(client)
        self.assertFalse(w.sync_btn.isEnabled())
        self.assertIn("не задан", w.server_label.text())
        # До первого прогона статус «ещё не запускалась».
        self.assertIn("не запускалась", w.last_sync_label.text())

    def test_refresh_recomputes_pending(self):
        w = self._window()
        self.assertIn("все изменения отправлены", w.pending_label.text())
        self.client.queue_attempt(1, {"a": 1})
        w.refresh()
        self.assertIn("1", w.pending_label.text())


class SyncRunTests(SyncWindowTestBase):
    """Прогон по кнопке: воркер в фоне, отчёт в статусе, очередь ушла."""

    def test_sync_run_updates_status_and_clears_queue(self):
        self.client.queue_attempt(7, {"answer": "42"})
        self.server.seed("partition", 20, {
            "subject_id": 1, "partition_name": "С сервера",
            "constracted": 0, "generation_parametrs": ""})
        w = self._window()

        w.sync_btn.click()
        self.assertFalse(w.sync_btn.isEnabled(), "кнопка выключена на время прогона")
        self._wait_sync_done(w)

        self.assertTrue(w.sync_btn.isEnabled(), "кнопка вернулась после прогона")
        status = w.last_sync_label.text()
        self.assertIn("успешно", status)
        self.assertIn("отправлено попыток: 1", status)
        self.assertIn("1 разд.", status)
        self.assertFalse(w.errors_label.isVisibleTo(w))
        self.assertIn("все изменения отправлены", w.pending_label.text())
        self.assertEqual(self.store.pending(), [])

    def test_sync_errors_shown_in_danger_area(self):
        # Детерминированный путь обработки результата: слот вызывается
        # напрямую с синтетическим отчётом (контракт _on_sync_finished).
        w = self._window()
        w._on_sync_finished(SyncReport(errors=["push: сеть оборвалась"]))
        self.assertIn("ошибками", w.last_sync_label.text())
        self.assertTrue(w.errors_label.isVisibleTo(w))
        self.assertIn("сеть оборвалась", w.errors_label.text())

    def test_failed_run_keeps_queue(self):
        self.client.queue_attempt(7, {"answer": "x"})
        self.server.fail_next_push = True
        w = self._window()
        w.sync_btn.click()
        self._wait_sync_done(w)
        self.assertTrue(w.errors_label.isVisibleTo(w))
        self.assertIn("1", w.pending_label.text(), "очередь не потеряна")


class ConflictUITests(SyncWindowTestBase):
    """Список конфликтов: показ обеих версий и разрешение кнопками."""

    def test_conflict_card_shows_both_versions(self):
        self._seed_conflict()
        w = self._window()
        cards = self._conflict_cards(w)
        self.assertEqual(len(cards), 1)
        self.assertFalse(w.no_conflicts_label.isVisibleTo(w))
        texts = " ".join(lbl.text() for lbl in cards[0].findChildren(QLabel))
        self.assertIn("Моя версия", texts)
        self.assertIn("Версия сервера", texts)
        self.assertIn("раздел #10", texts)

    def test_resolve_theirs_removes_card(self):
        self._seed_conflict()
        w = self._window()
        card = self._conflict_cards(w)[0]
        btn = next(b for b in card.findChildren(QPushButton)
                   if "серверную" in b.text())
        btn.click()
        self.assertEqual(self.store.unresolved_conflicts(), [])
        self.assertEqual(self._conflict_cards(w), [])
        self.assertTrue(w.no_conflicts_label.isVisibleTo(w))
        self.assertIn("все изменения отправлены", w.pending_label.text())

    def test_resolve_mine_requeues_and_updates_pending(self):
        self._seed_conflict()
        w = self._window()
        card = self._conflict_cards(w)[0]
        btn = next(b for b in card.findChildren(QPushButton)
                   if "мою" in b.text())
        btn.click()
        self.assertEqual(self.store.unresolved_conflicts(), [])
        self.assertEqual(self._conflict_cards(w), [])
        # «Оставить мою» пере-ставит правку в outbox — счётчик очереди растёт.
        self.assertIn("1", w.pending_label.text())

    def test_no_conflicts_placeholder(self):
        w = self._window()
        self.assertTrue(w.no_conflicts_label.isVisibleTo(w))
        self.assertEqual(self._conflict_cards(w), [])


class BadgeHelperTests(SyncWindowTestBase):
    """pending_badge_text — сводка для TopBar.set_badge (контракт для Opus)."""

    def test_empty_state_hides_badge(self):
        self.assertEqual(pending_badge_text(self.client), ("", ""))
        self.assertEqual(pending_badge_text(None), ("", ""))

    def test_pending_gives_warn(self):
        self.client.queue_attempt(1, {"a": 1})
        text, level = pending_badge_text(self.client)
        self.assertEqual(level, "warn")
        self.assertIn("1", text)

    def test_conflicts_beat_pending_with_error(self):
        self._seed_conflict()
        self.client.queue_attempt(1, {"a": 1})
        text, level = pending_badge_text(self.client)
        self.assertEqual(level, "error")
        self.assertIn("конфликт", text)


if __name__ == "__main__":
    unittest.main()
