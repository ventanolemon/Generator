"""
InteractiveTaskView — представление для интерактивных заданий-сессий.

Цикл: показать prompt → дождаться ввода → submit → показать feedback и next_prompt.
Подходит для тренажёров (например, английских слов).
"""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QScrollArea, QLabel, QCheckBox
)

from core import Capability, InteractiveTask, TaskGenerator
from ui.utils import render_blocks, clear_layout


class InteractiveTaskView(QWidget):
    """Сессия 'спроси-ответь' с историей ходов."""

    def __init__(self, generator: TaskGenerator, parent: QWidget | None = None):
        super().__init__(parent)
        if Capability.INTERACTIVE not in generator.capabilities:
            raise ValueError(
                f"InteractiveTaskView требует INTERACTIVE, "
                f"у {generator.name!r} его нет."
            )
        self.generator = generator
        self.task: InteractiveTask | None = None
        self.score_correct = 0
        self.score_total = 0
        self._build_ui()
        self._start_session()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        title = QLabel(self.generator.name, self)
        title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(title)

        # Строка со счётом и (если поддерживается) переключателем мягкой проверки
        status_row = QHBoxLayout()
        self.score_label = QLabel("", self)
        status_row.addWidget(self.score_label)
        status_row.addStretch()

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
            status_row.addWidget(self.tolerant_chk)
        root.addLayout(status_row)

        # История ходов
        self.history_scroll = QScrollArea(self)
        self.history_scroll.setWidgetResizable(True)
        self.history_holder = QWidget(self.history_scroll)
        self.history_layout = QVBoxLayout(self.history_holder)
        self.history_scroll.setWidget(self.history_holder)
        root.addWidget(self.history_scroll, stretch=1)

        # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
        # Подключаем автоматическую прокрутку вниз при любом изменении высоты контента
        v_scrollbar = self.history_scroll.verticalScrollBar()
        v_scrollbar.rangeChanged.connect(
            lambda min_val, max_val: v_scrollbar.setValue(max_val)
        )
        # -------------------------

        # Текущий промпт
        self.prompt_holder = QWidget(self)
        self.prompt_layout = QVBoxLayout(self.prompt_holder)
        self.prompt_layout.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self.prompt_holder)

        # Поле ввода
        input_row = QHBoxLayout()
        self.input_field = QLineEdit(self)
        self.submit_btn = QPushButton("Ответить", self)
        self.restart_btn = QPushButton("Заново", self)
        input_row.addWidget(self.input_field, stretch=1)
        input_row.addWidget(self.submit_btn)
        input_row.addWidget(self.restart_btn)
        root.addLayout(input_row)

        self.submit_btn.clicked.connect(self._on_submit)
        self.input_field.returnPressed.connect(self._on_submit)
        self.restart_btn.clicked.connect(self._start_session)

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
        self.input_field.setEnabled(True)
        self.submit_btn.setEnabled(True)
        self.input_field.setFocus()

    def _on_submit(self) -> None:
        if self.task is None:
            return
        text = self.input_field.text().strip()
        if not text:
            return
        result = self.task.submit(text)
        # Просто добавляем feedback. Сам блок (например, WordCorrectionBlock)
        # уже содержит и условие, и ответ пользователя, и правильный ответ —
        # дублировать вручную не надо.
        self._append_history(result.feedback)

        self.score_total += 1
        if result.correct:
            self.score_correct += 1
        self._update_score()
        self.input_field.clear()

        if result.next_prompt is not None:
            self._show_prompt(result.next_prompt)
        else:
            self._show_finish()

    def _show_prompt(self, blocks) -> None:
        clear_layout(self.prompt_layout)
        widget = render_blocks(blocks, self.prompt_holder)
        self.prompt_layout.addWidget(widget)

    def _append_history(self, blocks) -> None:
        widget = render_blocks(blocks, self.history_holder)
        self.history_layout.addWidget(widget)
        # Автоскролл вниз обрабатывается через сигнал rangeChanged в _build_ui

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
        msg.setStyleSheet("font-weight: bold; color: #2a5a8a;")
        self.prompt_layout.addWidget(msg)
        self.input_field.setEnabled(False)
        self.submit_btn.setEnabled(False)