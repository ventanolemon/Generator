"""
C2 плана docs/ui_rework_plan.md — окно «Генератор через ИИ» (мастер контура).

Сервер — in-memory FakeContourServer из tests.test_contour_client (тот же
протокол, без сети), поэтому фоновые вызовы детерминированно быстрые: тесты
крутят цикл событий до прихода сигнала воркера/поллера — проверяется
РЕАЛЬНЫЙ путь QThread → сигнал → слот и QTimer-поллинг, а не подмена слотов.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_contour_window
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QProgressBar
    HAS_QT = True
except Exception:
    HAS_QT = False

if HAS_QT:
    import tempfile

    from core.contour import ContourClient
    from core.contour.client import AWAITING_HUMAN, FAILED, REJECTED
    from core.repository import Subject
    from core.settings import Settings
    from tests.test_contour_client import FakeContourServer
    from ui.app_context import AppContext
    from ui.windows.contour_window import (
        STAGE_DECISION, STAGE_DISABLED, STAGE_FORM, STAGE_WAITING,
        ContourWindow,
    )


class _FakeRepo:
    """Ровно та поверхность Repository, что нужна окну: list_subjects."""

    def __init__(self, subjects):
        self._subjects = list(subjects)

    def list_subjects(self):
        return list(self._subjects)


_PREVIEWS = [
    {"seed": 101, "statement": "Вычислите предел (x²−1)/(x−1) при x→1.",
     "answer": "2"},
    {"seed": 202, "statement": "Вычислите предел (x²−4)/(x−2) при x→2.",
     "answer": "4"},
    {"seed": 303, "statement": "Вычислите предел (x²−9)/(x−3) при x→3.",
     "answer": "6"},
]
_FLAGS = ["ответы попадают в узкий диапазон"]
_CRITIC = {"summary": "Формулировки корректны, разнообразие приемлемое.",
           "confidence": 0.82}


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ContourWindowTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server = FakeContourServer()
        self.repo = _FakeRepo([Subject(1, "Математика", ""),
                               Subject(2, "Физика", "")])
        self.settings = Settings(QSettings(tempfile.mktemp(suffix=".ini"),
                                           QSettings.Format.IniFormat))

    def _client(self, role="teacher", base_url="http://fake"):
        return ContourClient(base_url=base_url,
                             transport=self.server.transport,
                             user_id_provider=lambda: "7",
                             user_role_provider=lambda: role)

    def _window(self, client=None) -> "ContourWindow":
        ctx = AppContext(repo=self.repo, settings=self.settings,
                         user_id_provider=lambda: "7",
                         user_role_provider=lambda: "teacher",
                         contour_client=(client if client is not None
                                         else self._client()))
        w = ContourWindow(ctx, poll_interval_ms=30)
        self.addCleanup(w.deleteLater)
        return w

    def _spin(self, predicate, timeout=6.0):
        """Крутить цикл событий, пока условие не выполнится (или таймаут)."""
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline,
                            "условие не наступило за отведённое время")
            self.app.processEvents()
            time.sleep(0.01)

    # --- сценарные помощники ---

    def _submit(self, w: "ContourWindow",
                description="Предел рациональной дроби") -> str:
        """Заполнить форму, отправить, дождаться стадии ожидания."""
        w.description_edit.setPlainText(description)
        w.submit_btn.click()
        self._spin(lambda: w.stack.currentIndex() == STAGE_WAITING)
        self._spin(lambda: w._worker is None)
        job_id = w._job_id
        self.assertIn(job_id, self.server.jobs)
        return job_id

    def _settle(self, w: "ContourWindow", job_id: str, **fields) -> None:
        """Перевести фейковую джобу в новое состояние и дождаться решения."""
        self.server.jobs[job_id].update(fields)
        self._spin(lambda: w.stack.currentIndex() == STAGE_DECISION)

    def _decision_to_awaiting(self, w: "ContourWindow") -> str:
        job_id = self._submit(w)
        self._settle(w, job_id, status=AWAITING_HUMAN, previews=_PREVIEWS,
                     flags=_FLAGS, critic=_CRITIC)
        return job_id

    def _preview_cards(self, w: "ContourWindow") -> list:
        return [f for f in w._decision_host.findChildren(QFrame)
                if f.property("preview_seed") is not None]


class FormStageTests(ContourWindowTestBase):
    """Стадия 1: постановка джобы, валидация, ошибки сервера."""

    def test_submit_creates_job_and_switches_to_waiting(self):
        w = self._window()
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)
        self.assertEqual(w.subject_combo.count(), 2)

        w.subject_combo.setCurrentIndex(1)  # Физика, id=2
        job_id = self._submit(w, "Закон Ома для участка цепи")

        job = self.server.jobs[job_id]
        self.assertEqual(job["subject_id"], 2)
        self.assertEqual(job["description"], "Закон Ома для участка цепи")
        self.assertEqual(job["constraints"], {})  # тип «авто» — без огранич.
        self.assertTrue(w.poller.is_active(), "поллер следит за джобой")
        self.assertIn("Закон Ома", w.waiting_description_label.text())
        self.assertIn("очереди", w.waiting_status_label.text())

    def test_task_type_constraint_sent_when_not_auto(self):
        w = self._window()
        idx = w.task_type_combo.findData("interactive")
        self.assertGreaterEqual(idx, 0)
        w.task_type_combo.setCurrentIndex(idx)
        job_id = self._submit(w)
        self.assertEqual(self.server.jobs[job_id]["constraints"],
                         {"task_type": "interactive"})

    def test_empty_description_blocks_submit(self):
        w = self._window()
        w.submit_btn.click()
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)
        self.assertTrue(w.form_error_label.isVisibleTo(w))
        self.assertEqual(self.server.jobs, {}, "джоба не поставлена")

    def test_create_error_shown_on_form(self):
        w = self._window()
        w.description_edit.setPlainText("х")
        self.server.fail_next = True
        w.submit_btn.click()
        self._spin(lambda: w._worker is None)
        self._spin(lambda: w.form_error_label.isVisibleTo(w))
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM,
                         "при ошибке остаёмся на форме")
        self.assertIn("сеть оборвалась", w.form_error_label.text())
        self.assertTrue(w.submit_btn.isEnabled(), "кнопка вернулась")


class WaitingStageTests(ContourWindowTestBase):
    """Стадия 2: живой статус, обрыв сети, отмена наблюдения."""

    def test_status_line_follows_job_status(self):
        w = self._window()
        job_id = self._submit(w)
        self.server.jobs[job_id]["status"] = "running"
        self._spin(lambda: "петля работает" in w.waiting_status_label.text())

    def test_poll_error_shown_but_polling_continues(self):
        w = self._window()
        job_id = self._submit(w)
        self.server.fail_next = True
        self._spin(lambda: w.poll_error_label.isVisibleTo(w))
        self.assertTrue(w.poller.is_active(), "обрыв сети не терминален")
        # Следующий успешный опрос прячет строку сбоя.
        self._settle(w, job_id, status=AWAITING_HUMAN, previews=_PREVIEWS)

    def test_cancel_watch_stops_poller_and_returns_to_form(self):
        w = self._window()
        self._submit(w)
        w.cancel_watch_btn.click()
        self.assertFalse(w.poller.is_active())
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)
        self.assertTrue(w.form_info_label.isVisibleTo(w))
        self.assertIn("продолжает выполняться", w.form_info_label.text())


class DecisionStageTests(ContourWindowTestBase):
    """Стадия 3: превью/флаги/критик, approve с сигналом, reject, failed."""

    def test_awaiting_human_shows_previews_flags_and_critic(self):
        w = self._window()
        self._decision_to_awaiting(w)

        cards = self._preview_cards(w)
        self.assertEqual(len(cards), 3)
        texts = " ".join(lbl.text() for c in cards
                         for lbl in c.findChildren(type(w.form_error_label)))
        self.assertIn("(x²−1)/(x−1)", texts)
        self.assertIn("Ответ: 2", texts)
        self.assertIn("seed 101", texts)

        chips = [lbl for lbl in w._decision_host.findChildren(
            type(w.form_error_label))
            if lbl.property("class") == "badge-warn"]
        self.assertEqual([c.text() for c in chips], _FLAGS)

        all_text = " ".join(lbl.text() for lbl in
                            w._decision_host.findChildren(
                                type(w.form_error_label)))
        self.assertIn("Критик:", all_text)
        self.assertIn("0.82", all_text)
        # Имя партиции предзаполнено началом описания.
        self.assertEqual(w.partition_name_edit.text(),
                         "Предел рациональной дроби")

    def test_decision_shows_verdict_badge_meter_and_rounds(self):
        # Апгрейд экрана приёмки: вердикт-бейдж, метр уверенности, таймлайн.
        w = self._window()
        job_id = self._submit(w)
        self._settle(
            w, job_id, status=AWAITING_HUMAN, previews=_PREVIEWS,
            critic={"summary": "Ок.", "confidence": 0.9, "verdict": "accept"},
            rounds=[{"stage": "генерация", "verdict": "accept"},
                    {"stage": "критик", "verdict": "accept"}])
        # Метр уверенности = 90.
        meters = w._decision_host.findChildren(QProgressBar)
        self.assertTrue(any(m.value() == 90 for m in meters))
        # Вердикт-бейдж «принять» с классом badge-ok (НЕ badge-warn).
        oks = [lbl for lbl in w._decision_host.findChildren(QLabel)
               if lbl.property("class") == "badge-ok"]
        self.assertEqual([b.text() for b in oks], ["принять"])
        # Таймлайн раундов — есть строки со стадиями.
        all_text = " ".join(lbl.text()
                             for lbl in w._decision_host.findChildren(QLabel))
        self.assertIn("Раунды контура", all_text)
        self.assertIn("генерация", all_text)
        # Кнопка приёмки — первичная.
        self.assertEqual(w.approve_btn.property("class"), "primary")

    def test_approve_calls_api_and_emits_partition_created(self):
        w = self._window()
        job_id = self._decision_to_awaiting(w)
        created = []
        w.partition_created.connect(created.append)

        w.partition_name_edit.setText("Пределы: устранимая особенность")
        w.approve_btn.click()
        self._spin(lambda: created)

        self.assertEqual(created, [777])  # partition_id фейка
        path, payload = next(c for c in self.server.calls
                             if c[0].endswith("/approve"))
        self.assertIn(job_id, path)
        self.assertEqual(payload["partition_name"],
                         "Пределы: устранимая особенность")
        self.assertEqual(self.server.jobs[job_id]["status"], "approved")
        # Итог показан на месте, есть возврат к форме.
        self._spin(lambda: w._worker is None)
        all_text = " ".join(lbl.text() for lbl in
                            w._decision_host.findChildren(
                                type(w.form_error_label)))
        self.assertIn("777", all_text)
        w.restart_btn.click()
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)

    def test_reject_requires_reason_then_returns_to_form(self):
        w = self._window()
        job_id = self._decision_to_awaiting(w)

        w.reject_btn.click()
        self.assertTrue(w._reject_row.isVisibleTo(w), "поле причины открылось")
        w.reject_confirm_btn.click()  # пустая причина — не уходит
        self.assertTrue(w.decision_error_label.isVisibleTo(w))
        self.assertEqual(self.server.jobs[job_id]["status"], AWAITING_HUMAN)

        w.reject_reason_edit.setText("однотипные формулировки")
        w.reject_confirm_btn.click()
        self._spin(lambda: w.stack.currentIndex() == STAGE_FORM)
        self._spin(lambda: w._worker is None)

        self.assertEqual(self.server.jobs[job_id]["status"], REJECTED)
        path, payload = next(c for c in self.server.calls
                             if c[0].endswith("/reject"))
        self.assertEqual(payload["reason"], "однотипные формулировки")
        self.assertTrue(w.form_info_label.isVisibleTo(w))
        self.assertIn("отклонена", w.form_info_label.text())

    def test_failed_job_shows_error_and_restart(self):
        w = self._window()
        job_id = self._submit(w)
        self._settle(w, job_id, status=FAILED,
                     error="LLM не собрал валидный граф за 3 раунда")

        all_text = " ".join(lbl.text() for lbl in
                            w._decision_host.findChildren(
                                type(w.form_error_label)))
        self.assertIn("LLM не собрал валидный граф", all_text)
        danger = [lbl for lbl in w._decision_host.findChildren(
            type(w.form_error_label))
            if lbl.property("class") == "danger" and lbl.text()]
        self.assertTrue(danger, "ошибка показана danger-стилем")
        w.restart_btn.click()
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)

    def test_already_settled_elsewhere_shows_info(self):
        w = self._window()
        job_id = self._submit(w)
        self._settle(w, job_id, status="approved")
        all_text = " ".join(lbl.text() for lbl in
                            w._decision_host.findChildren(
                                type(w.form_error_label)))
        self.assertIn("уже утверждена", all_text)


class GatingTests(ContourWindowTestBase):
    """can_use() ложен — окно объясняет почему, refresh() возвращает форму."""

    def test_student_role_shows_explanation(self):
        w = self._window(self._client(role="student"))
        self.assertEqual(w.stack.currentIndex(), STAGE_DISABLED)
        self.assertIn("преподавателям", w.disabled_label.text())

    def test_no_server_points_to_settings(self):
        w = self._window(self._client(base_url=""))
        self.assertEqual(w.stack.currentIndex(), STAGE_DISABLED)
        self.assertIn("Настройках", w.disabled_label.text())

    def test_no_client_shows_settings_hint(self):
        ctx = AppContext(repo=self.repo, settings=self.settings,
                         user_id_provider=lambda: "7",
                         user_role_provider=lambda: "teacher",
                         contour_client=None)
        w = ContourWindow(ctx)
        self.addCleanup(w.deleteLater)
        self.assertEqual(w.stack.currentIndex(), STAGE_DISABLED)
        self.assertIn("Настройках", w.disabled_label.text())

    def test_refresh_recovers_after_server_configured(self):
        client = self._client(base_url="")
        w = self._window(client)
        self.assertEqual(w.stack.currentIndex(), STAGE_DISABLED)
        client.set_base_url("http://fake")
        w.refresh()
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)
        self.assertEqual(w.subject_combo.count(), 2)

    def test_refresh_is_idempotent_and_keeps_selection(self):
        w = self._window()
        w.subject_combo.setCurrentIndex(1)
        w.refresh()
        w.refresh()
        self.assertEqual(w.subject_combo.currentData(), 2,
                         "выбор предмета пережил refresh")
        self.assertEqual(w.stack.currentIndex(), STAGE_FORM)


if __name__ == "__main__":
    unittest.main()
