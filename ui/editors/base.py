"""
PartitionEditor — базовый контракт редактора раздела БД.

Редактор — это окно с формой; по «Сохранить» он пишет в Partitions
и эмитит сигнал saved(partition_id). Главное окно перехватывает сигнал
и пересобирает реестр.

Три кита:
  * GroupEditor   — раздел-группа (constracted=2)
  * TestEditor    — раздел-тест (constracted=3)
  * FisicEditor   — конструктор физической задачи (constracted=1)

Все три наследуют PartitionEditor.
"""

from __future__ import annotations
from abc import abstractmethod

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget

from core import Repository


class PartitionEditor(QWidget):
    """
    Базовый редактор раздела.

    Используется в двух режимах:
      * создание нового раздела   — partition_id is None
      * правка существующего      — partition_id is int

    По успешному сохранению эмитит saved(partition_id).
    """

    saved = pyqtSignal(int)         # partition_id (новый или обновлённый)
    cancelled = pyqtSignal()

    def __init__(
        self,
        repository: Repository,
        subject_id: int,
        partition_id: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.repo = repository
        self.subject_id = subject_id
        self.partition_id = partition_id
        self.is_edit_mode = partition_id is not None

    # --- Подклассы реализуют ---

    @abstractmethod
    def load_existing(self) -> None:
        """Заполнить форму данными существующего раздела."""

    @abstractmethod
    def collect_payload(self) -> tuple[str, int, dict | list]:
        """
        Собрать данные для записи. Возвращает кортеж:
          (partition_name, constracted, generation_params)
        Бросает ValueError при ошибке валидации (UI должен показать сообщение).
        """

    # --- Общая логика сохранения ---

    def save(self) -> int | None:
        """Записать раздел в БД и эмитнуть сигнал. Возвращает partition_id или None."""
        try:
            name, constracted, params = self.collect_payload()
        except ValueError as e:
            self._show_error(str(e))
            return None

        try:
            pid = self.repo.upsert_partition(
                subject_id=self.subject_id,
                name=name,
                constracted=constracted,
                generation_params=params,
            )
        except Exception as e:
            self._show_error(f"Ошибка БД: {e}")
            return None

        self.partition_id = pid
        self.saved.emit(pid)
        return pid

    def _show_error(self, message: str) -> None:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Не удалось сохранить", message)
