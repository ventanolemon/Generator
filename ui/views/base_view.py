"""
BaseTaskView — общий каркас представлений заданий (контракт K4 плана
docs/ui_rework_plan.md, владелец Fable).

Все 4 view (static/table/interactive/test) делят одну и ту же обвязку:
заголовок с именем генератора, строка управляющих кнопок, центральная зона.
Рендер содержимого и так общий (render_blocks / Block.render_qt из ui/utils) —
здесь консолидируется только хром.

Шаблонный метод:

    __init__(generator, parent)          # сигнатура всех view — стабильна
      ├─ проверка REQUIRED_CAPABILITY    # сообщение — _capability_error()
      ├─ _init_state()                   # хук: состояние до постройки UI
      ├─ _build_chrome()                 # заголовок + build_controls + build_center
      └─ _post_init()                    # хук: действия после постройки UI

Хуки подклассов:

    build_controls(row)   — наполнить строку кнопок (свой addStretch — сами);
    build_center(root)    — центральная зона; по умолчанию — прокручиваемый
                            контейнер блоков (scroll/content_holder/
                            content_layout) + show_blocks()/refresh_body();
    build_body()          — Iterable[Block] для дефолтной центральной зоны
                            (это и есть точка входа превью мастера контура C2).
"""

from __future__ import annotations

from typing import Iterable

from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from core import Block, Capability, TaskGenerator
from ui.utils import clear_layout, render_blocks


class BaseTaskView(QWidget):
    """Каркас: заголовок + строка контролов + центральная зона."""

    #: Какой Capability обязан быть у генератора (None — не проверять).
    REQUIRED_CAPABILITY: Capability | None = None

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        cap = self.REQUIRED_CAPABILITY
        if cap is not None and cap not in generator.capabilities:
            raise ValueError(self._capability_error(generator))
        self.generator = generator
        self._init_state()
        self._build_chrome()
        self._post_init()

    # ---------- шаблонный метод ----------

    def _capability_error(self, generator: TaskGenerator) -> str:
        """Текст ошибки несовместимого генератора (подклассы могут уточнить)."""
        return (
            f"{type(self).__name__} требует {self.REQUIRED_CAPABILITY.name}, "
            f"у {generator.name!r} его нет."
        )

    def _init_state(self) -> None:
        """Хук: инициализация состояния до постройки UI."""

    def _post_init(self) -> None:
        """Хук: действия после постройки UI (например, старт сессии)."""

    def _build_chrome(self) -> None:
        root = QVBoxLayout(self)

        self.title_label = QLabel(self.generator.name, self)
        self.title_label.setProperty("class", "title")
        root.addWidget(self.title_label)

        controls = QHBoxLayout()
        self.build_controls(controls)
        root.addLayout(controls)

        self.build_center(root)

    # ---------- хуки ----------

    def build_controls(self, row: QHBoxLayout) -> None:
        """Наполнить строку контролов (кнопки, чекбоксы, свой addStretch)."""

    def build_center(self, root: QVBoxLayout) -> None:
        """
        Центральная зона. По умолчанию — прокручиваемый контейнер блоков:
        подклассу достаточно звать show_blocks(...) или переопределить
        build_body() и звать refresh_body().
        """
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.content_holder = QWidget(self.scroll)
        self.content_layout = QVBoxLayout(self.content_holder)
        self.scroll.setWidget(self.content_holder)
        root.addWidget(self.scroll, stretch=1)

    def build_body(self) -> Iterable[Block]:
        """Блоки для дефолтной центральной зоны (см. refresh_body)."""
        return ()

    # ---------- сервис дефолтной центральной зоны ----------

    def refresh_body(self) -> None:
        """Перерисовать дефолтную центральную зону из build_body()."""
        self.show_blocks(list(self.build_body()))

    def show_blocks(self, blocks: Iterable[Block]) -> None:
        """Показать список блоков в прокручиваемом контейнере."""
        clear_layout(self.content_layout)
        self.content_layout.addWidget(render_blocks(blocks, self.content_holder))

    # ---------- статистика попыток (outbox синка) ----------

    def attach_stats(self, *, partition_id: int | None, sync_client) -> None:
        """
        Подключить контекст для записи попыток решения. Вызывается владельцем
        (GeneratorWindow) сразу после конструктора — не часть стабильного
        контракта __init__(generator, parent) (K4), чтобы не плодить
        параметры у всех view ради того, что реально использует только один
        подкласс (InteractiveTaskView — единственный, где вообще есть
        понятие «правильно/неправильно» на текущий момент).
        """
        self._stats_partition_id = partition_id
        self._stats_sync_client = sync_client

    def queue_attempt(self, payload: dict, *, correct: bool | None) -> None:
        """
        Записать попытку в outbox синхронизации (SyncClient.queue_attempt),
        если attach_stats был вызван. Тихо no-op иначе (учебный режим без
        подключённого контекста — например, headless-тесты) и на любой сбой
        записи — статистика не должна ронять сессию решения задания.
        """
        client = getattr(self, "_stats_sync_client", None)
        partition_id = getattr(self, "_stats_partition_id", None)
        if client is None or partition_id is None:
            return
        try:
            client.queue_attempt(partition_id, payload, correct=correct)
        except Exception:
            pass
