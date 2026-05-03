"""
Адаптеры модуля английского языка.

Два типа генераторов:
  WordsTrainerGenerator — INTERACTIVE-тренажёр перевода слов.
  SentenceFillGenerator — STATIC-задание «вставь пропущенные слова».

Тип определяется по содержимому JSON-файла: dict → words, list → sentences.
"""

from __future__ import annotations
import json
import random
from pathlib import Path
from typing import List

from core import (
    TaskGenerator, InteractiveTask, TurnResult, Capability,
    Block, TextBlock, StaticTask, STATIC_DEFAULT,
    FillInTheBlankBlock,
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
    meta: dict = {}

    def __init__(self, words_dict: dict[str, str], session_size: int = 20):
        keys = list(words_dict.keys())
        if len(keys) > session_size:
            keys = random.sample(keys, session_size)
        self._remaining = {k: words_dict[k] for k in keys}
        self._current: str | None = None

    def _pick_next(self) -> str:
        return random.choice(list(self._remaining.keys()))

    def initial_prompt(self) -> List[Block]:
        if not self._remaining:
            return [TextBlock("Словарь пуст.")]
        self._current = self._pick_next()
        return [
            TextBlock("Переведите на английский:"),
            TextBlock(self._remaining[self._current]),
        ]

    def submit(self, user_input: str) -> TurnResult:
        if self._current is None:
            return TurnResult(False, [TextBlock("Сессия не начата.")], None)
        expected = self._current
        ok = user_input.strip().lower() == expected.lower()
        if ok:
            feedback = [TextBlock(f"Верно: {expected}")]
            self._remaining.pop(expected, None)
        else:
            feedback = [TextBlock(f"Правильный ответ: {expected}")]
        if not self._remaining:
            return TurnResult(ok, feedback, None)
        self._current = self._pick_next()
        return TurnResult(
            ok, feedback,
            [TextBlock("Переведите на английский:"),
             TextBlock(self._remaining[self._current])]
        )

    def is_finished(self) -> bool:
        return not self._remaining


class WordsTrainerGenerator(TaskGenerator):
    capabilities = Capability.INTERACTIVE

    def __init__(self, name: str, words_path, partition_id: int | None = None,
                 session_size: int = 20):
        self.name = name
        self.partition_id = partition_id
        self.words_path = Path(words_path)
        self.session_size = session_size
        self._cache = None

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            data = _read_json_lenient(self.words_path)
            self._cache = self._flatten_words(data)
        return self._cache

    @staticmethod
    def _flatten_words(data) -> dict[str, str]:
        """
        Привести разные форматы словарей к плоскому dict[str, str].

        Поддерживаемые форматы:
          * {"word": "translation", ...}                       — прямой
          * [{"word": "translation"}, ...]                     — список объектов
          * [{"section": {"word": "translation", ...}}, ...]   — секционный
        """
        out: dict[str, str] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    out[k] = v
                elif isinstance(v, dict):
                    # Вложенный словарь — принимаем как есть
                    for k2, v2 in v.items():
                        if isinstance(v2, str):
                            out[k2] = v2
            return out
        if isinstance(data, list):
            for entry in data:
                out.update(WordsTrainerGenerator._flatten_words(entry))
            return out
        return out

    def generate(self) -> InteractiveTask:
        return WordsSession(self._load(), self.session_size)


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
    try:
        data = _read_json_lenient(path)
    except OSError:
        return "unknown"
    if isinstance(data, dict):
        return "words"
    if isinstance(data, list) and data and isinstance(data[0], dict):
        # Признаём sentences по наличию ключа 'template' хотя бы в первом элементе
        if "template" in data[0]:
            return "sentences"
        # Иначе — это словарь в списочной обёртке: WordsTrainerGenerator его сплющит
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
