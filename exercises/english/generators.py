"""
Адаптеры модуля английского языка.

Два типа генераторов:
  WordsTrainerGenerator — INTERACTIVE-тренажёр перевода слов.
  SentenceFillGenerator — STATIC-задание «вставь пропущенные слова».

Тип определяется по содержимому JSON-файла:
  sentences — list с ключом "template" в первом элементе.
  words     — всё остальное.

Поддерживаемые форматы словарей (words):
  Новый, одиночный юнит:
    {"unit": 1, "title": "...", "vocabulary": [{"term": "...", "translation": "..."}, ...]}
  Новый, объединённый файл:
    {"title": "...", "units": [{"unit": 1, "vocabulary": [...]}, ...]}
  Старый прямой:
    {"word": "translation", ...}
  Старый список объектов:
    [{"word": "translation"}, ...]
  Старый секционный:
    [{"section": {"word": "translation", ...}}, ...]
"""

from __future__ import annotations
import json
import random
from pathlib import Path
from typing import List

from core import (
    TaskGenerator, InteractiveTask, TurnResult, Capability,
    Block, TextBlock, StaticTask, STATIC_DEFAULT,
    FillInTheBlankBlock, WordCorrectionBlock,
)


def _read_json_lenient(path: Path):
    """
    Прочитать JSON, пробуя несколько кодировок. Старые файлы могли
    сохраняться в cp1251.
    """
    for enc in ("utf-8", "utf-8-sig", "cp1251"):
        try:
            with open(path, encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise OSError(f"Не удалось прочитать JSON {path!s}.")


# ---------- WordsTrainerGenerator (INTERACTIVE) ----------

class WordsSession(InteractiveTask):
    """
    Сессия тренировки слов.

    Алгоритм (адаптирован из исходного words_test.py):

      * Пул `_remaining` — все слова, ещё не отгаданные пользователем.
        Сессия идёт, пока пул не опустеет. Лимита на количество вопросов нет.
      * `_last` — FIFO недавно показанных слов (≈ треть пула).
        Алгоритм избегает повторов: новое слово выбирается так, чтобы оно
        не было в `_last`. Когда `_last` переполняется — самое старое слово
        удаляется и снова может попасть в выдачу.
      * `_last_wrong` — недавние ошибки. При переполнении (>5) самое старое
        слово из ошибок удаляется и из `_last`, чтобы быстрее вернуться
        к нему на повторение.
      * При правильном ответе слово удаляется из `_remaining`.
      * При неправильном — остаётся, и его задание увидят снова.
    """

    meta: dict = {}

    def __init__(self, words_dict: dict[str, str]):
        # _remaining: {english: russian}
        self._remaining: dict[str, str] = dict(words_dict)
        self._total: int = len(self._remaining)
        self._current: str | None = None

        # Буферы антиповтора и ошибок (имена и логика — из words_test.py)
        self._last: list[str] = []
        self._last_wrong: list[str] = []

    # ---------- Выбор следующего слова ----------

    def _last_capacity(self) -> int:
        """
        Размер FIFO антиповтора. Точно как в исходнике: len // 3.
        Минимум 3, чтобы при маленьких пулах не зацикливаться.
        """
        return max(3, self._total // 3)

    def _pick_next(self) -> str:
        """
        Выбрать следующее слово, избегая недавно показанных.
        Если в пуле «свежих» слов нет — допускаем повтор.
        """
        # Балансировка last_wrong: при переполнении самое старое из ошибок
        # удаляется из «недавно показанных», чтобы быстрее вернулось.
        if len(self._last_wrong) > 5:
            oldest_wrong = self._last_wrong[0]
            if oldest_wrong in self._last:
                self._last.remove(oldest_wrong)
            self._last_wrong = self._last_wrong[1:]

        all_keys = list(self._remaining.keys())
        # Кандидаты — те, кого нет в недавно показанных
        candidates = [w for w in all_keys if w not in self._last]

        if candidates:
            word = random.choice(candidates)
        else:
            # Все слова в _last — допускаем повтор
            word = random.choice(all_keys)

        # Добавляем в FIFO и подрезаем размер
        self._last.append(word)
        while len(self._last) > self._last_capacity():
            self._last.pop(0)

        return word

    # ---------- InteractiveTask API ----------

    def initial_prompt(self) -> List[Block]:
        if not self._remaining:
            return [TextBlock("Словарь пуст.")]
        self._current = self._pick_next()
        return self._make_prompt_for(self._current)

    def _make_prompt_for(self, word: str) -> List[Block]:
        translation = self._remaining[word]
        return [
            TextBlock("Переведите на английский:"),
            TextBlock(translation),
        ]

    def submit(self, user_input: str) -> TurnResult:
        if self._current is None:
            return TurnResult(False, [TextBlock("Сессия не начата.")], None)

        expected = self._current
        translation = self._remaining[expected]
        user = user_input.strip()
        ok = user.lower() == expected.lower()

        # Feedback с подсветкой ошибок: новый блок WordCorrectionBlock
        feedback: List[Block] = [
            WordCorrectionBlock(
                translation=translation,
                user_answer=user,
                expected=expected,
                correct=ok,
            )
        ]

        if ok:
            self._remaining.pop(expected, None)
        else:
            self._last_wrong.append(expected)
            # Подрезаем буфер ошибок, как в исходнике (но симметрично)
            if len(self._last_wrong) > 6:
                self._last_wrong = self._last_wrong[-5:]

        # Если пул опустел — сессия завершена
        if not self._remaining:
            return TurnResult(ok, feedback, next_prompt=None)

        # Иначе — берём следующее
        self._current = self._pick_next()
        return TurnResult(ok, feedback, self._make_prompt_for(self._current))

    def is_finished(self) -> bool:
        return not self._remaining


class WordsTrainerGenerator(TaskGenerator):
    capabilities = Capability.INTERACTIVE

    def __init__(self, name: str, words_path, partition_id: int | None = None):
        self.name = name
        self.partition_id = partition_id
        self.words_path = Path(words_path)
        self._cache = None

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            data = _read_json_lenient(self.words_path)
            self._cache = self._flatten_words(data)
            # Если имя генератора не задано явно — берём заголовок из JSON
            extracted = self._extract_title(data)
            if extracted and self.name.startswith("Английский:"):
                self.name = extracted
        return self._cache

    @staticmethod
    def _flatten_words(data) -> dict[str, str]:
        """
        Привести разные форматы словарей к плоскому dict[str, str]
        вида {english_term: russian_translation}.

        Новые форматы (проверяются первыми):
          * {"unit": N, "title": "...", "vocabulary": [{"term": "...", "translation": "..."}, ...]}
            — одиночный юнит.
          * {"title": "...", "units": [{"vocabulary": [...]}, ...]}
            — объединённый файл из нескольких юнитов.

        Старые форматы (обратная совместимость):
          * {"word": "translation", ...}                       — прямой
          * [{"word": "translation"}, ...]                     — список объектов
          * [{"section": {"word": "translation", ...}}, ...]   — секционный
        """
        out: dict[str, str] = {}

        if isinstance(data, dict):
            # Новый формат: одиночный юнит — есть ключ "vocabulary" со списком
            if "vocabulary" in data and isinstance(data["vocabulary"], list):
                for entry in data["vocabulary"]:
                    if (isinstance(entry, dict)
                            and "term" in entry
                            and "translation" in entry):
                        term = entry["term"]
                        translation = entry["translation"]
                        if isinstance(term, str) and isinstance(translation, str):
                            out[term] = translation
                return out

            # Новый формат: объединённый файл — есть ключ "units" со списком
            if "units" in data and isinstance(data["units"], list):
                for unit in data["units"]:
                    out.update(WordsTrainerGenerator._flatten_words(unit))
                return out

            # Старый прямой формат: {"word": "translation", ...}
            for k, v in data.items():
                if isinstance(v, str):
                    out[k] = v
                elif isinstance(v, dict):
                    for k2, v2 in v.items():
                        if isinstance(v2, str):
                            out[k2] = v2
            return out

        # Старые форматы: список объектов или секционный список
        if isinstance(data, list):
            for entry in data:
                out.update(WordsTrainerGenerator._flatten_words(entry))
            return out

        return out

    @staticmethod
    def _extract_title(data) -> str | None:
        """
        Извлечь человекочитаемый заголовок из нового формата JSON.
        Возвращает None, если заголовок не найден (старый формат).
        """
        if not isinstance(data, dict):
            return None
        title = data.get("title")
        if not isinstance(title, str) or not title:
            return None
        # Для одиночного юнита добавляем номер: "Unit 3 · Computer Hardware"
        unit_num = data.get("unit")
        if isinstance(unit_num, int):
            return f"Unit {unit_num} · {title}"
        return title

    def generate(self) -> InteractiveTask:
        return WordsSession(self._load())


# ---------- SentenceFillGenerator (STATIC + динамический блок) ----------

class SentenceFillGenerator(TaskGenerator):
    """
    Задание: предложение с пропусками. Использует FillInTheBlankBlock,
    который выводит интерактивные поля ввода прямо в условии задания
    и подсвечивает правильные/неправильные ответы.
    """

    capabilities = STATIC_DEFAULT

    def __init__(self, name: str, sentences_path,
                 partition_id: int | None = None):
        self.name = name
        self.partition_id = partition_id
        self.sentences_path = Path(sentences_path)
        self._cache: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._cache is None:
            self._cache = _read_json_lenient(self.sentences_path)
        return self._cache

    def generate(self) -> StaticTask:
        sentences = self._load()
        if not sentences:
            return StaticTask(
                statement=[TextBlock("Файл предложений пуст.")],
                answer=[],
            )
        item = random.choice(sentences)
        template = item["template"]
        answers = list(item["answers"])
        translation = item.get("translation", "")

        statement: list[Block] = [
            TextBlock("Вставьте пропущенные слова в предложение:"),
            FillInTheBlankBlock(template=template, answers=answers),
        ]
        if translation:
            statement.append(TextBlock(f"Перевод: {translation}"))

        # В ответе — правильно заполненное предложение
        full = template
        for ans in answers:
            full = full.replace(FillInTheBlankBlock.PLACEHOLDER, ans, 1)
        answer: list[Block] = [
            TextBlock("Правильное предложение:"),
            TextBlock(full),
            TextBlock(f"Пропущенные слова: {', '.join(answers)}"),
        ]
        return StaticTask(
            statement=statement, answer=answer,
            meta={"partition_id": self.partition_id},
        )


# ---------- Определение формата ----------

def _detect_kind(path: Path) -> str:
    """
    Определить тип JSON-файла:
      "words"     — словарный тренажёр (новый или старый формат)
      "sentences" — задание с пропусками
      "unknown"   — не удалось распознать

    Новый формат словаря — dict с ключом "vocabulary" или "units".
    Старый формат словаря — dict {word: translation} или list объектов.
    Sentences — list, у первого элемента есть ключ "template".
    """
    try:
        data = _read_json_lenient(path)
    except OSError:
        return "unknown"
    if isinstance(data, dict):
        # Новый формат: одиночный юнит или объединённый файл
        if "vocabulary" in data or "units" in data:
            return "words"
        # Старый прямой формат {"word": "translation"}
        return "words"
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # Sentences — по наличию ключа "template" в первом элементе
        if "template" in data[0]:
            return "sentences"
        # Список объектов — старый словарный формат
        return "words"
    return "unknown"


def english_generators_for_path(
    path: Path, partition_id: int, name: str | None = None
) -> TaskGenerator | None:
    kind = _detect_kind(path)
    display = name or f"Английский: {path.stem}"
    if kind == "words":
        return WordsTrainerGenerator(
            name=display, words_path=path, partition_id=partition_id,
        )
    if kind == "sentences":
        return SentenceFillGenerator(
            name=display, sentences_path=path, partition_id=partition_id,
        )
    return None


def all_generators(words_dir) -> list[TaskGenerator]:
    words_dir = Path(words_dir)
    if not words_dir.exists():
        return []
    out: list[TaskGenerator] = []
    for path in sorted(words_dir.glob("*.json")):
        gen = english_generators_for_path(path, partition_id=0)
        if gen is not None:
            out.append(gen)
    return out