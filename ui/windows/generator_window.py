"""
GeneratorWindow — главное окно генератора.

Не знает о предметах. Работает только с Repository (БД) и
GeneratorRegistry (модули).

Отвечает за:
  1. Выбор предмета и раздела
  2. Подбор представления по capabilities + view_kind
  3. Управление разделами (создание/редактирование/удаление групп, тестов,
     физических конструкторов) через ui.editors
  4. Пересборку реестра после изменений в БД
"""

from __future__ import annotations
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QCheckBox, QComboBox, QLabel, QMessageBox, QListWidgetItem, QPushButton,
    QMenu, QSizePolicy, QToolButton
)

from core import (
    Capability, GeneratorRegistry, Subject, Partition,
    TaskGenerator, WordStatsStore,
)
from ui.app_context import AppContext
from ui.widgets import TopBar
from ui.views import (
    StaticTaskView, TableTaskView, InteractiveTaskView, TestExportView
)
from ui.editors import create_editor, PartitionEditor
from ui.utils import clear_layout
from .stats_window import StatsWindow


# Тип фабрики, пересобирающей реестр после изменений в БД.
RegistryBuilder = Callable[[], GeneratorRegistry]


class GeneratorWindow(QMainWindow):
    """Главное окно: выбор предмета, список разделов, область задания, управление."""

    def __init__(
        self,
        context: AppContext,
        registry: GeneratorRegistry,
        registry_builder: RegistryBuilder | None = None,
        *,
        stats_store: WordStatsStore | None = None,
        words_dir: Path | None = None,
    ):
        """
        context — кросс-сквозная инфраструктура и сессия (репозиторий,
        настройки, провайдеры user_id/role, клиенты sync/контура).

        registry_builder — опциональная функция, которая пересобирает реестр
        после изменения БД. Без неё кнопки правки/создания не показываются.

        stats_store — если передан, в шапке появляется кнопка «Моя
        статистика», открывающая StatsWindow. words_dir нужен окну
        статистики, чтобы рядом с термином показывать перевод.
        """
        super().__init__()
        self.ctx = context
        self.repo = context.repo
        self.user_id_provider = context.user_id_provider
        self.user_role_provider = context.user_role_provider
        self.registry = registry
        self.registry_builder = registry_builder
        self.stats_store = stats_store
        self.words_dir = words_dir
        self.subjects: list[Subject] = []
        self.partitions: list[Partition] = []
        self._editor_window: PartitionEditor | None = None
        self._stats_window: StatsWindow | None = None
        self._sync_window = None
        self._contour_window = None
        self._admin_window = None
        self._analytics_window = None
        self._homework_window = None

        self.setWindowTitle("Генератор заданий")
        self.resize(1100, 720)
        self._build_ui()
        self._load_subjects()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Верхняя панель действий ----
        # Единая точка расширения: подсистемы вешают сюда свои кнопки
        # (статистика сейчас; настройки/sync/контур — следующими волнами).
        self.top_bar = TopBar(self.user_role_provider, self)
        outer.addWidget(self.top_bar)
        if self.stats_store is not None:
            self.top_bar.add_action(
                "Моя статистика",
                "История прохождения словарного тренажёра "
                "(межсессионная для авторизованных, "
                "в рамках запуска — для гостей).",
                self._open_stats_window,
            )
        self.top_bar.add_action(
            "Настройки",
            "Технические настройки среды: адрес сервера, оформление, аккаунт.",
            self._open_settings,
        )
        if self.ctx.sync_client is not None:
            self.top_bar.add_action(
                "Синхронизация",
                "Отправить локальные изменения на сервер и получить чужие; "
                "разрешить конфликты.",
                self._open_sync_window,
            )
            # Бейдж состояния синка (несинхронизированные правки / конфликты).
            self.top_bar.add_badge("sync")
        if self.ctx.contour_client is not None:
            # Контур доступен только преподавателям/админам (гейтинг ролью).
            self.top_bar.add_action(
                "✨ ИИ-генератор",
                "Генератор через ИИ: опишите задание — сервер соберёт и "
                "проверит генератор, вы утвердите результат.",
                self._open_contour_window,
                roles={"teacher", "admin"},
            )
        if self.ctx.analytics_client is not None:
            # Аналитика — преподавателям/админам (окно покажет заглушку без
            # сервера; скоуп данных считает сервер по владению предметами).
            self.top_bar.add_action(
                "Аналитика",
                "Дашборд успеваемости: попытки, доля верных, сложность "
                "заданий, студенты и группы (только с сервером).",
                self._open_analytics_window,
                roles={"teacher", "admin"},
            )
        if self.ctx.assignments_client is not None:
            # Домашки — вошедшему пользователю (teacher/admin выдают, student
            # смотрит; ветвление и заглушки — внутри окна).
            self.top_bar.add_action(
                "Домашки",
                "Выдача заданий группам (преподаватель) и просмотр выданных "
                "домашек (студент). Требует сервера.",
                self._open_homework_window,
                roles={"teacher", "admin", "student"},
            )
        if self.ctx.admin_client is not None:
            # Администрирование — только admin (окно само покажет заглушку,
            # если адрес сервера не задан: права server-authoritative).
            self.top_bar.add_action(
                "Администрирование",
                "Пользователи и роли, группы и назначение преподавателей "
                "(только с сервером).",
                self._open_admin_window,
                roles={"admin"},
            )

        # ---- Контент (под панелью) ----
        content = QWidget(central)
        root = QHBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        outer.addWidget(content, stretch=1)

        # ---- Боковая панель (навигация по предметам и разделам) ----
        left_widget = QWidget(self)
        left_widget.setProperty("class", "sidebar")
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(14, 14, 14, 14)
        left.setSpacing(8)

        brand = QLabel("Генератор", left_widget)
        brand.setProperty("class", "brand")
        left.addWidget(brand)

        subj_cap = QLabel("Предмет", left_widget)
        subj_cap.setProperty("class", "subtitle")
        left.addWidget(subj_cap)
        subj_row = QHBoxLayout()
        self.subject_combo = QComboBox(self)
        subj_row.addWidget(self.subject_combo, stretch=1)
        # Меню действий над предметом: скрыть/показать/удалить.
        self.subject_menu_btn = QToolButton(self)
        self.subject_menu_btn.setText("⋯")
        self.subject_menu_btn.setToolTip("Действия с предметом")
        self.subject_menu_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup)
        subj_menu = QMenu(self.subject_menu_btn)
        self._subj_hide_action = subj_menu.addAction(
            "Скрыть предмет", self._on_toggle_subject_hidden)
        subj_menu.addAction("Удалить предмет…", self._on_delete_subject)
        self.subject_menu_btn.setMenu(subj_menu)
        subj_row.addWidget(self.subject_menu_btn)
        left.addLayout(subj_row)

        left.addSpacing(4)
        part_cap = QLabel("Разделы", left_widget)
        part_cap.setProperty("class", "subtitle")
        left.addWidget(part_cap)

        self.partition_list = QListWidget(self)
        self.partition_list.setSpacing(2)
        # Контекстное меню раздела: скрыть/показать/удалить.
        self.partition_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.partition_list.customContextMenuRequested.connect(
            self._on_partition_context_menu)
        left.addWidget(self.partition_list, stretch=1)

        # Пустое состояние списка разделов (показывается вместо пустого списка).
        self.partitions_empty = QLabel("", left_widget)
        self.partitions_empty.setProperty("class", "muted")
        self.partitions_empty.setWordWrap(True)
        self.partitions_empty.hide()
        left.addWidget(self.partitions_empty)

        # Показ скрытых: влияет и на предметы, и на разделы.
        self.show_hidden_cb = QCheckBox("Показывать скрытые", self)
        self.show_hidden_cb.toggled.connect(self._on_show_hidden_toggled)
        left.addWidget(self.show_hidden_cb)

        # Панель управления разделами — только если есть registry_builder
        if self.registry_builder is not None:
            self._build_partition_controls(left)

        left_widget.setFixedWidth(300)
        root.addWidget(left_widget)

        # ---- Правая панель (область задания) ----
        self.view_holder = QWidget(self)
        self.view_layout = QVBoxLayout(self.view_holder)
        self.view_layout.setContentsMargins(18, 18, 18, 18)
        root.addWidget(self.view_holder, stretch=1)

        # Приветствие/пустое состояние области задания.
        self._show_content_placeholder(
            "Выберите раздел слева, чтобы сгенерировать задание.")

        # Сигналы
        self.subject_combo.currentIndexChanged.connect(self._on_subject_changed)
        self.partition_list.itemClicked.connect(self._on_partition_clicked)
        self.partition_list.itemSelectionChanged.connect(self._on_selection_changed)

    def _build_partition_controls(self, parent_layout: QVBoxLayout) -> None:
        """
        Кнопки «Создать», «Изменить», «Удалить» под списком разделов.
        Кнопка «Создать» открывает меню с тремя типами: группа / тест / задача физики.
        """
        # Первичное действие — «+ Создать» на всю ширину сайдбара.
        self.create_btn = QToolButton(self)
        self.create_btn.setText("+ Создать раздел")
        self.create_btn.setProperty("class", "primary")
        self.create_btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                      QSizePolicy.Policy.Fixed)
        self.create_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.create_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly)
        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Группу", lambda: self._open_editor_new("group"))
        create_menu.addAction("Тест",   lambda: self._open_editor_new("test"))
        create_menu.addAction("Задачу по физике",
                              lambda: self._open_editor_new("fisic"))
        create_menu.addAction("Граф (визуальный конструктор)",
                              lambda: self._open_editor_new("graph"))
        self.create_btn.setMenu(create_menu)
        parent_layout.addWidget(self.create_btn)

        # Вторичные действия — правка/удаление выбранного, отдельным рядом.
        controls = QHBoxLayout()
        self.edit_btn = QPushButton("Изменить", self)
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        controls.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Удалить", self)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        controls.addWidget(self.delete_btn)
        parent_layout.addLayout(controls)

    # Ярлык типа раздела по constracted — для метки в списке.
    _TYPE_LABEL = {0: "Одиночный", 1: "Физика", 2: "Группа",
                   3: "Тест", 4: "Граф"}

    def _partition_label(self, p: Partition) -> str:
        """Строка раздела в списке: [Тип] Имя (· скрыт)."""
        kind = self._TYPE_LABEL.get(p.constracted)
        prefix = f"[{kind}] " if kind else ""
        suffix = "   · скрыт" if p.hidden else ""
        return f"{prefix}{p.name}{suffix}"

    def _show_content_placeholder(self, text: str) -> None:
        """Показать в правой области центрированную подсказку (пустое состояние)."""
        clear_layout(self.view_layout)
        placeholder = QLabel(text, self.view_holder)
        placeholder.setProperty("class", "empty")
        placeholder.setWordWrap(True)
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view_layout.addWidget(placeholder)

    def showEvent(self, event) -> None:
        # Окно показывается после авторизации — роль сессии уже известна,
        # пересматриваем видимость ролевых кнопок панели (кнопка контура и т.п.).
        super().showEvent(event)
        self.top_bar.refresh_roles()
        self._refresh_sync_badge()

    # ---------- Настройки ----------

    def _open_settings(self) -> None:
        from ui.windows.settings_window import SettingsWindow
        SettingsWindow(self.ctx, self).exec()

    # ---------- Синхронизация ----------

    def _open_sync_window(self) -> None:
        from ui.windows.sync_window import SyncWindow
        if self._sync_window is None:
            self._sync_window = SyncWindow(self.ctx, self)
            self._sync_window.destroyed.connect(self._on_sync_window_destroyed)
        else:
            self._sync_window.refresh()
        self._sync_window.show()
        self._sync_window.raise_()
        self._sync_window.activateWindow()

    def _on_sync_window_destroyed(self, *_args) -> None:
        self._sync_window = None
        self._refresh_sync_badge()

    # ---------- Контур (ИИ-генератор) ----------

    def _open_contour_window(self) -> None:
        from ui.windows.contour_window import ContourWindow
        if self._contour_window is None:
            self._contour_window = ContourWindow(self.ctx, self)
            self._contour_window.partition_created.connect(
                self._on_contour_partition_created)
            self._contour_window.destroyed.connect(
                self._on_contour_window_destroyed)
        else:
            self._contour_window.refresh()
        self._contour_window.show()
        self._contour_window.raise_()
        self._contour_window.activateWindow()

    def _on_contour_partition_created(self, partition_id: int) -> None:
        # Контур создал партицию на сервере (constracted=4). Пересобираем
        # реестр и перечитываем текущий предмет — новый раздел появится,
        # если принадлежит выбранному предмету.
        self._rebuild_registry()
        self._refresh_current_subject(select_partition_id=partition_id)

    def _on_contour_window_destroyed(self, *_args) -> None:
        self._contour_window = None

    # ---------- Администрирование ----------

    def _open_admin_window(self) -> None:
        from ui.windows.admin_window import AdminWindow
        if self._admin_window is None:
            self._admin_window = AdminWindow(self.ctx, self)
            self._admin_window.destroyed.connect(
                self._on_admin_window_destroyed)
        else:
            self._admin_window.refresh()
        self._admin_window.show()
        self._admin_window.raise_()
        self._admin_window.activateWindow()

    def _on_admin_window_destroyed(self, *_args) -> None:
        self._admin_window = None

    # ---------- Аналитика ----------

    def _open_analytics_window(self) -> None:
        from ui.windows.analytics_window import AnalyticsWindow
        if self._analytics_window is None:
            self._analytics_window = AnalyticsWindow(self.ctx, self)
            self._analytics_window.destroyed.connect(
                self._on_analytics_window_destroyed)
        else:
            self._analytics_window.refresh()
        self._analytics_window.show()
        self._analytics_window.raise_()
        self._analytics_window.activateWindow()

    def _on_analytics_window_destroyed(self, *_args) -> None:
        self._analytics_window = None

    # ---------- Домашки ----------

    def _open_homework_window(self) -> None:
        from ui.windows.homework_window import HomeworkWindow
        if self._homework_window is None:
            self._homework_window = HomeworkWindow(self.ctx, self)
            self._homework_window.destroyed.connect(
                self._on_homework_window_destroyed)
        else:
            self._homework_window.refresh()
        self._homework_window.show()
        self._homework_window.raise_()
        self._homework_window.activateWindow()

    def _on_homework_window_destroyed(self, *_args) -> None:
        self._homework_window = None

    def _refresh_sync_badge(self) -> None:
        """Обновить статус-бейдж синка в панели (очередь/конфликты)."""
        if self.ctx.sync_client is None:
            return
        from ui.windows.sync_window import pending_badge_text
        text, level = pending_badge_text(self.ctx.sync_client)
        self.top_bar.set_badge("sync", text, level)

    # ---------- Окно статистики ----------

    def _open_stats_window(self) -> None:
        """
        Открыть окно «Моя статистика». Если уже открыто — выводим на передний
        план и обновляем данные (на случай, если пользователь успел пройти
        ещё один словарь).
        """
        if self.stats_store is None or self.user_id_provider is None:
            return
        if self._stats_window is None:
            self._stats_window = StatsWindow(
                stats_store=self.stats_store,
                user_id_provider=self.user_id_provider,
                words_dir=self.words_dir,
            )
            # При закрытии — забыть ссылку, чтобы следующий клик создал заново
            # и подхватил актуального пользователя (на случай перелогина).
            self._stats_window.destroyed.connect(self._on_stats_window_destroyed)
        else:
            self._stats_window.refresh()
        self._stats_window.show()
        self._stats_window.raise_()
        self._stats_window.activateWindow()

    def _on_stats_window_destroyed(self, *_args) -> None:
        self._stats_window = None

    # ---------- Загрузка данных ----------

    def _show_hidden(self) -> bool:
        return self.show_hidden_cb.isChecked()

    def _owner_scope(self) -> str | None:
        """
        Кого показывать в витрине предметов (list_subjects(owned_by=...)).
        Канонический id пользователя = login (решение об унификации
        идентичности, см. docs/ui_rework_plan.md).
          * admin — None: видит все предметы (управление);
          * гость (login None) — None: локальная витрина, владения нет;
          * teacher/student — свой login: встроенные (owner NULL) + свои.
        Пока все предметы встроенные (owner NULL), фильтр ничего не прячет;
        разграничение оживает, когда сервер начнёт слать владельцев логином.
        """
        role = self.user_role_provider() if self.user_role_provider else None
        uid = self.user_id_provider() if self.user_id_provider else None
        if role == "admin" or uid is None:
            return None
        return uid

    def _load_subjects(self) -> None:
        try:
            self.subjects = self.repo.list_subjects(
                include_hidden=self._show_hidden(),
                owned_by=self._owner_scope())
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД",
                                 f"Не удалось загрузить предметы: {e}")
            return
        self.subject_combo.clear()
        for subj in self.subjects:
            label = f"{subj.name} · скрыт" if subj.hidden else subj.name
            self.subject_combo.addItem(label, subj.id)

    def _on_subject_changed(self, idx: int) -> None:
        if idx < 0:
            return
        subject_id = self.subject_combo.itemData(idx)
        try:
            self.partitions = self.repo.list_partitions_for_subject(
                subject_id, include_hidden=self._show_hidden())
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД",
                                 f"Не удалось загрузить разделы: {e}")
            return
        self.partition_list.clear()
        for p in self.partitions:
            item = QListWidgetItem(self._partition_label(p))
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.partition_list.addItem(item)
        # Пустое состояние списка разделов.
        empty = not self.partitions
        self.partition_list.setVisible(not empty)
        self.partitions_empty.setVisible(empty)
        if empty:
            self.partitions_empty.setText(
                "У этого предмета пока нет разделов." +
                ("\nСоздайте первый кнопкой «+ Создать»."
                 if self.registry_builder is not None else ""))
        self._on_selection_changed()
        # Подпись пункта скрытия — под текущий предмет.
        subj = self._current_subject()
        if subj is not None:
            self._subj_hide_action.setText(
                "Показать предмет" if subj.hidden else "Скрыть предмет")

    def _current_subject(self) -> Subject | None:
        sid = self.subject_combo.currentData()
        for s in self.subjects:
            if s.id == sid:
                return s
        return None

    # ---------- Скрытие/удаление (D3) ----------

    def _on_show_hidden_toggled(self, _checked: bool) -> None:
        """Перезагрузить оба списка, сохранив выбранный предмет, если можно."""
        keep = self.subject_combo.currentData()
        self._load_subjects()
        if keep is not None:
            for i in range(self.subject_combo.count()):
                if self.subject_combo.itemData(i) == keep:
                    self.subject_combo.setCurrentIndex(i)
                    break

    def _on_toggle_subject_hidden(self) -> None:
        subj = self._current_subject()
        if subj is None:
            return
        self.repo.set_subject_hidden(subj.id, not subj.hidden)
        self._on_show_hidden_toggled(self._show_hidden())

    def _on_delete_subject(self) -> None:
        subj = self._current_subject()
        if subj is None:
            return
        n = len(self.repo.list_partitions_for_subject(subj.id,
                                                      include_hidden=True))
        ok = QMessageBox.question(
            self, "Удаление предмета",
            f"Необратимо удалить предмет «{subj.name}» и все его разделы "
            f"({n} шт.)?\n\nВстроенные предметы будут восстановлены при "
            f"следующем запуске приложения — для них уместнее «Скрыть».",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repo.delete_subject(subj.id)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", str(e))
            return
        self._rebuild_registry()
        self._load_subjects()
        self._show_content_placeholder(
            "Выберите раздел слева, чтобы сгенерировать задание.")
        self._refresh_sync_badge()   # удаления ушли в outbox

    def _on_partition_context_menu(self, pos) -> None:
        item = self.partition_list.itemAt(pos)
        if item is None:
            return
        self.partition_list.setCurrentItem(item)
        pid = item.data(Qt.ItemDataRole.UserRole)
        partition = next((p for p in self.partitions if p.id == pid), None)
        if partition is None:
            return
        menu = QMenu(self.partition_list)
        menu.addAction(
            "Показать раздел" if partition.hidden else "Скрыть раздел",
            lambda: self._toggle_partition_hidden(partition))
        if self.registry_builder is not None:
            menu.addSeparator()
            menu.addAction("Удалить раздел…", self._on_delete_clicked)
        menu.exec(self.partition_list.mapToGlobal(pos))

    def _toggle_partition_hidden(self, partition: Partition) -> None:
        self.repo.set_partition_hidden(partition.id, not partition.hidden)
        self._refresh_current_subject()

    def _refresh_current_subject(self, select_partition_id: int | None = None) -> None:
        """Перечитать разделы и при необходимости выделить указанный."""
        idx = self.subject_combo.currentIndex()
        if idx < 0:
            return
        self._on_subject_changed(idx)
        if select_partition_id is not None:
            for i in range(self.partition_list.count()):
                if self.partition_list.item(i).data(Qt.ItemDataRole.UserRole) \
                        == select_partition_id:
                    self.partition_list.setCurrentRow(i)
                    break

    # ---------- Открытие задания ----------

    def _on_partition_clicked(self, item: QListWidgetItem) -> None:
        partition_id = item.data(Qt.ItemDataRole.UserRole)
        partition = self.repo.get_partition(partition_id)
        if partition is None:
            QMessageBox.warning(self, "Ошибка", f"Раздел {partition_id} не найден.")
            return

        try:
            generator = self.registry.get(
                partition_id, partition.generation_params
            )
        except KeyError as e:
            QMessageBox.warning(self, "Не реализовано", str(e))
            return
        except Exception as e:
            QMessageBox.critical(self, "Ошибка",
                                 f"Не удалось создать генератор: {e}")
            return

        view = self._pick_view(generator, self.repo.view_kind_for(partition))
        # Контекст статистики попыток (см. BaseTaskView.attach_stats):
        # используется только теми view, у которых есть проверяемый ответ
        # (сейчас — InteractiveTaskView), остальные его тихо игнорируют.
        view.attach_stats(partition_id=partition_id,
                          sync_client=self.ctx.sync_client)
        clear_layout(self.view_layout)
        self.view_layout.addWidget(view)

    def _pick_view(self, generator: TaskGenerator, view_kind: str) -> QWidget:
        if Capability.INTERACTIVE in generator.capabilities:
            return InteractiveTaskView(generator, self)
        if view_kind == "table":
            return TableTaskView(generator, self)
        if view_kind == "test":
            return TestExportView(generator, self)
        return StaticTaskView(generator, self)

    # ---------- Управление разделами ----------

    def _on_selection_changed(self) -> None:
        if self.registry_builder is None:
            return
        item = self.partition_list.currentItem()
        if item is None:
            self.edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        partition_id = item.data(Qt.ItemDataRole.UserRole)
        partition = self.repo.get_partition(partition_id)
        if partition is None:
            self.edit_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        kind = self.repo.editor_kind_for(partition)
        self.edit_btn.setEnabled(kind is not None)
        self.delete_btn.setEnabled(kind is not None)

    def _open_editor_new(self, kind: str) -> None:
        subject_id = self.subject_combo.currentData()
        if subject_id is None:
            QMessageBox.warning(self, "Внимание", "Сначала выберите предмет.")
            return
        self._open_editor(kind, subject_id, partition_id=None)

    def _on_edit_clicked(self) -> None:
        item = self.partition_list.currentItem()
        if item is None:
            return
        partition_id = item.data(Qt.ItemDataRole.UserRole)
        partition = self.repo.get_partition(partition_id)
        if partition is None:
            return
        kind = self.repo.editor_kind_for(partition)
        if kind is None:
            QMessageBox.information(
                self, "Нет редактора",
                "Этот тип раздела не редактируется через UI."
            )
            return
        self._open_editor(kind, partition.subject_id, partition_id)

    def _on_delete_clicked(self) -> None:
        item = self.partition_list.currentItem()
        if item is None:
            return
        partition_id = item.data(Qt.ItemDataRole.UserRole)
        partition = self.repo.get_partition(partition_id)
        if partition is None:
            return
        ok = QMessageBox.question(
            self, "Удаление",
            f"Удалить раздел «{partition.name}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        try:
            self.repo.delete_partition(partition_id)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД", str(e))
            return
        self._rebuild_registry()
        self._refresh_current_subject()
        self._show_content_placeholder(
            "Выберите раздел слева, чтобы сгенерировать задание.")
        self._refresh_sync_badge()   # удаление ушло в outbox

    def _open_editor(self, kind: str, subject_id: int,
                     partition_id: int | None) -> None:
        try:
            editor = create_editor(
                kind,
                repository=self.repo,
                subject_id=subject_id,
                registry=self.registry,
                partition_id=partition_id,
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть редактор: {e}")
            return

        editor.saved.connect(self._on_editor_saved)
        editor.cancelled.connect(self._on_editor_cancelled)
        editor.setWindowModality(Qt.WindowModality.ApplicationModal)
        editor.show()
        self._editor_window = editor

    def _on_editor_saved(self, partition_id: int) -> None:
        self._rebuild_registry()
        self._refresh_current_subject(select_partition_id=partition_id)
        self._refresh_sync_badge()   # правка ушла в outbox
        if self._editor_window is not None:
            self._editor_window.close()
            self._editor_window = None

    def _on_editor_cancelled(self) -> None:
        if self._editor_window is not None:
            self._editor_window.close()
            self._editor_window = None

    def _rebuild_registry(self) -> None:
        if self.registry_builder is None:
            return
        try:
            self.registry = self.registry_builder()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка пересборки реестра",
                f"Изменения сохранены, но реестр не удалось пересобрать:\n{e}"
            )
