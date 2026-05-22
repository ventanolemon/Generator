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
    QComboBox, QLabel, QMessageBox, QListWidgetItem, QPushButton,
    QMenu, QToolButton
)

from core import (
    Capability, GeneratorRegistry, Repository, Subject, Partition,
    TaskGenerator, WordStatsStore,
)
from ui.views import (
    StaticTaskView, TableTaskView, InteractiveTaskView, TestExportView
)
from ui.editors import create_editor, PartitionEditor
from ui.utils import clear_layout
from .stats_window import StatsWindow


# Тип фабрики, пересобирающей реестр после изменений в БД.
RegistryBuilder = Callable[[], GeneratorRegistry]
UserIdProvider = Callable[[], Optional[str]]


class GeneratorWindow(QMainWindow):
    """Главное окно: выбор предмета, список разделов, область задания, управление."""

    def __init__(
        self,
        repository: Repository,
        registry: GeneratorRegistry,
        registry_builder: RegistryBuilder | None = None,
        *,
        stats_store: WordStatsStore | None = None,
        user_id_provider: UserIdProvider | None = None,
        words_dir: Path | None = None,
    ):
        """
        registry_builder — опциональная функция, которая пересобирает реестр
        после изменения БД. Без неё кнопки правки/создания не показываются.

        stats_store + user_id_provider — если переданы, в шапке появляется
        кнопка «Моя статистика», открывающая StatsWindow. words_dir нужен
        окну статистики, чтобы рядом с термином показывать перевод.
        """
        super().__init__()
        self.repo = repository
        self.registry = registry
        self.registry_builder = registry_builder
        self.stats_store = stats_store
        self.user_id_provider = user_id_provider
        self.words_dir = words_dir
        self.subjects: list[Subject] = []
        self.partitions: list[Partition] = []
        self._editor_window: PartitionEditor | None = None
        self._stats_window: StatsWindow | None = None

        self.setWindowTitle("Генератор заданий")
        self.resize(1100, 720)
        self._build_ui()
        self._load_subjects()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- Левая панель ----
        left = QVBoxLayout()

        # Кнопка просмотра статистики — только если есть хранилище.
        if self.stats_store is not None:
            self.stats_btn = QPushButton("Моя статистика", self)
            self.stats_btn.setToolTip(
                "История прохождения словарного тренажёра "
                "(межсессионная для авторизованных, "
                "в рамках запуска — для гостей)."
            )
            self.stats_btn.clicked.connect(self._open_stats_window)
            left.addWidget(self.stats_btn)

        left.addWidget(QLabel("Предмет:"))
        self.subject_combo = QComboBox(self)
        left.addWidget(self.subject_combo)

        left.addWidget(QLabel("Разделы:"))
        self.partition_list = QListWidget(self)
        left.addWidget(self.partition_list, stretch=1)

        # Панель управления разделами — только если есть registry_builder
        if self.registry_builder is not None:
            self._build_partition_controls(left)

        left_widget = QWidget(self)
        left_widget.setLayout(left)
        left_widget.setMaximumWidth(300)
        root.addWidget(left_widget)

        # ---- Правая панель ----
        self.view_holder = QWidget(self)
        self.view_layout = QVBoxLayout(self.view_holder)
        root.addWidget(self.view_holder, stretch=1)

        # Сигналы
        self.subject_combo.currentIndexChanged.connect(self._on_subject_changed)
        self.partition_list.itemClicked.connect(self._on_partition_clicked)
        self.partition_list.itemSelectionChanged.connect(self._on_selection_changed)

    def _build_partition_controls(self, parent_layout: QVBoxLayout) -> None:
        """
        Кнопки «Создать», «Изменить», «Удалить» под списком разделов.
        Кнопка «Создать» открывает меню с тремя типами: группа / тест / задача физики.
        """
        controls = QHBoxLayout()

        self.create_btn = QToolButton(self)
        self.create_btn.setText("+ Создать")
        self.create_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        create_menu = QMenu(self.create_btn)
        create_menu.addAction("Группу", lambda: self._open_editor_new("group"))
        create_menu.addAction("Тест",   lambda: self._open_editor_new("test"))
        create_menu.addAction("Задачу по физике",
                              lambda: self._open_editor_new("fisic"))
        self.create_btn.setMenu(create_menu)
        controls.addWidget(self.create_btn)

        self.edit_btn = QPushButton("Изменить", self)
        self.edit_btn.setEnabled(False)
        self.edit_btn.clicked.connect(self._on_edit_clicked)
        controls.addWidget(self.edit_btn)

        self.delete_btn = QPushButton("Удалить", self)
        self.delete_btn.setEnabled(False)
        self.delete_btn.clicked.connect(self._on_delete_clicked)
        controls.addWidget(self.delete_btn)

        parent_layout.addLayout(controls)

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

    def _load_subjects(self) -> None:
        try:
            self.subjects = self.repo.list_subjects()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД",
                                 f"Не удалось загрузить предметы: {e}")
            return
        self.subject_combo.clear()
        for subj in self.subjects:
            self.subject_combo.addItem(subj.name, subj.id)

    def _on_subject_changed(self, idx: int) -> None:
        if idx < 0:
            return
        subject_id = self.subject_combo.itemData(idx)
        try:
            self.partitions = self.repo.list_partitions_for_subject(subject_id)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка БД",
                                 f"Не удалось загрузить разделы: {e}")
            return
        self.partition_list.clear()
        for p in self.partitions:
            item = QListWidgetItem(p.name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.partition_list.addItem(item)
        self._on_selection_changed()

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
        clear_layout(self.view_layout)

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
