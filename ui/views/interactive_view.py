"""
InteractiveTaskView — представление для интерактивных заданий-сессий.

Цикл: показать prompt → дождаться ввода → submit → показать feedback и next_prompt.
Подходит для тренажёров (например, английских слов).

Хром (заголовок + строка статуса) — из BaseTaskView (контракт K4);
центральная зона своя: история ходов + текущий промпт + способ ввода.

Способ ввода — не всегда поле
-----------------------------
До задания на произношение вводом здесь была одна строка, и другого не
предполагалось. Реестр виджетов (`core.widgets`) заведён ровно для того,
чтобы это перестало быть допущением: спецификация ответа объявляет ВИД,
виджет объявляет, какие виды обслуживает, а платформа связывает имя со
своей реализацией — как блоки связаны с фронтом полем `type`.

Здесь это связывание и происходит: имя `voice_recorder` разворачивается в
`ui.audio_recorder.VoiceRecorder`, остальные имена — в поле ввода.
Неизвестное имя не ошибка: поле ввода обслуживает всё, что печатают, и
показать его лучше, чем отказаться показать вопрос.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QScrollArea, QLabel, QCheckBox, QStackedWidget
)

from core import Capability, InteractiveTask
from ui.utils import render_blocks, clear_layout
from .base_view import BaseTaskView

#: Имя виджета из реестра ядра → реализация на этой платформе.
VOICE_RECORDER = "voice_recorder"


class InteractiveTaskView(BaseTaskView):
    """Сессия 'спроси-ответь' с историей ходов."""

    REQUIRED_CAPABILITY = Capability.INTERACTIVE

    def _init_state(self) -> None:
        self.task: InteractiveTask | None = None
        self.score_correct = 0
        self.score_total = 0
        # Запись голоса строится ЛЕНИВО: она опрашивает устройства ввода,
        # а подавляющее большинство сессий отвечает с клавиатуры.
        self.recorder = None

    def _post_init(self) -> None:
        self._start_session()

    def build_controls(self, row: QHBoxLayout) -> None:
        # Строка со счётом и (если поддерживается) переключателем мягкой проверки
        self.score_label = QLabel("", self)
        row.addWidget(self.score_label)
        row.addStretch()

        self.tolerant_chk: QCheckBox | None = None
        if hasattr(self.generator, "tolerant"):
            self.tolerant_chk = QCheckBox("Толерантная проверка (опечатки)", self)
            self.tolerant_chk.setToolTip(
                "Принимать мелкие опечатки: расстояние Левенштейна "
                "≤ 1 для слов длиной до 6 символов и ≤ 2 для более длинных. "
                "Правильное написание всё равно показывается в обратной связи."
            )
            self.tolerant_chk.setChecked(bool(self.generator.tolerant))
            self.tolerant_chk.toggled.connect(self._on_tolerant_toggled)
            row.addWidget(self.tolerant_chk)

    def build_center(self, root: QVBoxLayout) -> None:
        # История ходов
        self.history_scroll = QScrollArea(self)
        self.history_scroll.setWidgetResizable(True)
        self.history_holder = QWidget(self.history_scroll)
        self.history_layout = QVBoxLayout(self.history_holder)
        self.history_scroll.setWidget(self.history_holder)
        root.addWidget(self.history_scroll, stretch=1)

        # Автоматическая прокрутка вниз при любом изменении высоты контента.
        # Слот — связанный метод на self, а не лямбда, замыкающая локальную
        # переменную v_scrollbar: замыкание держало бы отдельную сильную
        # ссылку на обёртку QScrollBar, которая могла пережить порядок
        # разрушения C++-объектов при деструктуризации виджета/выходе из
        # процесса — обращение к ней тогда падает (сегфолт, не RuntimeError).
        # Связанный метод сам запрашивает scrollbar заново при каждом вызове.
        self.history_scroll.verticalScrollBar().rangeChanged.connect(
            self._autoscroll_history)

        # Текущий промпт
        self.prompt_holder = QWidget(self)
        self.prompt_layout = QVBoxLayout(self.prompt_holder)
        self.prompt_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.prompt_holder)

        # Способ ввода. Стопка, а не одно поле: вид ответа объявляет
        # вопрос, и в одной сессии вопросы бывают разные.
        input_row = QHBoxLayout()
        self.input_stack = QStackedWidget(self)
        self.input_field = QLineEdit(self.input_stack)
        self.input_stack.addWidget(self.input_field)
        self.submit_btn = QPushButton("Ответить", self)
        self.restart_btn = QPushButton("Заново", self)
        input_row.addWidget(self.input_stack, stretch=1)
        input_row.addWidget(self.submit_btn)
        input_row.addWidget(self.restart_btn)
        root.addLayout(input_row)

        self.submit_btn.clicked.connect(self._on_submit)
        self.input_field.returnPressed.connect(self._on_submit)
        self.restart_btn.clicked.connect(self._start_session)

    def _autoscroll_history(self, min_val: int, max_val: int) -> None:
        self.history_scroll.verticalScrollBar().setValue(max_val)

    def _start_session(self) -> None:
        self.task = self.generator.generate()
        if not isinstance(self.task, InteractiveTask):
            raise TypeError(
                f"{self.generator.name!r} вернул не InteractiveTask"
            )
        self.score_correct = 0
        self.score_total = 0
        clear_layout(self.history_layout)
        self._update_score()
        self._show_prompt(self.task.initial_prompt())
        self._set_input_enabled(True)
        self.submit_btn.setEnabled(True)

    def _on_submit(self) -> None:
        if self.task is None:
            return
        text = self._answer()
        if not text:
            return
        result = self.task.submit(text)
        # Просто добавляем feedback. Сам блок (например, WordCorrectionBlock)
        # уже содержит и условие, и ответ пользователя, и правильный ответ —
        # дублировать вручную не надо.
        self._append_history(result.feedback)

        # Попытка — в outbox синка (per-partition статистика; ортогонально
        # словарной WordStatsStore, которую генератор пишет сам себе).
        self.queue_attempt(self._attempt_payload(text), correct=result.correct)

        self.score_total += 1
        if result.correct:
            self.score_correct += 1
        self._update_score()
        self._clear_answer()

        if result.next_prompt is not None:
            self._show_prompt(result.next_prompt)
        else:
            self._show_finish()

    # ---------- Способ ввода ----------

    def _current_widget_name(self) -> str:
        """
        Каким виджетом отвечают на текущий вопрос.

        Спрашиваем сессию, а не генератор: вид ответа принадлежит ВОПРОСУ,
        и в одной сессии он меняется. Сессии без понятия вопроса
        (`WordsSession`) отвечают пустой строкой — им поле ввода.
        """
        current = getattr(self.task, "current", None)
        if current is None:
            return ""
        try:
            question = current()
        except Exception:                       # noqa: BLE001
            return ""
        return question.widget_name() if question is not None else ""

    def _use_recorder(self) -> bool:
        return self.input_stack.currentWidget() is self.recorder \
            and self.recorder is not None

    def _sync_input_control(self) -> None:
        """Поставить в стопку тот способ ввода, которого просит вопрос."""
        if self._current_widget_name() == VOICE_RECORDER:
            if self.recorder is None:
                from ui.audio_recorder import VoiceRecorder
                self.recorder = VoiceRecorder(self.input_stack)
                self.input_stack.addWidget(self.recorder)
            self.input_stack.setCurrentWidget(self.recorder)
            return
        self.input_stack.setCurrentWidget(self.input_field)
        self.input_field.setFocus()

    def _answer(self) -> str:
        """Ответ в том виде, в каком его понимает спецификация."""
        if self._use_recorder():
            return self.recorder.recording_path()
        return self.input_field.text().strip()

    def _clear_answer(self) -> None:
        if self._use_recorder():
            self.recorder.reset()
        else:
            self.input_field.clear()

    def _set_input_enabled(self, enabled: bool) -> None:
        self.input_field.setEnabled(enabled)
        if self.recorder is not None:
            self.recorder.setEnabled(enabled)
        if enabled and not self._use_recorder():
            self.input_field.setFocus()

    def _attempt_payload(self, answer: str) -> dict:
        """
        Что записать в попытку.

        Для напечатанного ответа — он сам. Для записи голоса — НЕ он:
        ответом там служит путь к временному файлу, и он бессмыслен всюду,
        кроме этой машины и этой минуты. Вместо него уезжает то, что
        сессия способна о попытке рассказать; сама запись не сохраняется
        (см. `ui/audio_recorder.py`).
        """
        if not self._use_recorder():
            return {"input": answer}
        describe = getattr(self.task, "attempt_payload", None)
        return describe() if describe is not None else {"input": "voice"}

    def _show_prompt(self, blocks) -> None:
        clear_layout(self.prompt_layout)
        widget = render_blocks(blocks, self.prompt_holder)
        self.prompt_layout.addWidget(widget)
        # ПОСЛЕ показа условия: вопрос уже сменился, и способ ввода
        # выбирается для нового, а не для предыдущего.
        self._sync_input_control()

    def _append_history(self, blocks) -> None:
        widget = render_blocks(blocks, self.history_holder)
        self.history_layout.addWidget(widget)
        # Автоскролл вниз обрабатывается через сигнал rangeChanged в build_center

    def _update_score(self) -> None:
        self.score_label.setText(
            f"Счёт: {self.score_correct} / {self.score_total}"
        )

    def _on_tolerant_toggled(self, checked: bool) -> None:
        """
        Переключение мягкой проверки из GUI. Записываем флаг и в генератор
        (чтобы рестарт сохранил выбор), и в текущую сессию (чтобы применился
        к следующему же ответу без перезапуска).
        """
        if hasattr(self.generator, "tolerant"):
            self.generator.tolerant = checked
        if self.task is not None and hasattr(self.task, "tolerant"):
            self.task.tolerant = checked

    def _show_finish(self) -> None:
        clear_layout(self.prompt_layout)
        msg = QLabel("Сессия завершена. Нажмите «Заново», чтобы начать новую.",
                     self.prompt_holder)
        msg.setProperty("class", "accent")
        self.prompt_layout.addWidget(msg)
        self._set_input_enabled(False)
        self.submit_btn.setEnabled(False)
