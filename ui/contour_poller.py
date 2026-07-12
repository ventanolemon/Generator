"""
ContourJobPoller — неблокирующий поллинг джобы контура (C1 плана
docs/ui_rework_plan.md).

Сервер сознательно не шлёт события (SSE/webhook нет — system_topology §4):
клиент поллит GET /contour/jobs/{id} каждые 2–5 с. Петля живёт минуты,
поэтому сам HTTP-запрос уводится в фоновый QThread, а расписание держит
QTimer в UI-потоке. Мастер генерации (окно C2) просто подключается к
сигналам — сети и потоков он не видит:

    poller = ContourJobPoller(client, parent=self)
    poller.job_updated.connect(...)     # каждый успешный опрос (dict джобы)
    poller.settled.connect(...)         # статус вышел из queued/running
    poller.poll_error.connect(...)      # ошибка сети/HTTP (текст); поллинг
                                        # продолжается — обрыв не терминален
    poller.start(job_id)
    ...
    poller.stop()
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from core.contour import ContourClient, ContourError
from core.contour.client import SETTLED_STATUSES

# Интервал опроса — середина рекомендованного протоколом окна 2–5 с.
POLL_INTERVAL_MS = 3000


class _FetchWorker(QThread):
    """Один GET джобы в фоне: сеть не трогает UI-поток."""

    fetched = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, client: ContourClient, job_id: str,
                 parent: Optional[QObject] = None):
        super().__init__(parent)
        self._client = client
        self._job_id = job_id

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.fetched.emit(self._client.get_job(self._job_id))
        except ContourError as e:
            self.failed.emit(str(e))
        except Exception as e:  # страховка: любой сбой — сигналом, не крэшем
            self.failed.emit(f"контур: {e}")


class ContourJobPoller(QObject):
    """QTimer-поллер одной джобы: тикает, пока статус queued/running."""

    job_updated = pyqtSignal(dict)   # каждый успешный опрос
    settled = pyqtSignal(dict)       # awaiting_human/approved/rejected/failed
    poll_error = pyqtSignal(str)     # ошибка опроса (поллинг продолжается)

    def __init__(self, client: ContourClient,
                 parent: Optional[QObject] = None,
                 interval_ms: int = POLL_INTERVAL_MS):
        super().__init__(parent)
        self._client = client
        self._job_id: Optional[str] = None
        self._worker: Optional[_FetchWorker] = None
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    # ---------- управление ----------

    def start(self, job_id: str) -> None:
        """Начать поллинг джобы (первый опрос — сразу, не через интервал)."""
        self.stop()
        self._job_id = job_id
        self._timer.start()
        self._tick()

    def stop(self) -> None:
        self._timer.stop()
        self._job_id = None
        # Бегущий воркер довершится и молча отбросится (_job_id уже None).

    def is_active(self) -> bool:
        return self._job_id is not None

    # ---------- цикл ----------

    def _tick(self) -> None:
        if self._job_id is None or self._worker is not None:
            return  # нет джобы или предыдущий опрос ещё в полёте
        self._worker = _FetchWorker(self._client, self._job_id, self)
        self._worker.fetched.connect(self._on_fetched)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_done(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _on_fetched(self, job: dict) -> None:
        if self._job_id is None:            # stop() случился в полёте
            return
        self.job_updated.emit(job)
        if str(job.get("status", "")) in SETTLED_STATUSES:
            self.stop()
            self.settled.emit(job)

    def _on_failed(self, message: str) -> None:
        if self._job_id is None:
            return
        # Обрыв сети не терминален: сообщаем и продолжаем тикать.
        self.poll_error.emit(message)
