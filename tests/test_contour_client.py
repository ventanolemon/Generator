"""
C1 плана docs/ui_rework_plan.md — клиент LLM-контура и Qt-поллер.

Клиент (headless): формирование вызовов create/get/list/approve/reject,
гейтинг can_use по роли и адресу, оборачивание ошибок в ContourError.
Поллер (offscreen): реальный цикл QTimer→QThread→сигнал — джоба проходит
queued→running→awaiting_human, поллер эмитит job_updated и останавливается
на settled; обрыв сети не терминален.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_contour_client
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.contour import ContourClient, ContourError
from core.contour.client import AWAITING_HUMAN, QUEUED, RUNNING

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


class FakeContourServer:
    """Фейк API джоб в памяти: та же семантика, что routers/jobs.py."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.calls: list[tuple[str, dict | None]] = []
        self.next_id = 1
        self.fail_next = False

    def transport(self, path: str, payload):
        self.calls.append((path, payload))
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("сеть оборвалась")
        if path == "/contour/jobs" and payload is not None:
            job_id = f"job-{self.next_id}"
            self.next_id += 1
            self.jobs[job_id] = {"job_id": job_id, "status": QUEUED,
                                 **payload}
            return {"job_id": job_id, "status": QUEUED}
        if path == "/contour/jobs" and payload is None:
            return {"jobs": list(self.jobs.values())}
        if path.endswith("/approve"):
            job_id = path.split("/")[-2]
            self.jobs[job_id]["status"] = "approved"
            return {"job_id": job_id, "status": "approved",
                    "partition_id": 777}
        if path.endswith("/reject"):
            job_id = path.split("/")[-2]
            self.jobs[job_id]["status"] = "rejected"
            return {"job_id": job_id, "status": "rejected"}
        job_id = path.split("/")[-1]
        job = self.jobs.get(job_id)
        if job is None:
            raise ContourError("HTTP 404: Джоба не найдена.")
        return dict(job)


def _client(server: FakeContourServer, role="teacher") -> ContourClient:
    return ContourClient(base_url="http://fake", transport=server.transport,
                         user_id_provider=lambda: "7",
                         user_role_provider=lambda: role)


class ClientCallTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeContourServer()
        self.client = _client(self.server)

    def test_create_job_returns_id(self):
        resp = self.client.create_job("Предел с заменой", 8)
        self.assertEqual(resp["status"], QUEUED)
        self.assertIn(resp["job_id"], self.server.jobs)
        # POST-пейлоад содержит описание/предмет/ограничения.
        path, payload = self.server.calls[-1]
        self.assertEqual(path, "/contour/jobs")
        self.assertEqual(payload["subject_id"], 8)
        self.assertEqual(payload["constraints"], {})

    def test_get_and_list(self):
        job_id = self.client.create_job("x", 1)["job_id"]
        self.assertEqual(self.client.get_job(job_id)["status"], QUEUED)
        self.assertEqual(len(self.client.list_jobs()), 1)

    def test_approve_and_reject(self):
        a = self.client.create_job("a", 1)["job_id"]
        b = self.client.create_job("b", 1)["job_id"]
        resp = self.client.approve(a, partition_name="Готовое")
        self.assertEqual(resp["partition_id"], 777)
        self.assertEqual(self.client.reject(b, "не то")["status"], "rejected")
        # reject ушёл с причиной в теле.
        path, payload = self.server.calls[-1]
        self.assertTrue(path.endswith(f"/{b}/reject"))
        self.assertEqual(payload["reason"], "не то")

    def test_network_error_wrapped(self):
        self.server.fail_next = True
        with self.assertRaises(ContourError):
            self.client.get_job("job-нет")

    def test_can_use_gating(self):
        self.assertTrue(_client(self.server, "teacher").can_use())
        self.assertTrue(_client(self.server, "admin").can_use())
        self.assertFalse(_client(self.server, "student").can_use())
        no_server = ContourClient(base_url="",
                                  transport=self.server.transport,
                                  user_role_provider=lambda: "admin")
        self.assertFalse(no_server.can_use())
        no_server.set_base_url("http://x")
        self.assertTrue(no_server.can_use())


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class PollerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.server = FakeContourServer()
        self.client = _client(self.server)
        self.job_id = self.client.create_job("предел", 8)["job_id"]

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "поллер не дождался")
            self.app.processEvents()
            time.sleep(0.01)

    def test_polls_until_settled(self):
        from ui.contour_poller import ContourJobPoller
        updates, settled = [], []
        poller = ContourJobPoller(self.client, interval_ms=30)
        poller.job_updated.connect(updates.append)
        poller.settled.connect(settled.append)
        poller.start(self.job_id)

        self._spin(lambda: len(updates) >= 1)
        self.server.jobs[self.job_id]["status"] = RUNNING
        self._spin(lambda: any(u["status"] == RUNNING for u in updates))
        self.server.jobs[self.job_id]["status"] = AWAITING_HUMAN
        self._spin(lambda: settled)

        self.assertEqual(settled[0]["status"], AWAITING_HUMAN)
        self.assertFalse(poller.is_active(), "поллер остановился на settled")

    def test_poll_error_not_terminal(self):
        from ui.contour_poller import ContourJobPoller
        errors, settled = [], []
        poller = ContourJobPoller(self.client, interval_ms=30)
        poller.poll_error.connect(errors.append)
        poller.settled.connect(settled.append)
        self.server.fail_next = True
        poller.start(self.job_id)

        self._spin(lambda: errors)
        self.assertTrue(poller.is_active(), "обрыв сети не остановил поллинг")
        self.server.jobs[self.job_id]["status"] = AWAITING_HUMAN
        self._spin(lambda: settled)
        self.assertEqual(settled[0]["status"], AWAITING_HUMAN)

    def test_stop_prevents_further_signals(self):
        from ui.contour_poller import ContourJobPoller
        updates = []
        poller = ContourJobPoller(self.client, interval_ms=30)
        poller.job_updated.connect(updates.append)
        poller.start(self.job_id)
        self._spin(lambda: updates)
        poller.stop()
        n = len(updates)
        for _ in range(20):
            self.app.processEvents()
            time.sleep(0.01)
        self.assertEqual(len(updates), n, "после stop сигналов нет")


if __name__ == "__main__":
    unittest.main()
