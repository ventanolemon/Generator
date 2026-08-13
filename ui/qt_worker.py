"""
Дисциплина фоновых вызовов Qt: поток не должен принадлежать окну.

Здесь лежит то, что раньше было скопировано в семь мест почти дословно —
и вместе с копиями разъехалось одно и то же падение.

Как падало
----------
Воркер создавался с окном в родителях (`_CallWorker(fn, self)`). Удаление
окна удаляет его детей, в том числе РАБОТАЮЩИЙ QThread, а это
неопределённое поведение: на практике segfault без единого сообщения.
Достаточно закрыть окно (или выйти из программы) с незавершённым
запросом к серверу.

Вторая половина той же беды — ссылка. Колбэк снимал `self._worker = None`,
то есть последнюю ссылку на python-обёртку, ещё до того, как поток
заканчивался.

Как надо
--------
    worker = MyWorker(fn)              # БЕЗ родителя
    run_detached(self, worker,
                 on_done=..., on_failed=...)

`run_detached` берёт на себя всё остальное: держит воркер живым, пока тот
работает, отпускает по `finished` и не пускает колбэк к уже удалённому
окну — ответ на запрос закрытого окна молча отбрасывается, потому что
закрыть окно, не дожидаясь сервера, законное право пользователя.

Модуль намеренно ничего не знает про конкретные окна и клиентов: у
воркеров разная обработка ошибок (`AdminError`, `SyncError`, …), и она
остаётся в них. Общая здесь только ЖИЗНЬ потока.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, QThread


_IN_FLIGHT: set = set()
"""
Воркеры, которые сейчас работают.

Единственное место, которое держит их живыми. Не окно: окно вправе
исчезнуть раньше, чем придёт ответ, и как раз на этом всё и падало.
"""


class _Alive:
    """
    Жив ли ещё виджет, ради которого затевался запрос.

    Спросить об этом само окно нельзя: к моменту ответа его python-обёртка
    указывает на удалённый объект, и любое обращение — либо исключение,
    либо падение. Поэтому признак живёт в отдельном объекте, который окно
    переживает, а гасит его сигнал `destroyed`.
    """

    # `__weakref__` в слотах обязателен: PyQt держит получателя сигнала
    # слабой ссылкой, а на объект без него ссылку не создать.
    __slots__ = ("alive", "__weakref__")

    def __init__(self) -> None:
        self.alive = True

    def mark_dead(self, *_args) -> None:
        self.alive = False


def alive_guard(owner: QObject) -> _Alive:
    """
    Сторож жизни окна — один на окно, заводится при первом обращении.

    Хранится атрибутом самого окна: пока окно живо, его и спрашивают, а
    когда умрёт — сторож останется у тех колбэков, которые его захватили.
    """
    guard = getattr(owner, "_alive_guard", None)
    if guard is None:
        guard = _Alive()
        owner._alive_guard = guard          # type: ignore[attr-defined]
        owner.destroyed.connect(guard.mark_dead)
    return guard


def run_detached(owner: QObject, worker: QThread,
                 on_done: Optional[Callable[[object], None]] = None,
                 on_failed: Optional[Callable[[object], None]] = None,
                 *, done_signal: str = "done",
                 failed_signal: str = "failed") -> QThread:
    """
    Запустить воркер так, чтобы он пережил своего заказчика.

    `worker` обязан быть БЕЗ родителя — иначе смысл теряется: владелец
    снова сможет удалить работающий поток. Проверяется здесь же, потому
    что ошибка эта не видна ни в одном обычном прогоне и всплывает
    падением у пользователя.

    Имена сигналов параметрами, а не жёстко: воркеры разных окон писались
    порознь и называются по-разному, а переименовывать их всем разом ради
    одной функции — менять больше кода, чем чинить.
    """
    if worker.parent() is not None:
        raise ValueError(
            "у фонового воркера не должно быть родителя: удаление "
            "родителя снесёт работающий поток (см. модуль)")

    _IN_FLIGHT.add(worker)
    guard = alive_guard(owner)

    def _retire() -> None:
        _IN_FLIGHT.discard(worker)

    def _guarded(callback):
        # `*args`, а не один аргумент: сигналы воркеров писались порознь и
        # несут кто одно значение, кто пару (результат, ошибка).
        def inner(*args) -> None:
            if not guard.alive or callback is None:
                return
            callback(*args)
        return inner

    for name, callback in ((done_signal, on_done), (failed_signal, on_failed)):
        signal = getattr(worker, name, None)
        # Сигнала может не быть вовсе: у окна обновлений один `done`,
        # который несёт и ошибку. Молча пропускаем, а не требуем от всех
        # воркеров одинаковой формы — переименовывать их разом ради одной
        # функции значило бы менять больше кода, чем чинить.
        if signal is not None:
            signal.connect(_guarded(callback))
    worker.finished.connect(_retire)
    worker.finished.connect(worker.deleteLater)
    worker.start()
    return worker


def in_flight_count() -> int:
    """Сколько воркеров сейчас в полёте. Нужно тестам, а не окнам."""
    return len(_IN_FLIGHT)
