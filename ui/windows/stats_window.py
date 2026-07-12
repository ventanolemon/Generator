"""
StatsWindow — окно просмотра истории прохождения словарного тренажёра.

Показывает сводку (всего слов, правильных, ошибок, точность) и таблицу
со счётчиками times_shown / times_correct / times_wrong и временем
последнего показа для каждого слова.

Работает и для авторизованных пользователей (данные из SQLite), и для
гостей (in-memory bucket). Источник user_id — провайдер, передаваемый
из главного окна, поэтому при перелогине окно само возьмёт правильные
данные при следующем открытии.

Окно не модальное и не самообновляющееся: данные снимаются один раз
при показе (Refresh — кнопка). Это сознательно: сессия тренажёра может
писать в store параллельно, и постоянный поллинг здесь ни к чему.
"""

from __future__ import annotations
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QAbstractItemView, QSizePolicy,
)

from core import WordStat, WordStatsStore


# Цвета строк в зависимости от качества знания слова.
# Подобраны мягкими, чтобы текст оставался читаемым.
COLOR_MASTERED = QColor("#e6f4ea")   # зелёный — точность ≥ 0.8 и хоть раз правильно
COLOR_PROBLEM = QColor("#fce8e6")    # красный — точность < 0.5 или wrong >= correct
COLOR_NEUTRAL = QColor("#fff8e1")    # жёлтый — посередине

# Подложки выше — светлые пастельные; в тёмной теме глобальный цвет текста
# светлый, поэтому подкрашенным ячейкам явно задаём тёмный текст.
COLOR_TINTED_TEXT = QColor("#1F2328")


class _NumericItem(QTableWidgetItem):
    """
    Ячейка с произвольным текстом для отображения и числовым ключом
    для сортировки. По умолчанию QTableWidget сортирует по тексту
    DisplayRole — здесь сравниваем по UserRole, чтобы «60%» < «100%»
    и «5 мин назад» < «2 дн назад».
    """

    def __lt__(self, other):  # type: ignore[override]
        try:
            return float(self.data(Qt.ItemDataRole.UserRole)) < \
                   float(other.data(Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return super().__lt__(other)


class StatsWindow(QWidget):
    """Окно «Моя статистика»: сводка + таблица WordStats."""

    # Колонки таблицы
    COLUMNS = ("Слово", "Перевод", "Показов", "Верно", "Ошибок",
               "Точность", "Последний раз")

    def __init__(
        self,
        stats_store: WordStatsStore,
        user_id_provider: Callable[[], Optional[str]],
        words_dir: Path | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._store = stats_store
        self._user_id_provider = user_id_provider
        self._words_dir = Path(words_dir) if words_dir else None

        # term → translation, подгружается лениво при первом показе
        self._translations: dict[str, str] | None = None

        self.setWindowTitle("Моя статистика")
        self.resize(820, 560)
        self._build_ui()
        self.refresh()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # Заголовок с именем пользователя
        self.user_label = QLabel("", self)
        self.user_label.setProperty("class", "title")
        root.addWidget(self.user_label)

        # Сводка одной строкой
        self.summary_label = QLabel("", self)
        self.summary_label.setProperty("class", "subtitle")
        root.addWidget(self.summary_label)

        # Панель управления: поиск + обновление
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Поиск:", self))
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("часть слова или перевода…")
        self.search_edit.textChanged.connect(self._apply_filter)
        controls.addWidget(self.search_edit, stretch=1)

        self.refresh_btn = QPushButton("Обновить", self)
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)

        self.close_btn = QPushButton("Закрыть", self)
        self.close_btn.clicked.connect(self.close)
        controls.addWidget(self.close_btn)
        root.addLayout(controls)

        # Таблица
        self.table = QTableWidget(0, len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, len(self.COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        root.addWidget(self.table, stretch=1)

        # Заглушка для пустой статистики
        self.empty_label = QLabel(
            "Статистика пока пуста. Пройдите словарный диктант — "
            "тут появятся ваши успехи и ошибки.",
            self,
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setProperty("class", "muted")
        self.empty_label.hide()
        root.addWidget(self.empty_label)

    # ---------- Загрузка данных ----------

    def refresh(self) -> None:
        """Перечитать статистику для текущего пользователя и заполнить таблицу."""
        user_id = self._user_id_provider() if self._user_id_provider else None

        if user_id:
            self.user_label.setText(f"Моя статистика — {user_id}")
        else:
            self.user_label.setText(
                "Моя статистика — гость (сохраняется только до перезапуска)"
            )

        stats = self._store.fetch_all(user_id)
        translations = self._get_translations()

        # Сводка
        total_terms = len(stats)
        total_shown = sum(s.times_shown for s in stats)
        total_correct = sum(s.times_correct for s in stats)
        total_wrong = sum(s.times_wrong for s in stats)
        denom = total_correct + total_wrong
        accuracy = (total_correct / denom * 100.0) if denom > 0 else 0.0
        self.summary_label.setText(
            f"Слов в статистике: {total_terms}  •  "
            f"Показов всего: {total_shown}  •  "
            f"Верно: {total_correct}  •  Ошибок: {total_wrong}  •  "
            f"Точность: {accuracy:.1f}%"
        )

        # Заполняем таблицу
        # Сортировку временно отключаем, иначе строки прыгают по ходу вставки
        # (QTableWidget сортирует на лету при setItem).
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for stat in stats:
            self._add_row(stat, translations.get(stat.term, ""))
        self.table.setSortingEnabled(True)

        # Пустая статистика: показываем плейсхолдер вместо таблицы
        is_empty = total_terms == 0
        self.table.setVisible(not is_empty)
        self.empty_label.setVisible(is_empty)

        self._apply_filter()

    def _add_row(self, stat: WordStat, translation: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        denom = stat.times_correct + stat.times_wrong
        accuracy = (stat.times_correct / denom) if denom > 0 else 0.0
        accuracy_pct = f"{accuracy * 100:.0f}%" if denom > 0 else "—"
        last_seen_str = self._format_last_seen(stat.last_seen)

        # (display_text, sort_key, numeric?). Численные ячейки сортируются
        # через _NumericItem по UserRole; текстовые — стандартно по DisplayRole.
        cells = [
            (stat.term, None, False),
            (translation, None, False),
            (str(stat.times_shown), float(stat.times_shown), True),
            (str(stat.times_correct), float(stat.times_correct), True),
            (str(stat.times_wrong), float(stat.times_wrong), True),
            (accuracy_pct, float(accuracy) if denom > 0 else -1.0, True),
            (last_seen_str, float(stat.last_seen), True),
        ]

        bg = self._row_color(stat, accuracy, denom)

        for col, (display, sort_key, numeric) in enumerate(cells):
            if numeric:
                item = _NumericItem(display)
                item.setData(Qt.ItemDataRole.UserRole, sort_key)
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            else:
                item = QTableWidgetItem(display)
            if bg is not None:
                item.setBackground(QBrush(bg))
                item.setForeground(QBrush(COLOR_TINTED_TEXT))
            self.table.setItem(row, col, item)

    @staticmethod
    def _row_color(stat: WordStat, accuracy: float, denom: int):
        if denom == 0:
            return None  # не отвечали ни разу — нейтрально
        if stat.times_wrong >= stat.times_correct or accuracy < 0.5:
            return COLOR_PROBLEM
        if accuracy >= 0.8:
            return COLOR_MASTERED
        return COLOR_NEUTRAL

    @staticmethod
    def _format_last_seen(ts: float) -> str:
        """Дружелюбное «X дней назад» или дата для давних показов."""
        if ts <= 0:
            return "—"
        now = time.time()
        delta = max(0.0, now - ts)
        if delta < 60:
            return "только что"
        if delta < 3600:
            return f"{int(delta // 60)} мин назад"
        if delta < 86400:
            return f"{int(delta // 3600)} ч назад"
        if delta < 7 * 86400:
            return f"{int(delta // 86400)} дн назад"
        # Старше недели — конкретная дата
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))

    # ---------- Фильтр поиска ----------

    def _apply_filter(self) -> None:
        needle = self.search_edit.text().strip().lower()
        for row in range(self.table.rowCount()):
            term_item = self.table.item(row, 0)
            trans_item = self.table.item(row, 1)
            term = term_item.text().lower() if term_item else ""
            trans = trans_item.text().lower() if trans_item else ""
            visible = (not needle) or (needle in term) or (needle in trans)
            self.table.setRowHidden(row, not visible)

    # ---------- Загрузка переводов ----------

    def _get_translations(self) -> dict[str, str]:
        """
        Сводный term→translation по всем словарям из WORDS_DIR.
        Кэшируется на время жизни окна — словари в рантайме не меняются.
        """
        if self._translations is not None:
            return self._translations

        out: dict[str, str] = {}
        if self._words_dir is None or not self._words_dir.exists():
            self._translations = out
            return out

        # Локальный импорт, чтобы не тянуть exercises в core/ui без нужды.
        from exercises.english.generators import (
            WordsTrainerGenerator, _read_json_lenient, _detect_kind,
        )
        for path in sorted(self._words_dir.glob("*.json")):
            try:
                if _detect_kind(path) != "words":
                    continue
                data = _read_json_lenient(path)
                out.update(WordsTrainerGenerator._flatten_words(data))
            except Exception:
                continue
        self._translations = out
        return out
