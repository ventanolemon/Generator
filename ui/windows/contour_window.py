"""
ContourWindow — мастер генерации через LLM-контур (C2 плана
docs/ui_rework_plan.md), окно «Генератор через ИИ».

Три стадии в QStackedWidget:

  1. Форма    — предмет + описание задания + тип; «Отправить» ставит джобу
                (ContourClient.create_job) в фоновом QThread.
  2. Ожидание — петля живёт на сервере минуты (S1–S5: сборка графа, пробы,
                критик); окно поллит статус неблокирующим ContourJobPoller
                и показывает индикатор. «Отменить наблюдение» лишь снимает
                поллинг — джоба продолжает выполняться на сервере.
  3. Решение  — статус вышел из queued/running:
                * awaiting_human — карточки превью (условие + ответ по
                  разным сидам), warn-флаги, вердикт критика; человек
                  утверждает (approve → сервер создаёт партицию, окно
                  эмитит partition_created) или отклоняет с причиной;
                * failed — текст ошибки и возврат к форме;
                * approved/rejected — информационная строка (джоба уже
                  решена где-то ещё).

Все HTTP-вызовы блокирующие, поэтому уводятся в _CallWorker (QThread,
паттерн _SyncWorker из sync_window.py); поллинг — только через
ContourJobPoller. Окно немодальное, живёт синглтоном у владельца
(как SyncWindow), публичный refresh() дёшев и идемпотентен.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.contour import ContourError
from core.contour.client import (
    APPROVED, AWAITING_HUMAN, FAILED, QUEUED, REJECTED, RUNNING,
)
from ui.app_context import AppContext
from ui.contour_poller import POLL_INTERVAL_MS, ContourJobPoller

# Индексы стадий в QStackedWidget.
STAGE_FORM = 0
STAGE_WAITING = 1
STAGE_DECISION = 2
STAGE_DISABLED = 3

# Человекочитаемые статусы активной джобы (стадия «Ожидание»).
_STATUS_LINES = {
    QUEUED: "в очереди на сервере…",
    RUNNING: "петля работает: сборка графа, пробы, критик…",
}

# Варианты типа задания: подпись → значение constraints["task_type"]
# (None = «авто», ограничение не передаётся — сервер решает сам).
_TASK_TYPES = (("авто", None), ("статическое", "static"),
               ("интерактивное", "interactive"))


class _CallWorker(QThread):
    """Один блокирующий вызов ContourClient в фоне (как _SyncWorker в B3).

    Результат/ошибка уходят сигналами — Qt доставит их в UI-поток через
    очередь событий, виджеты из воркера не трогаются.
    """

    done = pyqtSignal(object)   # dict-ответ сервера
    failed = pyqtSignal(str)    # текст ContourError / прочего сбоя

    def __init__(self, fn: Callable[[], dict], parent: QWidget | None = None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn())
        except ContourError as e:
            self.failed.emit(str(e))
        except Exception as e:  # страховка: любой сбой — сигналом, не крэшем
            self.failed.emit(f"контур: {e}")


class ContourWindow(QWidget):
    """Окно «Генератор через ИИ»: форма → поллинг → превью → approve/reject."""

    # Сервер создал партицию по approve — владелец (generator_window)
    # подключает к обновлению списка разделов.
    partition_created = pyqtSignal(int)

    def __init__(self, context: AppContext, parent: QWidget | None = None,
                 *, poll_interval_ms: int = POLL_INTERVAL_MS):
        super().__init__(parent)
        # Отдельное top-level окно даже при заданном parent (немодальный
        # синглтон, как SyncWindow): parent держит время жизни.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = context.contour_client
        self._worker: Optional[_CallWorker] = None
        self._job_id: str = ""
        self._job_description: str = ""

        self.poller: Optional[ContourJobPoller] = None
        if self.client is not None:
            self.poller = ContourJobPoller(self.client, parent=self,
                                           interval_ms=poll_interval_ms)
            self.poller.job_updated.connect(self._on_job_updated)
            self.poller.settled.connect(self._on_settled)
            self.poller.poll_error.connect(self._on_poll_error)

        self.setWindowTitle("Генератор через ИИ")
        self.resize(680, 640)
        self._build_ui()
        self.refresh()

    # ---------- сборка ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("Генератор через ИИ", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self._build_form_page())      # STAGE_FORM
        self.stack.addWidget(self._build_waiting_page())   # STAGE_WAITING
        self.stack.addWidget(self._build_decision_page())  # STAGE_DECISION
        self.stack.addWidget(self._build_disabled_page())  # STAGE_DISABLED
        root.addWidget(self.stack, stretch=1)

    def _build_form_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        intro = QLabel(
            "Опишите задание — сервер соберёт генератор, проверит его "
            "на пробных сидах, покажет вердикт критика и превью. "
            "Партиция появится только после вашего утверждения.", page)
        intro.setProperty("class", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        # Подтверждение отклонения предыдущей заявки (скрыто по умолчанию).
        self.form_info_label = QLabel("", page)
        self.form_info_label.setProperty("class", "muted")
        self.form_info_label.setWordWrap(True)
        self.form_info_label.hide()
        lay.addWidget(self.form_info_label)

        row = QHBoxLayout()
        subj_cap = QLabel("Предмет:", page)
        subj_cap.setProperty("class", "muted")
        row.addWidget(subj_cap)
        self.subject_combo = QComboBox(page)
        self.subject_combo.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Fixed)
        row.addWidget(self.subject_combo, stretch=1)
        type_cap = QLabel("Тип задания:", page)
        type_cap.setProperty("class", "muted")
        row.addWidget(type_cap)
        self.task_type_combo = QComboBox(page)
        for label, value in _TASK_TYPES:
            self.task_type_combo.addItem(label, value)
        row.addWidget(self.task_type_combo)
        lay.addLayout(row)

        desc_cap = QLabel("Описание задания:", page)
        desc_cap.setProperty("class", "muted")
        lay.addWidget(desc_cap)
        self.description_edit = QPlainTextEdit(page)
        self.description_edit.setPlaceholderText(
            "Опишите задание: тема, что дано, что нужно найти, диапазоны "
            "сложности…\nНапример: «Предел рациональной дроби при x→a с "
            "устранимой особенностью; коэффициенты — целые от −9 до 9».")
        lay.addWidget(self.description_edit, stretch=1)

        # Ошибка постановки джобы (ContourError create_job).
        self.form_error_label = QLabel("", page)
        self.form_error_label.setProperty("class", "danger")
        self.form_error_label.setWordWrap(True)
        self.form_error_label.hide()
        lay.addWidget(self.form_error_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.submit_btn = QPushButton("Отправить", page)
        self.submit_btn.clicked.connect(self._on_submit)
        buttons.addWidget(self.submit_btn)
        lay.addLayout(buttons)
        return page

    def _build_waiting_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        head = QLabel("Петля запущена", page)
        head.setProperty("class", "subtitle")
        lay.addWidget(head)

        card = QFrame(page)
        card.setProperty("class", "card")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(12, 10, 12, 10)
        self.waiting_description_label = QLabel("", card)
        self.waiting_description_label.setProperty("class", "muted")
        self.waiting_description_label.setWordWrap(True)
        card_lay.addWidget(self.waiting_description_label)
        lay.addWidget(card)

        self.waiting_status_label = QLabel("", page)
        self.waiting_status_label.setProperty("class", "accent")
        self.waiting_status_label.setWordWrap(True)
        lay.addWidget(self.waiting_status_label)

        self.waiting_progress = QProgressBar(page)
        self.waiting_progress.setRange(0, 0)  # индетерминированный
        self.waiting_progress.setTextVisible(False)
        lay.addWidget(self.waiting_progress)

        # Обрыв сети при опросе — не терминален, поллинг продолжается.
        self.poll_error_label = QLabel("", page)
        self.poll_error_label.setProperty("class", "muted")
        self.poll_error_label.setWordWrap(True)
        self.poll_error_label.hide()
        lay.addWidget(self.poll_error_label)

        lay.addStretch(1)
        buttons = QHBoxLayout()
        self.cancel_watch_btn = QPushButton("Отменить наблюдение", page)
        self.cancel_watch_btn.setToolTip(
            "Перестать следить за джобой в этом окне. Сама джоба продолжит "
            "выполняться на сервере — результат можно будет утвердить позже.")
        self.cancel_watch_btn.clicked.connect(self._on_cancel_watch)
        buttons.addWidget(self.cancel_watch_btn)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        return page

    def _build_decision_page(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        self._decision_host = QWidget(scroll)
        self.decision_layout = QVBoxLayout(self._decision_host)
        self.decision_layout.setSpacing(8)
        self.decision_layout.addStretch(1)
        scroll.setWidget(self._decision_host)
        return scroll

    def _build_disabled_page(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.addStretch(1)
        self.disabled_label = QLabel("", page)
        self.disabled_label.setProperty("class", "muted")
        self.disabled_label.setWordWrap(True)
        self.disabled_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.disabled_label)
        lay.addStretch(2)
        return page

    # ---------- публичное обновление ----------

    def refresh(self) -> None:
        """Пересчитать доступность контура и список предметов.

        Дёшево (одна проверка can_use + один SELECT предметов) и
        идемпотентно: не сбрасывает текущую стадию и выбор пользователя.
        """
        if self.client is None or not self.client.can_use():
            self.disabled_label.setText(self._disabled_reason())
            self.stack.setCurrentIndex(STAGE_DISABLED)
            return
        self._reload_subjects()
        # Контур стал доступен (настроили сервер/сменили роль) — с заглушки
        # возвращаемся на форму; активные стадии не трогаем.
        if self.stack.currentIndex() == STAGE_DISABLED:
            self.stack.setCurrentIndex(STAGE_FORM)

    def _disabled_reason(self) -> str:
        if self.client is None or not self.client.has_server():
            return ("Генерация через ИИ недоступна: адрес сервера не задан.\n"
                    "Укажите его в Настройках (вкладка «Соединение»).")
        return ("Генерация через ИИ доступна преподавателям и "
                "администраторам.\nВаша текущая роль — студент.")

    def _reload_subjects(self) -> None:
        current = self.subject_combo.currentData()
        subjects = self.ctx.repo.list_subjects()
        self.subject_combo.blockSignals(True)
        self.subject_combo.clear()
        for s in subjects:
            self.subject_combo.addItem(s.name, s.id)
        if current is not None:
            idx = self.subject_combo.findData(current)
            if idx >= 0:
                self.subject_combo.setCurrentIndex(idx)
        self.subject_combo.blockSignals(False)

    # ---------- стадия 1: форма ----------

    def _on_submit(self) -> None:
        if self._worker is not None or self.client is None:
            return
        description = self.description_edit.toPlainText().strip()
        subject_id = self.subject_combo.currentData()
        if not description:
            self._show_form_error(
                "Опишите задание — без описания петле не с чем работать.")
            return
        if subject_id is None:
            self._show_form_error(
                "Нет предметов — создайте предмет в главном окне.")
            return
        task_type = self.task_type_combo.currentData()
        constraints = {"task_type": task_type} if task_type else None

        self.form_error_label.hide()
        self.form_info_label.hide()
        self.submit_btn.setEnabled(False)
        self._job_description = description
        self._start_call(
            lambda: self.client.create_job(description, int(subject_id),
                                           constraints),
            self._on_job_created, self._on_create_failed)

    def _on_job_created(self, resp: dict) -> None:
        self.submit_btn.setEnabled(True)
        self._job_id = str(resp.get("job_id", ""))
        self.waiting_description_label.setText(self._job_description)
        self.waiting_status_label.setText(
            _STATUS_LINES.get(str(resp.get("status", QUEUED)),
                              _STATUS_LINES[QUEUED]))
        self.poll_error_label.hide()
        self.stack.setCurrentIndex(STAGE_WAITING)
        if self.poller is not None:
            self.poller.start(self._job_id)

    def _on_create_failed(self, message: str) -> None:
        self.submit_btn.setEnabled(True)
        self._show_form_error(f"Не удалось поставить джобу: {message}")

    def _show_form_error(self, text: str) -> None:
        self.form_error_label.setText(text)
        self.form_error_label.show()

    # ---------- стадия 2: ожидание (поллинг) ----------

    def _on_job_updated(self, job: dict) -> None:
        status = str(job.get("status", ""))
        if status in _STATUS_LINES:
            self.waiting_status_label.setText(_STATUS_LINES[status])
        self.poll_error_label.hide()

    def _on_poll_error(self, message: str) -> None:
        self.poll_error_label.setText(
            f"Сбой опроса: {message} — продолжаем следить.")
        self.poll_error_label.show()

    def _on_cancel_watch(self) -> None:
        if self.poller is not None:
            self.poller.stop()
        self._show_form_note(
            "Наблюдение снято. Джоба продолжает выполняться на сервере.")

    def _on_settled(self, job: dict) -> None:
        self._show_decision(job)

    # ---------- стадия 3: решение ----------

    def _show_decision(self, job: dict) -> None:
        self._clear_decision()
        status = str(job.get("status", ""))
        if status == AWAITING_HUMAN:
            self._build_approval_ui(job)
        elif status == FAILED:
            self._build_failed_ui(job)
        else:  # approved/rejected — решено где-то ещё (другой клиент/админ)
            verdict = ("уже утверждена" if status == APPROVED
                       else "уже отклонена" if status == REJECTED
                       else f"в статусе «{status}»")
            note = QLabel(f"Эта джоба {verdict} — делать здесь нечего.",
                          self._decision_host)
            note.setProperty("class", "muted")
            note.setWordWrap(True)
            self._add_decision(note)
            self._add_restart_button()
        self.stack.setCurrentIndex(STAGE_DECISION)

    def _build_approval_ui(self, job: dict) -> None:
        head = QLabel("Приёмка задания", self._decision_host)
        head.setProperty("class", "subtitle")
        self._add_decision(head)

        flags = [str(f) for f in (job.get("flags") or [])]
        critic = job.get("critic") or {}

        # --- Шапка-карточка: описание + чип типа + статус-пилюля S6 ---
        header_card, hlay = self._decision_card()
        description = str(job.get("description") or self._job_description)
        desc_label = QLabel(description, header_card)
        desc_label.setWordWrap(True)
        hlay.addWidget(desc_label)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        task_type = (job.get("constraints") or {}).get("task_type")
        type_label = {"static": "статическое",
                      "interactive": "интерактивное"}.get(task_type, "задание")
        chips.addWidget(self._chip(type_label, "chip", header_card))
        chips.addWidget(self._chip("на утверждении · S6", "badge", header_card))
        chips.addStretch(1)
        hlay.addLayout(chips)
        self._add_decision(header_card)

        # --- Карточка критика: вердикт-бейдж + метр уверенности + текст ---
        summary = str(critic.get("summary", "")).strip()
        confidence = critic.get("confidence")
        if summary or confidence is not None or flags:
            critic_card, clay = self._decision_card()
            vrow = QHBoxLayout()
            vrow.setSpacing(8)
            vrow.addWidget(self._verdict_badge(critic, flags, critic_card))
            title = QLabel("Критик", critic_card)
            title.setProperty("class", "accent")
            vrow.addWidget(title)
            vrow.addStretch(1)
            clay.addLayout(vrow)

            if confidence is not None:
                meter = QProgressBar(critic_card)
                meter.setRange(0, 100)
                try:
                    meter.setValue(int(round(float(confidence) * 100)))
                except (TypeError, ValueError):
                    meter.setValue(0)
                meter.setFormat("уверенность %p%")
                clay.addWidget(meter)

            # Текстовая строка критика — несёт «Критик:» и сырую уверенность
            # (инвариант: сводка критика читается и без визуального метра).
            if summary or confidence is not None:
                conf_txt = "" if confidence is None \
                    else f" (уверенность {confidence})"
                critic_label = QLabel(
                    (f"Критик: {summary}" if summary else "Критик:") + conf_txt,
                    critic_card)
                critic_label.setProperty("class", "muted")
                critic_label.setWordWrap(True)
                clay.addWidget(critic_label)

            # warn-флаги проб — не блокируют приёмку.
            if flags:
                flags_cap = QLabel(
                    "Предупреждения проб — не блокируют приёмку:", critic_card)
                flags_cap.setProperty("class", "muted")
                clay.addWidget(flags_cap)
                frow = QHBoxLayout()
                frow.setSpacing(6)
                for flag in flags:
                    chip = QLabel(flag, critic_card)
                    chip.setProperty("class", "badge-warn")
                    chip.setWordWrap(True)
                    frow.addWidget(chip)
                frow.addStretch(1)
                clay.addLayout(frow)
            self._add_decision(critic_card)

        # --- Превью заданий (разные seed) ---
        previews = job.get("previews") or []
        if previews:
            pv_head = QLabel("Примеры заданий (разные seed)",
                             self._decision_host)
            pv_head.setProperty("class", "muted")
            self._add_decision(pv_head)
            for preview in previews:
                self._add_decision(self._make_preview_card(preview))

        # --- Раунды контура (компактный таймлайн) ---
        rounds = job.get("rounds") or []
        if rounds:
            self._add_decision(self._make_rounds_card(rounds))

        # --- Имя партиции + действия ---
        name_row = QHBoxLayout()
        name_cap = QLabel("Название партиции:", self._decision_host)
        name_cap.setProperty("class", "muted")
        name_row.addWidget(name_cap)
        self.partition_name_edit = QLineEdit(description[:80],
                                             self._decision_host)
        name_row.addWidget(self.partition_name_edit, stretch=1)
        self._add_decision_layout(name_row)

        self.decision_error_label = QLabel("", self._decision_host)
        self.decision_error_label.setProperty("class", "danger")
        self.decision_error_label.setWordWrap(True)
        self.decision_error_label.hide()
        self._add_decision(self.decision_error_label)

        buttons = QHBoxLayout()
        self.approve_btn = QPushButton("Принять задание", self._decision_host)
        self.approve_btn.setProperty("class", "primary")
        self.approve_btn.clicked.connect(self._on_approve)
        buttons.addWidget(self.approve_btn)
        self.reject_btn = QPushButton("Отклонить", self._decision_host)
        self.reject_btn.setProperty("class", "danger")
        self.reject_btn.clicked.connect(self._on_reject_clicked)
        buttons.addWidget(self.reject_btn)
        buttons.addStretch(1)
        self._add_decision_layout(buttons)

        # Причина отклонения — раскрывается по «Отклонить».
        self._reject_row = QWidget(self._decision_host)
        reject_lay = QHBoxLayout(self._reject_row)
        reject_lay.setContentsMargins(0, 0, 0, 0)
        reason_cap = QLabel("Причина:", self._reject_row)
        reason_cap.setProperty("class", "muted")
        reject_lay.addWidget(reason_cap)
        self.reject_reason_edit = QLineEdit(self._reject_row)
        self.reject_reason_edit.setPlaceholderText(
            "что не так — уйдёт в лог петли")
        reject_lay.addWidget(self.reject_reason_edit, stretch=1)
        self.reject_confirm_btn = QPushButton("Подтвердить отклонение",
                                              self._reject_row)
        self.reject_confirm_btn.clicked.connect(self._on_reject_confirm)
        reject_lay.addWidget(self.reject_confirm_btn)
        self._reject_row.hide()
        self._add_decision(self._reject_row)

    # --- визуальные помощники экрана приёмки ---

    def _decision_card(self):
        """Карточка (QFrame class=card) с вертикальным лейаутом."""
        card = QFrame(self._decision_host)
        card.setProperty("class", "card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        return card, lay

    def _chip(self, text: str, cls: str, parent: QWidget) -> QLabel:
        lbl = QLabel(text, parent)
        lbl.setProperty("class", cls)
        return lbl

    def _verdict_badge(self, critic: dict, flags: list,
                       parent: QWidget) -> QLabel:
        """Бейдж вердикта критика. НЕ использует badge-warn (та зарезервирована
        под флаги проб): принять — badge-ok, отклонить — badge-error,
        доработать/с замечаниями — нейтральный chip."""
        verdict = str(critic.get("verdict", "")).strip().lower()
        if verdict in ("reject", "отклонить"):
            text, cls = "отклонить", "badge-error"
        elif verdict in ("revise", "repair", "доработать"):
            text, cls = "доработать", "chip"
        elif verdict in ("accept", "pass", "принять"):
            text, cls = "принять", "badge-ok"
        else:  # явного вердикта нет: с флагами — «с замечаниями», иначе «принять»
            text, cls = ("с замечаниями", "chip") if flags \
                else ("принять", "badge-ok")
        return self._chip(text, cls, parent)

    def _make_rounds_card(self, rounds: list) -> QFrame:
        card, lay = self._decision_card()
        cap = QLabel("Раунды контура", card)
        cap.setProperty("class", "muted")
        lay.addWidget(cap)
        for i, rnd in enumerate(rounds, 1):
            stage = str(rnd.get("stage") or rnd.get("kind") or "раунд")
            verdict = str(rnd.get("verdict") or "").strip()
            line = QLabel(f"{i}. {stage}" + (f" — {verdict}" if verdict else ""),
                          card)
            vl = verdict.lower()
            cls = ("accent" if vl in ("accept", "pass") else
                   "danger" if vl == "reject" else "muted")
            line.setProperty("class", cls)
            lay.addWidget(line)
        return card

    def _make_preview_card(self, preview: dict) -> QFrame:
        card = QFrame(self._decision_host)
        card.setProperty("class", "card")
        card.setProperty("preview_seed", preview.get("seed"))  # для тестов
        lay = QVBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        seed = QLabel(f"проба, seed {preview.get('seed', '—')}", card)
        seed.setProperty("class", "muted")
        lay.addWidget(seed)
        statement = QLabel(str(preview.get("statement", "")), card)
        statement.setWordWrap(True)
        lay.addWidget(statement)
        answer = QLabel(f"Ответ: {preview.get('answer', '')}", card)
        answer.setProperty("class", "accent")
        answer.setWordWrap(True)
        lay.addWidget(answer)
        return card

    def _build_failed_ui(self, job: dict) -> None:
        reason = str(job.get("error") or "причина неизвестна")
        error = QLabel(f"Петля завершилась с ошибкой: {reason}",
                       self._decision_host)
        error.setProperty("class", "danger")
        error.setWordWrap(True)
        self._add_decision(error)
        self._add_restart_button()

    def _add_restart_button(self) -> None:
        row = QHBoxLayout()
        self.restart_btn = QPushButton("Начать заново", self._decision_host)
        self.restart_btn.clicked.connect(lambda: self._show_form_note(""))
        row.addWidget(self.restart_btn)
        row.addStretch(1)
        self._add_decision_layout(row)

    # --- approve / reject ---

    def _on_approve(self) -> None:
        if self._worker is not None or self.client is None:
            return
        name = self.partition_name_edit.text().strip()
        job_id = self._job_id
        self._set_decision_busy(True)
        self.decision_error_label.hide()
        self._start_call(
            lambda: self.client.approve(job_id, partition_name=name),
            self._on_approved, self._on_decision_failed)

    def _on_approved(self, resp: dict) -> None:
        partition_id = int(resp.get("partition_id") or 0)
        self.partition_created.emit(partition_id)
        self._clear_decision()
        ok = QLabel(f"Партиция создана (id {partition_id}) — она появится "
                    "в списке разделов главного окна.", self._decision_host)
        ok.setProperty("class", "accent")
        ok.setWordWrap(True)
        self._add_decision(ok)
        self._add_restart_button()

    def _on_reject_clicked(self) -> None:
        self._reject_row.show()
        self.reject_reason_edit.setFocus()

    def _on_reject_confirm(self) -> None:
        if self._worker is not None or self.client is None:
            return
        reason = self.reject_reason_edit.text().strip()
        if not reason:
            self.decision_error_label.setText(
                "Укажите причину отклонения — она уйдёт в лог петли.")
            self.decision_error_label.show()
            return
        job_id = self._job_id
        self._set_decision_busy(True)
        self.decision_error_label.hide()
        self._start_call(lambda: self.client.reject(job_id, reason),
                         self._on_rejected, self._on_decision_failed)

    def _on_rejected(self, resp: dict) -> None:
        self._show_form_note("Заявка отклонена — можно составить новую.")

    def _on_decision_failed(self, message: str) -> None:
        self._set_decision_busy(False)
        self.decision_error_label.setText(message)
        self.decision_error_label.show()

    def _set_decision_busy(self, busy: bool) -> None:
        for btn in (self.approve_btn, self.reject_btn,
                    self.reject_confirm_btn):
            btn.setEnabled(not busy)

    # ---------- переходы и утилиты ----------

    def _show_form_note(self, note: str) -> None:
        """Вернуться на форму, опционально показав muted-подтверждение."""
        if note:
            self.form_info_label.setText(note)
            self.form_info_label.show()
        else:
            self.form_info_label.hide()
        self.form_error_label.hide()
        self.stack.setCurrentIndex(STAGE_FORM)

    def _clear_decision(self) -> None:
        # Снести всё, кроме финальной растяжки. setParent(None) отвязывает
        # виджет немедленно (иначе он «мигает» до deleteLater).
        while self.decision_layout.count() > 1:
            item = self.decision_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif item.layout() is not None:
                _drain_layout(item.layout())

    def _add_decision(self, widget: QWidget) -> None:
        self.decision_layout.insertWidget(self.decision_layout.count() - 1,
                                          widget)

    def _add_decision_layout(self, layout) -> None:
        self.decision_layout.insertLayout(self.decision_layout.count() - 1,
                                          layout)

    def _start_call(self, fn: Callable[[], dict],
                    on_done: Callable[[dict], None],
                    on_failed: Callable[[str], None]) -> None:
        self._worker = _CallWorker(fn, self)
        self._worker.done.connect(on_done)
        self._worker.failed.connect(on_failed)
        self._worker.finished.connect(self._release_worker)
        self._worker.start()

    def _release_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None


def _drain_layout(layout) -> None:
    """Рекурсивно снести вложенный лейаут с его виджетами."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            _drain_layout(item.layout())
    layout.deleteLater()
