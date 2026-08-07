"""
AdminWindow — окно «Администрирование» (docs/ui_rework_plan.md, п.4–5).

Четыре вкладки в QTabWidget:

  1. Пользователи и роли — таблица пользователей; роль меняется комбобоксом
     в строке с подтверждением. Серверные guardrail'ы (нельзя менять свою
     роль, нельзя понизить последнего администратора) приходят как 400 и
     показываются строкой-ошибкой; combobox откатывается. Своя строка —
     роль заблокирована, помечена «Это вы».
  2. Группы — мастер-деталь: список групп (+ создание) слева, состав и
     назначенные преподаватели выбранной группы справа (добавить/убрать по
     логину). Отражает /admin/groups.
  3. Предметы преподавателям — матрица «преподаватель × предмет» с
     чекбоксами (docs/subject_grants.md). Правится целиком и сохраняется
     кнопкой: строки уходят на сервер по одной и последовательно, потому что
     _start_call держит один вызов в полёте. Здесь же переключатель режима
     по умолчанию (видно всё / ничего) для преподавателей без выдач.
  4. Права по ролям — статичная справочная матрица (student|teacher|admin):
     что кому доступно. Информационная, серверных вызовов не делает.

Управление доступно только admin и только при заданном адресе сервера
(права server-authoritative). Все HTTP-вызовы блокирующие — уводятся в
_CallWorker (QThread, тот же паттерн, что contour/sync-окна). Окно
немодальное, живёт синглтоном у владельца; refresh() дёшев и идемпотентен.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSizePolicy, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from core.admin import AdminError
from core.grants import GrantsError
from ui.app_context import AppContext

ROLES = ("student", "teacher", "admin")
ROLE_LABELS = {"student": "студент", "teacher": "преподаватель",
               "admin": "администратор"}

# Матрица прав (вкладка 3) — справочная, синхронна с серверной моделью.
# Значения: True — доступно; False — нет; "own" — только своё; "soon" — скоро.
_CAPABILITIES = [
    ("Контент", [
        ("Решать задания, видеть свою статистику", True, True, True),
        ("Создавать и править свои предметы/разделы", False, True, True),
        ("Скрывать/удалять свои разделы", False, True, True),
        ("Править встроенные (системные) предметы", False, False, True),
    ]),
    ("ИИ-контур", [
        ("Запускать генерацию через ИИ", False, True, True),
        ("Утверждать сгенерированные задания", False, "own", True),
    ]),
    ("Аналитика", [
        ("Аналитика по своим предметам", False, True, True),
        ("Глобальная аналитика по всем предметам", False, False, True),
    ]),
    ("Администрирование", [
        ("Список пользователей, смена ролей", False, False, True),
        ("Группы и назначение преподавателей", False, False, True),
        ("Выдача предметов преподавателям", False, False, True),
    ]),
]
_CELL = {True: "✓", False: "—", "own": "только своё", "soon": "скоро"}


class _CallWorker(QThread):
    """Один блокирующий вызов AdminClient в фоне (паттерн contour/sync-окон).
    Результат/ошибка — сигналами; виджеты из воркера не трогаются.

    Родителя у воркера НЕТ намеренно, см. `_IN_FLIGHT`.
    """

    done = pyqtSignal(object)
    failed = pyqtSignal(object)   # (message: str, status: int|None)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:  # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn())
        except (AdminError, GrantsError) as e:
            # Оба клиента несут HTTP-код — он нужен окну, чтобы отличить
            # «не хватает прав» от «нарушено доменное правило».
            self.failed.emit((str(e), getattr(e, "status", None)))
        except Exception as e:
            self.failed.emit((f"администрирование: {e}", None))


_IN_FLIGHT: set = set()
"""
Воркеры, которые сейчас работают.

Держим их здесь, а не родителем-виджетом, и это не перестраховка, а
починка падения. Раньше воркер создавался с окном в родителях, и удаление
окна удаляло ЕГО ВМЕСТЕ С РАБОТАЮЩИМ ПОТОКОМ: закрыть окно (или выйти из
программы) с запросом в полёте значило снести живой QThread, а это
неопределённое поведение, на практике — segfault без единого сообщения.

Ссылка здесь же не даёт сборщику мусора убрать python-обёртку раньше
времени: `self._worker = None` в колбэке снимает последнюю ссылку окна,
а поток к этому моменту ещё не закончился.

Снимается по `finished` — то есть когда поток действительно встал.
"""


class _Alive:
    """
    Жив ли ещё виджет, ради которого затевался запрос.

    Спросить об этом само окно нельзя: к моменту ответа его python-обёртка
    указывает на удалённый объект, и любое обращение — либо исключение,
    либо падение. Поэтому признак живёт в отдельном объекте, который
    переживает окно, а гасит его сигнал `destroyed`.
    """

    # `__weakref__` в слотах обязателен: PyQt держит получателя сигнала
    # слабой ссылкой, а на объект без него ссылку не создать.
    __slots__ = ("alive", "__weakref__")

    def __init__(self) -> None:
        self.alive = True

    def mark_dead(self, *_args) -> None:
        self.alive = False


class AdminWindow(QWidget):
    """Окно администрирования: пользователи/роли, группы, матрица прав."""

    def __init__(self, context: AppContext, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.client = getattr(context, "admin_client", None)
        self.grants_client = getattr(context, "grants_client", None)
        self._worker: Optional[_CallWorker] = None
        # Сторож на случай, если окно умрёт раньше своего запроса: колбэк
        # обязан промолчать, а не трогать удалённый виджет.
        self._alive = _Alive()
        self.destroyed.connect(self._alive.mark_dead)
        # Матрица выдач: канон с сервера, рабочая копия и очередь сохранения.
        self._grants_teachers: list[dict] = []
        self._grants_subjects: list[dict] = []
        self._grants_loaded: dict[str, set[int]] = {}
        self._grants_draft: dict[str, set[int]] = {}
        self._grants_save_queue: list[str] = []
        self._refresh_queue: list[Callable[[], None]] = []
        # Подтверждение смены роли: по умолчанию модальный диалог; тесты
        # подменяют на предикат без UI.
        self._confirm: Callable[[str], bool] = self._default_confirm
        self._viewer_login = context.user_id_provider() or ""

        self.setWindowTitle("Администрирование")
        self.resize(760, 620)
        self._build_ui()
        self.refresh()

    # ---------- сборка ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(10)

        title = QLabel("Администрирование", self)
        title.setProperty("class", "title")
        root.addWidget(title)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_users_tab(), "Пользователи и роли")
        self.tabs.addTab(self._build_groups_tab(), "Группы")
        self.tabs.addTab(self._build_grants_tab(), "Предметы преподавателям")
        self.tabs.addTab(self._build_matrix_tab(), "Права по ролям")
        root.addWidget(self.tabs, stretch=1)

        # Заглушка «недоступно» поверх вкладок, когда сервер/роль не позволяют.
        self.disabled_label = QLabel("", self)
        self.disabled_label.setProperty("class", "muted")
        self.disabled_label.setWordWrap(True)
        self.disabled_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disabled_label.hide()
        root.addWidget(self.disabled_label)

    # --- вкладка 1: пользователи ---

    def _build_users_tab(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        intro = QLabel(
            "Роль назначается целиком и применяется у пользователя при "
            "следующем входе. Свою роль изменить нельзя; нельзя понизить "
            "последнего администратора.", page)
        intro.setProperty("class", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.users_error = QLabel("", page)
        self.users_error.setProperty("class", "danger")
        self.users_error.setWordWrap(True)
        self.users_error.hide()
        lay.addWidget(self.users_error)

        self.users_table = QTableWidget(0, 4, page)
        self.users_table.setHorizontalHeaderLabels(
            ["Пользователь", "Группа", "Роль", "Регистрация"])
        self.users_table.verticalHeader().setVisible(False)
        self.users_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.users_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        hh = self.users_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.users_table, stretch=1)

        row = QHBoxLayout()
        self.users_reload_btn = QPushButton("Обновить", page)
        self.users_reload_btn.clicked.connect(self._load_users)
        row.addWidget(self.users_reload_btn)
        row.addStretch(1)
        lay.addLayout(row)
        return page

    # --- вкладка 2: группы ---

    def _build_groups_tab(self) -> QWidget:
        page = QWidget(self)
        outer = QHBoxLayout(page)
        outer.setSpacing(12)

        # Левая колонка: список групп + создание.
        left = QVBoxLayout()
        left.setSpacing(6)
        left_cap = QLabel("Группы", page)
        left_cap.setProperty("class", "subtitle")
        left.addWidget(left_cap)
        self.groups_list = QListWidget(page)
        self.groups_list.currentItemChanged.connect(
            lambda *_: self._render_group_detail())
        left.addWidget(self.groups_list, stretch=1)
        create_row = QHBoxLayout()
        self.group_name_edit = QLineEdit(page)
        self.group_name_edit.setPlaceholderText("Название группы")
        create_row.addWidget(self.group_name_edit, stretch=1)
        self.group_create_btn = QPushButton("Создать", page)
        self.group_create_btn.clicked.connect(self._on_create_group)
        create_row.addWidget(self.group_create_btn)
        left.addLayout(create_row)
        outer.addLayout(left, stretch=1)

        # Правая колонка: детализация выбранной группы.
        right = QVBoxLayout()
        right.setSpacing(6)
        self.group_detail_title = QLabel("Выберите группу", page)
        self.group_detail_title.setProperty("class", "subtitle")
        right.addWidget(self.group_detail_title)

        self.groups_error = QLabel("", page)
        self.groups_error.setProperty("class", "danger")
        self.groups_error.setWordWrap(True)
        self.groups_error.hide()
        right.addWidget(self.groups_error)

        members_cap = QLabel("Участники", page)
        members_cap.setProperty("class", "muted")
        right.addWidget(members_cap)
        self.members_list = QListWidget(page)
        right.addWidget(self.members_list, stretch=1)
        add_member_row = QHBoxLayout()
        self.member_login_edit = QLineEdit(page)
        self.member_login_edit.setPlaceholderText("логин студента")
        add_member_row.addWidget(self.member_login_edit, stretch=1)
        self.member_add_btn = QPushButton("Добавить", page)
        self.member_add_btn.clicked.connect(self._on_add_member)
        add_member_row.addWidget(self.member_add_btn)
        right.addLayout(add_member_row)

        teachers_cap = QLabel("Преподаватели", page)
        teachers_cap.setProperty("class", "muted")
        right.addWidget(teachers_cap)
        self.teachers_list = QListWidget(page)
        right.addWidget(self.teachers_list, stretch=1)
        add_teacher_row = QHBoxLayout()
        self.teacher_login_edit = QLineEdit(page)
        self.teacher_login_edit.setPlaceholderText("логин преподавателя")
        add_teacher_row.addWidget(self.teacher_login_edit, stretch=1)
        self.teacher_add_btn = QPushButton("Назначить", page)
        self.teacher_add_btn.clicked.connect(self._on_assign_teacher)
        add_teacher_row.addWidget(self.teacher_add_btn)
        right.addLayout(add_teacher_row)

        outer.addLayout(right, stretch=2)
        return page

    # --- вкладка 3: предметы преподавателям ---

    def _build_grants_tab(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        lay.setSpacing(8)

        intro = QLabel(
            "Отметьте, какие предметы доступны преподавателю. Изменения "
            "применяются кнопкой — правьте матрицу целиком и сохраняйте одним "
            "действием. Преподаватель увидит новый набор при следующей "
            "синхронизации.\n"
            "Для встроенных предметов это витрина, а не защита: их генераторы "
            "входят в само приложение, и локальную базу её владелец правит как "
            "хочет. Полноценно закрывается только серверный контент.", page)
        intro.setProperty("class", "muted")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        self.grants_error = QLabel("", page)
        self.grants_error.setProperty("class", "danger")
        self.grants_error.setWordWrap(True)
        self.grants_error.hide()
        lay.addWidget(self.grants_error)

        top = QHBoxLayout()
        top.addWidget(QLabel("Без выдач преподаватель видит:", page))
        self.grants_default_combo = QComboBox(page)
        self.grants_default_combo.addItem("все предметы", "all")
        self.grants_default_combo.addItem("ничего", "none")
        self.grants_default_combo.setToolTip(
            "«Все предметы» — безопасное умолчание: пока админ не раздал "
            "доступы, никто не остаётся с пустым экраном. Переключайте в "
            "«ничего», когда выдачи проставлены.")
        self.grants_default_combo.currentIndexChanged.connect(
            self._on_default_access_changed)
        top.addWidget(self.grants_default_combo)
        top.addSpacing(16)
        self.grants_filter_edit = QLineEdit(page)
        self.grants_filter_edit.setPlaceholderText("Поиск преподавателя")
        self.grants_filter_edit.textChanged.connect(
            lambda *_: self._render_grants_table())
        top.addWidget(self.grants_filter_edit, stretch=1)
        lay.addLayout(top)

        self.grants_table = QTableWidget(0, 0, page)
        self.grants_table.verticalHeader().setVisible(False)
        self.grants_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.grants_table.itemChanged.connect(self._on_grant_cell_changed)
        lay.addWidget(self.grants_table, stretch=1)

        row = QHBoxLayout()
        self.grants_apply_btn = QPushButton("Применить", page)
        self.grants_apply_btn.clicked.connect(self._on_apply_grants)
        self.grants_apply_btn.setEnabled(False)
        row.addWidget(self.grants_apply_btn)
        self.grants_revert_btn = QPushButton("Сбросить", page)
        self.grants_revert_btn.clicked.connect(self._on_revert_grants)
        self.grants_revert_btn.setEnabled(False)
        row.addWidget(self.grants_revert_btn)
        row.addStretch(1)
        self.grants_dirty_label = QLabel("", page)
        self.grants_dirty_label.setProperty("class", "muted")
        row.addWidget(self.grants_dirty_label)
        self.grants_reload_btn = QPushButton("Обновить", page)
        self.grants_reload_btn.clicked.connect(self._load_grants)
        row.addWidget(self.grants_reload_btn)
        lay.addLayout(row)
        return page

    # ---------- выдачи предметов ----------

    def _load_grants(self) -> None:
        if self.grants_client is None:
            return
        self.grants_error.hide()
        self._start_call(self.grants_client.matrix, self._on_grants_loaded,
                         self._on_grants_error)

    def _on_grants_loaded(self, matrix: dict) -> None:
        self._grants_teachers = list(matrix.get("teachers") or [])
        self._grants_subjects = list(matrix.get("subjects") or [])
        loaded = matrix.get("grants") or {}
        # Снимок «как на сервере» и рабочая копия — раздельно: разница между
        # ними и есть то, что уйдёт на сервер по «Применить».
        self._grants_loaded = {
            str(t["login"]): set(loaded.get(str(t["login"])) or set())
            for t in self._grants_teachers}
        self._grants_draft = {k: set(v) for k, v in self._grants_loaded.items()}

        combo = self.grants_default_combo
        combo.blockSignals(True)
        idx = combo.findData(matrix.get("default_access", "all"))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

        self._render_grants_table()

    def _visible_teachers(self) -> list[dict]:
        needle = self.grants_filter_edit.text().strip().lower()
        teachers = getattr(self, "_grants_teachers", [])
        if not needle:
            return list(teachers)
        return [t for t in teachers
                if needle in str(t.get("login", "")).lower()
                or needle in str(t.get("fio", "")).lower()]

    def _render_grants_table(self) -> None:
        subjects = getattr(self, "_grants_subjects", [])
        teachers = self._visible_teachers()
        table = self.grants_table
        # Заполнение шлёт itemChanged на каждую ячейку — иначе рисование
        # выглядело бы как правка пользователя и пачкало черновик.
        table.blockSignals(True)
        table.clear()
        table.setRowCount(len(teachers))
        table.setColumnCount(len(subjects) + 1)
        table.setHorizontalHeaderLabels(
            ["Преподаватель"] + [str(s.get("subject_name", "")) for s in subjects])
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(subjects) + 1):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        for col, subject in enumerate(subjects, start=1):
            header = table.horizontalHeaderItem(col)
            if header is not None and subject.get("is_builtin"):
                header.setToolTip(
                    "Встроенный предмет: ограничение действует на витрину, "
                    "но генераторы входят в приложение")

        for r, teacher in enumerate(teachers):
            login = str(teacher.get("login", ""))
            fio = str(teacher.get("fio", "")) or "—"
            who = QTableWidgetItem(f"{fio}\n{login}")
            who.setData(Qt.ItemDataRole.UserRole, login)
            who.setFlags(Qt.ItemFlag.ItemIsEnabled)
            table.setItem(r, 0, who)
            granted = self._grants_draft.get(login, set())
            for c, subject in enumerate(subjects, start=1):
                sid = int(subject["id"])
                cell = QTableWidgetItem("")
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled
                              | Qt.ItemFlag.ItemIsUserCheckable)
                cell.setCheckState(Qt.CheckState.Checked if sid in granted
                                   else Qt.CheckState.Unchecked)
                cell.setData(Qt.ItemDataRole.UserRole, (login, sid))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, cell)
        table.blockSignals(False)
        self._update_grants_dirty()

    def _on_grant_cell_changed(self, item: QTableWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(payload, tuple):
            return
        login, sid = payload
        bucket = self._grants_draft.setdefault(login, set())
        if item.checkState() == Qt.CheckState.Checked:
            bucket.add(int(sid))
        else:
            bucket.discard(int(sid))
        self._update_grants_dirty()

    def _dirty_logins(self) -> list[str]:
        loaded = getattr(self, "_grants_loaded", {})
        draft = getattr(self, "_grants_draft", {})
        return sorted(login for login, ids in draft.items()
                      if ids != loaded.get(login, set()))

    def _update_grants_dirty(self) -> None:
        dirty = self._dirty_logins()
        self.grants_apply_btn.setEnabled(bool(dirty))
        self.grants_revert_btn.setEnabled(bool(dirty))
        self.grants_dirty_label.setText(
            f"Не сохранено: {len(dirty)}" if dirty else "")

    def _on_revert_grants(self) -> None:
        self._grants_draft = {k: set(v)
                              for k, v in getattr(self, "_grants_loaded", {}).items()}
        self._render_grants_table()

    def _on_apply_grants(self) -> None:
        # Правки сохраняются по одному преподавателю и ПОСЛЕДОВАТЕЛЬНО:
        # _start_call держит один вызов в полёте, параллельные молча пропали
        # бы. Каждая строка отправляется целым набором — идемпотентно.
        self.grants_error.hide()
        self._grants_save_queue = self._dirty_logins()
        self._save_next_grant_row()

    def _save_next_grant_row(self) -> None:
        queue = getattr(self, "_grants_save_queue", [])
        if not queue:
            self._load_grants()      # перечитать канон после записи
            return
        login = queue.pop(0)
        ids = sorted(self._grants_draft.get(login, set()))

        def _done(_resp: object) -> None:
            # Строка легла на сервер — двигаем канон, чтобы обрыв на середине
            # очереди не выглядел как «ничего не сохранилось».
            self._grants_loaded[login] = set(ids)
            self._update_grants_dirty()
            self._save_next_grant_row()

        self._start_call(
            lambda: self.grants_client.set_teacher_grants(login, ids),
            _done, self._on_grants_error)

    def _on_default_access_changed(self) -> None:
        if self.grants_client is None:
            return
        value = self.grants_default_combo.currentData()
        if not self._confirm(
                "Переключить режим по умолчанию на "
                f"«{self.grants_default_combo.currentText()}»? Это меняет "
                "витрину у всех преподавателей без явных выдач."):
            self._load_grants()      # откат — перечитать актуальный режим
            return
        self.grants_error.hide()
        self._start_call(
            lambda: self.grants_client.set_default_access(value),
            lambda _r: self._load_grants(), self._on_grants_error)

    def _on_grants_error(self, err) -> None:
        message, _status = err
        # Очередь сохранения рвём: продолжать вслепую после отказа нельзя.
        self._grants_save_queue = []
        self.grants_error.setText(message)
        self.grants_error.show()

    # --- вкладка 4: матрица прав ---

    def _build_matrix_tab(self) -> QWidget:
        page = QWidget(self)
        lay = QVBoxLayout(page)
        rows = sum(len(caps) for _c, caps in _CAPABILITIES) + len(_CAPABILITIES)
        table = QTableWidget(rows, 4, page)
        table.setHorizontalHeaderLabels(
            ["Возможность", "студент", "преподаватель", "администратор"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        r = 0
        for category, caps in _CAPABILITIES:
            head = QTableWidgetItem(category)
            head.setForeground(Qt.GlobalColor.gray)
            table.setItem(r, 0, head)
            table.setSpan(r, 0, 1, 4)
            r += 1
            for label, s, t, a in caps:
                table.setItem(r, 0, QTableWidgetItem(label))
                for col, val in ((1, s), (2, t), (3, a)):
                    cell = QTableWidgetItem(_CELL[val])
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    table.setItem(r, col, cell)
                r += 1
        lay.addWidget(table)
        return page

    # ---------- публичное обновление ----------

    def refresh(self) -> None:
        """Пересчитать доступность и, если доступно, перечитать данные.
        Дёшево и идемпотентно."""
        if self.client is None or not self.client.can_use():
            self.disabled_label.setText(self._disabled_reason())
            self.disabled_label.show()
            self.tabs.hide()
            return
        self.disabled_label.hide()
        self.tabs.show()
        # Последовательно, а не тремя вызовами подряд: _start_call держит один
        # вызов в полёте и МОЛЧА роняет остальные — подряд загрузились бы
        # только пользователи, а группы и выдачи остались бы пустыми.
        self._refresh_queue = [self._load_users, self._load_groups,
                               self._load_grants]
        self._drain_refresh_queue()

    def _drain_refresh_queue(self) -> None:
        """Запустить следующий шаг обновления, когда воркер освободился."""
        if self._worker is not None or not self._refresh_queue:
            return
        self._refresh_queue.pop(0)()

    def _disabled_reason(self) -> str:
        if self.client is None or not self.client.has_server():
            return ("Администрирование недоступно: адрес сервера не задан.\n"
                    "Укажите его в Настройках (вкладка «Соединение»).")
        return ("Администрирование доступно только администраторам.\n"
                "Права проверяются на сервере.")

    # ---------- пользователи ----------

    def _load_users(self) -> None:
        if self.client is None:
            return
        self.users_error.hide()
        self._start_call(self.client.list_users, self._on_users_loaded,
                         self._on_users_error)

    def _on_users_loaded(self, users: list) -> None:
        self.users_table.setRowCount(0)
        for u in users:
            self._append_user_row(u)

    def _append_user_row(self, user: dict) -> None:
        row = self.users_table.rowCount()
        self.users_table.insertRow(row)
        login = str(user.get("login", ""))
        fio = str(user.get("fio", "")) or "—"
        who = QTableWidgetItem(f"{fio}\n{login}")
        who.setData(Qt.ItemDataRole.UserRole, login)
        self.users_table.setItem(row, 0, who)
        self.users_table.setItem(
            row, 1, QTableWidgetItem(str(user.get("group", "")) or "—"))

        combo = QComboBox(self.users_table)
        for r in ROLES:
            combo.addItem(ROLE_LABELS[r], r)
        combo.setCurrentIndex(ROLES.index(user.get("role", "student"))
                              if user.get("role") in ROLES else 0)
        combo.setProperty("login", login)
        if login == self._viewer_login:
            combo.setEnabled(False)
            combo.setToolTip("Нельзя изменить свою роль")
        else:
            combo.currentIndexChanged.connect(
                lambda _i, c=combo: self._on_role_combo_changed(c))
        self.users_table.setCellWidget(row, 2, combo)

        created = user.get("created_at")
        self.users_table.setItem(
            row, 3, QTableWidgetItem(self._fmt_ts(created)))

    def _on_role_combo_changed(self, combo: QComboBox) -> None:
        login = combo.property("login")
        new_role = combo.currentData()
        if not self._confirm(
                f"Изменить роль пользователя {login} на "
                f"«{ROLE_LABELS[new_role]}»?"):
            self._load_users()   # откат — перечитать актуальные роли
            return
        self.users_error.hide()
        self._start_call(
            lambda: self.client.change_role(login, new_role),
            lambda _resp: self._load_users(), self._on_users_error)

    def _on_users_error(self, err) -> None:
        message, _status = err
        self.users_error.setText(message)
        self.users_error.show()
        self._load_users_silent_if_possible()

    def _load_users_silent_if_possible(self) -> None:
        # После ошибки смены роли перечитываем таблицу, чтобы combobox
        # отражал актуальное состояние (guardrail-откат). Но не зациклим:
        # если сам список не грузится — просто оставляем ошибку.
        if self.client is not None:
            self._start_call(self.client.list_users, self._on_users_loaded,
                             lambda _e: None)

    # ---------- группы ----------

    def _load_groups(self) -> None:
        if self.client is None:
            return
        self.groups_error.hide()
        self._start_call(self.client.list_groups, self._on_groups_loaded,
                         self._on_groups_error)

    def _on_groups_loaded(self, groups: list) -> None:
        self._groups = {int(g["id"]): g for g in groups}
        prev = self._current_group_id()
        self.groups_list.blockSignals(True)
        self.groups_list.clear()
        for g in groups:
            item = QListWidgetItem(
                f"{g['name']}  ·  {g.get('member_count', 0)}")
            item.setData(Qt.ItemDataRole.UserRole, int(g["id"]))
            self.groups_list.addItem(item)
        self.groups_list.blockSignals(False)
        self._select_group(prev if prev is not None else
                            (int(groups[0]["id"]) if groups else None))

    def _select_group(self, group_id: Optional[int]) -> None:
        if group_id is None:
            self._render_group_detail()
            return
        for i in range(self.groups_list.count()):
            if self.groups_list.item(i).data(Qt.ItemDataRole.UserRole) == group_id:
                self.groups_list.setCurrentRow(i)
                break
        self._render_group_detail()

    def _current_group_id(self) -> Optional[int]:
        item = self.groups_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _render_group_detail(self) -> None:
        gid = self._current_group_id()
        self.members_list.clear()
        self.teachers_list.clear()
        group = getattr(self, "_groups", {}).get(gid) if gid is not None else None
        if group is None:
            self.group_detail_title.setText("Выберите группу")
            return
        self.group_detail_title.setText(str(group["name"]))
        for login in group.get("members", []):
            self._add_detail_item(self.members_list, login,
                                  self._on_remove_member)
        for login in group.get("teachers", []):
            self._add_detail_item(self.teachers_list, login,
                                  self._on_unassign_teacher)

    def _add_detail_item(self, list_widget: QListWidget, login: str,
                         remover: Callable[[str], None]) -> None:
        item = QListWidgetItem(list_widget)
        row = QWidget(list_widget)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(4, 2, 4, 2)
        lbl = QLabel(login, row)
        lay.addWidget(lbl, stretch=1)
        btn = QPushButton("✕", row)
        btn.setProperty("class", "danger")
        btn.setFixedWidth(28)
        btn.setToolTip("Убрать")
        btn.clicked.connect(lambda: remover(login))
        lay.addWidget(btn)
        item.setSizeHint(row.sizeHint())
        list_widget.addItem(item)
        list_widget.setItemWidget(item, row)

    def _on_create_group(self) -> None:
        name = self.group_name_edit.text().strip()
        if not name:
            return
        self.groups_error.hide()
        self._start_call(
            lambda: self.client.create_group(name),
            lambda _resp: (self.group_name_edit.clear(), self._load_groups()),
            self._on_groups_error)

    def _on_add_member(self) -> None:
        gid = self._current_group_id()
        login = self.member_login_edit.text().strip()
        if gid is None or not login:
            return
        self.groups_error.hide()
        self._start_call(
            lambda: self.client.add_member(gid, login),
            lambda _r: (self.member_login_edit.clear(), self._load_groups()),
            self._on_groups_error)

    def _on_remove_member(self, login: str) -> None:
        gid = self._current_group_id()
        if gid is None:
            return
        self.groups_error.hide()
        self._start_call(lambda: self.client.remove_member(gid, login),
                         lambda _r: self._load_groups(), self._on_groups_error)

    def _on_assign_teacher(self) -> None:
        gid = self._current_group_id()
        login = self.teacher_login_edit.text().strip()
        if gid is None or not login:
            return
        self.groups_error.hide()
        self._start_call(
            lambda: self.client.assign_teacher(gid, login),
            lambda _r: (self.teacher_login_edit.clear(), self._load_groups()),
            self._on_groups_error)

    def _on_unassign_teacher(self, login: str) -> None:
        gid = self._current_group_id()
        if gid is None:
            return
        self.groups_error.hide()
        self._start_call(lambda: self.client.unassign_teacher(gid, login),
                         lambda _r: self._load_groups(), self._on_groups_error)

    def _on_groups_error(self, err) -> None:
        message, _status = err
        self.groups_error.setText(message)
        self.groups_error.show()

    # ---------- утилиты ----------

    def _default_confirm(self, question: str) -> bool:
        return QMessageBox.question(
            self, "Подтверждение", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes

    @staticmethod
    def _fmt_ts(ts) -> str:
        try:
            from datetime import datetime, timezone
            if isinstance(ts, str):
                return ts[:10]
            if ts:
                return datetime.fromtimestamp(
                    float(ts), tz=timezone.utc).date().isoformat()
        except Exception:
            pass
        return "—"

    def _start_call(self, fn: Callable[[], object],
                    on_done: Callable[[object], None],
                    on_failed: Callable[[object], None]) -> None:
        # Один вызов в полёте (защита от двойного сабмита действий). Слот
        # снимает флаг ДО пользовательского колбэка, чтобы колбэк мог
        # запустить следующий вызов (действие → перечитать список): иначе
        # reload внутри on_done упёрся бы в ещё занятый _worker.
        if self._worker is not None:
            return
        # Без родителя: виджет-владелец, умерев раньше потока, снёс бы
        # живой QThread (см. `_IN_FLIGHT`). Живым его держит множество
        # летящих, а не окно.
        worker = _CallWorker(fn)
        self._worker = worker
        _IN_FLIGHT.add(worker)
        alive = self._alive

        def _retire() -> None:
            _IN_FLIGHT.discard(worker)

        def _on_done(result: object) -> None:
            # Окна уже нет — отвечать некому. Не ошибка: пользователь
            # вправе закрыть окно, не дожидаясь ответа сервера.
            if not alive.alive:
                return
            self._worker = None
            on_done(result)
            self._drain_refresh_queue()

        def _on_failed(err: object) -> None:
            if not alive.alive:
                return
            self._worker = None
            on_failed(err)
            # Шаг упал — остальные всё равно нужны: неудача с группами не
            # повод оставить вкладку выдач пустой.
            self._drain_refresh_queue()

        worker.done.connect(_on_done)
        worker.failed.connect(_on_failed)
        worker.finished.connect(_retire)
        worker.finished.connect(worker.deleteLater)
        worker.start()
