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
import time
from pathlib import Path
from typing import Callable, List, Optional

from core import (
    TaskGenerator, InteractiveTask, TurnResult, Capability,
    Block, TextBlock, StaticTask, STATIC_DEFAULT,
    FillInTheBlankBlock, WordCorrectionBlock, AudioBlock,
    WordStat, WordStatsStore,
)


# Тип источника текущего user_id. Возвращает строку логина для авторизованного
# пользователя и None/"" для гостя. Передаётся в генератор замыканием — это
# позволяет один и тот же экземпляр генератора переключать пользователя
# (например, при перелогине) без пересоздания реестра.
UserIdProvider = Callable[[], Optional[str]]

# Конфигурация приоритизации в spaced-repetition. Подобрано эмпирически
# и зафиксировано как константы — менять можно через параметры конструктора.
DEFAULT_PRIORITY_RECENT_WRONG = 0.4    # вероятность взять «исторически ошибочное»
WEIGHT_BASE_UNSEEN = 1.0               # вес для слов без истории
WEIGHT_BASE_MASTERED = 0.4             # минимальный вес для уже знакомых
WEIGHT_PER_WRONG = 1.0                 # +1.0 за каждую прошлую ошибку
WEIGHT_PER_CORRECT = 0.3               # -0.3 за каждый правильный ответ
WEIGHT_AGE_DAYS_CAP = 14.0             # потолок «давности»
WEIGHT_AGE_GAIN = 0.15                 # вес единицы дня давности


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


# Глобальный кэш транскрипций — читается один раз за процесс. См.
# tools/generate_transcriptions.py для процесса генерации файла.
_global_transcriptions_cache: dict[str, str] | None = None


def _load_global_transcriptions() -> dict[str, str]:
    """
    Подгрузить общий resources/transcriptions.json (если он существует).
    Возвращает map term → IPA-строка. При отсутствии файла — пустой dict;
    тренажёр в этом случае просто не покажет транскрипции.
    """
    global _global_transcriptions_cache
    if _global_transcriptions_cache is not None:
        return _global_transcriptions_cache
    # Локальный импорт чтобы не тянуть const на верхний уровень модуля
    # (он легковесный, но единый источник пути).
    try:
        from const import TRANSCRIPTIONS_PATH
        if TRANSCRIPTIONS_PATH.exists():
            data = _read_json_lenient(TRANSCRIPTIONS_PATH)
            if isinstance(data, dict):
                _global_transcriptions_cache = {
                    k: v for k, v in data.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
                return _global_transcriptions_cache
    except Exception:
        pass
    _global_transcriptions_cache = {}
    return _global_transcriptions_cache


# Глобальный кэш аудио-манифеста (term → абсолютный путь к WAV).
_global_audio_cache: dict[str, str] | None = None


def _load_global_audio() -> dict[str, str]:
    """
    Подгрузить resources/audio/index.json и развернуть имена файлов в
    абсолютные пути. Возвращает map term → wav-путь. Отсутствие каталога/
    манифеста — пустой dict (тренажёр работает без звука).
    """
    global _global_audio_cache
    if _global_audio_cache is not None:
        return _global_audio_cache
    try:
        from const import AUDIO_DIR
        index_path = AUDIO_DIR / "index.json"
        if index_path.exists():
            data = _read_json_lenient(index_path)
            if isinstance(data, dict):
                _global_audio_cache = {
                    term: str(AUDIO_DIR / fname)
                    for term, fname in data.items()
                    if isinstance(term, str) and isinstance(fname, str)
                    and (AUDIO_DIR / fname).exists()
                }
                return _global_audio_cache
    except Exception:
        pass
    _global_audio_cache = {}
    return _global_audio_cache


def _levenshtein(a: str, b: str) -> int:
    """
    Расстояние Левенштейна — минимальное число односимвольных операций
    (вставка, удаление, замена), переводящих строку a в b.
    Классическая ДП с двумя строками — O(len(a) * len(b)) по времени,
    O(len(b)) по памяти.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,     # вставка
                prev[j] + 1,         # удаление
                prev[j - 1] + cost,  # замена
            )
        prev = curr
    return prev[-1]


def _tolerant_threshold(word: str) -> int:
    """Порог расстояния Левенштейна для слова: 1 при длине ≤ 6, иначе 2."""
    return 1 if len(word) <= 6 else 2


# ---------- WordsTrainerGenerator (INTERACTIVE) ----------

class WordsSession(InteractiveTask):
    """
    Сессия тренировки слов с межсессионной памятью.

    Алгоритм (расширение исходного words_test.py):

      * Пул `_remaining` — все слова, ещё не отгаданные пользователем
        в текущей сессии. Сессия идёт, пока пул не опустеет.
      * `_last` — FIFO недавно показанных слов (≈ треть пула), как и раньше.
      * `_last_wrong` — недавние ошибки текущей сессии, балансирует FIFO.
      * `_stats` — снимок межсессионной статистики из WordStatsStore,
        загружается один раз при старте сессии. Используется только при
        выборе следующего слова (вес = функция от times_wrong, times_correct,
        давности last_seen). На каждом ответе пишется обратно через store.
      * При правильном ответе слово удаляется из `_remaining`;
        при неправильном — остаётся.

    Spaced-repetition поверх «локального» алгоритма:
      * С вероятностью `priority_recent_wrong` следующим словом выбирается
        исторически ошибочное (times_wrong > times_correct ИЛИ когда-либо
        ошибались и не видели давно). Это даёт быстрое возвращение
        проблемных слов в новую сессию, а не только в ту же.
      * Иначе — взвешенный случайный выбор по «приоритетности»:
        давно не виденные и часто ошибочные имеют больше шансов.

    Состояние store: для гостей (user_id == None/'') хранится в памяти
    процесса и обнуляется при перезапуске; для авторизованных — в SQLite.
    """

    meta: dict = {}

    def __init__(
        self,
        words_dict: dict[str, str],
        tolerant: bool = False,
        *,
        stats_store: WordStatsStore | None = None,
        user_id: str | None = None,
        priority_recent_wrong: float = DEFAULT_PRIORITY_RECENT_WRONG,
        transcriptions: dict[str, str] | None = None,
        audio_index: dict[str, str] | None = None,
    ):
        # _remaining: {english: russian}
        self._remaining: dict[str, str] = dict(words_dict)
        self._total: int = len(self._remaining)
        self._current: str | None = None

        # Буферы антиповтора и ошибок (имена и логика — из words_test.py)
        self._last: list[str] = []
        self._last_wrong: list[str] = []

        # Мягкая проверка: ответы с расстоянием Левенштейна ≤ порога
        # засчитываются как правильные. Переключается из GUI на лету.
        self.tolerant: bool = bool(tolerant)

        # Межсессионная статистика
        self._stats_store = stats_store
        self._user_id = user_id
        self._priority_recent_wrong = max(
            0.0, min(1.0, float(priority_recent_wrong))
        )

        # IPA-транскрипции для показа в фидбэке. None / пустой dict —
        # тренажёр работает как раньше, без подсказки произношения.
        self._transcriptions: dict[str, str] = dict(transcriptions or {})

        # Аудио-произношение: term → путь к WAV. Пустой — без кнопки звука.
        self._audio_index: dict[str, str] = dict(audio_index or {})

        # Снимок stats для всех слов словаря. Подгружаем один раз —
        # дальше держим в памяти и обновляем после submit, параллельно
        # пробрасывая в store.
        self._stats: dict[str, WordStat] = {}
        if self._stats_store is not None and self._remaining:
            self._stats = self._stats_store.fetch(
                self._user_id, list(self._remaining.keys())
            )

    # ---------- Выбор следующего слова ----------

    def _last_capacity(self) -> int:
        """
        Размер FIFO антиповтора. Точно как в исходнике: len // 3.
        Минимум 3, чтобы при маленьких пулах не зацикливаться.
        """
        return max(3, self._total // 3)

    def _word_weight(self, term: str) -> float:
        """
        Приоритет слова для следующего выбора. Чем выше — тем чаще выпадает.
        Используется только для слов из `_remaining`.
        """
        stat = self._stats.get(term)
        if stat is None or stat.times_shown == 0:
            return WEIGHT_BASE_UNSEEN

        wrong = max(0, stat.times_wrong)
        correct = max(0, stat.times_correct)
        weight = (
            WEIGHT_BASE_MASTERED
            + WEIGHT_PER_WRONG * wrong
            - WEIGHT_PER_CORRECT * correct
        )

        # Бонус за давность (только если когда-то видели)
        if stat.last_seen > 0:
            age_days = max(0.0, (time.time() - stat.last_seen) / 86400.0)
            weight += min(age_days, WEIGHT_AGE_DAYS_CAP) * WEIGHT_AGE_GAIN

        # Не позволяем весу уйти в ноль/отрицательное — выбор всё равно
        # должен быть возможен. Минимальный пол — четверть базы.
        return max(WEIGHT_BASE_MASTERED * 0.25, weight)

    def _historically_wrong(self, pool: list[str]) -> list[str]:
        """
        Слова из пула, которые в истории чаще ошибались, чем угадывались
        (или ошибались и давно не виделись). Используется при бросании
        кубика `priority_recent_wrong`.
        """
        out: list[str] = []
        now = time.time()
        for term in pool:
            stat = self._stats.get(term)
            if stat is None or stat.times_wrong == 0:
                continue
            if stat.times_wrong >= stat.times_correct:
                out.append(term)
                continue
            # Ошибались, но в целом справлялись — добавляем если давно не виделись
            if stat.last_seen > 0 and (now - stat.last_seen) > 3 * 86400:
                out.append(term)
        return out

    def _pick_next(self) -> str:
        """
        Выбрать следующее слово, избегая недавно показанных, с учётом
        межсессионной статистики.
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
        if not candidates:
            candidates = all_keys  # все «свежие» закончились — допускаем повтор

        word: str | None = None

        # С вероятностью priority_recent_wrong — пытаемся взять исторически ошибочное
        if self._stats and self._priority_recent_wrong > 0.0 \
                and random.random() < self._priority_recent_wrong:
            wrong_pool = self._historically_wrong(candidates)
            if wrong_pool:
                word = random.choice(wrong_pool)

        # Иначе — взвешенный случайный выбор по приоритетности
        if word is None:
            if self._stats:
                weights = [self._word_weight(w) for w in candidates]
                # random.choices безопасен на положительных весах
                word = random.choices(candidates, weights=weights, k=1)[0]
            else:
                word = random.choice(candidates)

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

        strict_ok = user.lower() == expected.lower()
        # tolerant_accept — приняли благодаря мягкому режиму, посимвольно не равно.
        tolerant_accept = False
        if self.tolerant and not strict_ok and user:
            distance = _levenshtein(user.lower(), expected.lower())
            tolerant_accept = distance <= _tolerant_threshold(expected)
        ok = strict_ok or tolerant_accept

        # Feedback с подсветкой ошибок: новый блок WordCorrectionBlock
        feedback: List[Block] = [
            WordCorrectionBlock(
                translation=translation,
                user_answer=user,
                expected=expected,
                correct=ok,
                tolerant_accept=tolerant_accept,
                transcription=self._transcriptions.get(expected),
            )
        ]
        # Кнопка прослушивания произношения — если для слова есть аудио.
        audio_path = self._audio_index.get(expected)
        if audio_path:
            feedback.append(AudioBlock(audio_path, label=f"Прослушать «{expected}»"))

        # Обновляем межсессионную статистику (и снимок в памяти, и store).
        self._record_stat(expected, ok)

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

    # ---------- Stats ----------

    def _record_stat(self, term: str, correct: bool) -> None:
        """Обновить in-memory снимок и пробросить в store (если задан)."""
        now = time.time()
        stat = self._stats.get(term)
        if stat is None:
            stat = WordStat(term=term)
            self._stats[term] = stat
        stat.times_shown += 1
        if correct:
            stat.times_correct += 1
        else:
            stat.times_wrong += 1
        stat.last_seen = now

        if self._stats_store is not None:
            self._stats_store.record(self._user_id, term, correct, now)


class WordsTrainerGenerator(TaskGenerator):
    capabilities = Capability.INTERACTIVE

    def __init__(
        self,
        name: str,
        words_path,
        partition_id: int | None = None,
        *,
        stats_store: WordStatsStore | None = None,
        user_id_provider: UserIdProvider | None = None,
        priority_recent_wrong: float = DEFAULT_PRIORITY_RECENT_WRONG,
    ):
        self.name = name
        self.partition_id = partition_id
        self.words_path = Path(words_path)
        self._cache = None
        # Состояние мягкой проверки. Хранится на генераторе, чтобы при
        # рестарте сессии (кнопка «Заново») значение из GUI сохранялось.
        self.tolerant: bool = False

        # Межсессионная статистика. user_id берётся через провайдер
        # на момент generate(), чтобы тот же экземпляр генератора корректно
        # обслуживал разные пользователи в течение жизни приложения.
        self.stats_store = stats_store
        self.user_id_provider = user_id_provider
        self.priority_recent_wrong = priority_recent_wrong

    def _load(self) -> dict[str, str]:
        if self._cache is None:
            data = _read_json_lenient(self.words_path)
            self._cache = self._flatten_words(data)
            self._cache_inline_transcriptions = self._extract_transcriptions(data)
            # Если имя генератора не задано явно — берём заголовок из JSON
            extracted = self._extract_title(data)
            if extracted and self.name.startswith("Английский:"):
                self.name = extracted
        return self._cache

    def _resolved_transcriptions(self) -> dict[str, str]:
        """
        Финальная карта term → IPA для текущего словаря: глобальный файл
        перекрывается inline-полями `"transcription"` из vocab JSON.
        """
        merged: dict[str, str] = dict(_load_global_transcriptions())
        merged.update(getattr(self, "_cache_inline_transcriptions", {}) or {})
        # Оставляем только те термины, что реально есть в текущем словаре
        words = self._cache or {}
        return {t: ipa for t, ipa in merged.items() if t in words}

    def _resolved_audio(self) -> dict[str, str]:
        """
        Карта term → путь к WAV для слов текущего словаря (из общего
        манифеста resources/audio/index.json). Пустая, если аудио не собрано.
        """
        audio = _load_global_audio()
        words = self._cache or {}
        return {t: path for t, path in audio.items() if t in words}

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
    def _extract_transcriptions(data) -> dict[str, str]:
        """
        Достать inline-поля `"transcription"` из любого поддерживаемого
        формата vocab JSON. Возвращает только то, что явно прописано в
        самом словаре; глобальная таблица из resources/transcriptions.json
        накладывается отдельно в _resolved_transcriptions().

        Старые форматы без структуры vocabulary/term — возвращают пустой dict.
        """
        out: dict[str, str] = {}
        if isinstance(data, dict):
            if "vocabulary" in data and isinstance(data["vocabulary"], list):
                for entry in data["vocabulary"]:
                    if (isinstance(entry, dict)
                            and isinstance(entry.get("term"), str)
                            and isinstance(entry.get("transcription"), str)
                            and entry["transcription"]):
                        out[entry["term"]] = entry["transcription"]
                return out
            if "units" in data and isinstance(data["units"], list):
                for unit in data["units"]:
                    out.update(
                        WordsTrainerGenerator._extract_transcriptions(unit)
                    )
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
        user_id: str | None = None
        if self.user_id_provider is not None:
            try:
                user_id = self.user_id_provider()
            except Exception:
                user_id = None
        words = self._load()
        return WordsSession(
            words,
            tolerant=self.tolerant,
            stats_store=self.stats_store,
            user_id=user_id,
            priority_recent_wrong=self.priority_recent_wrong,
            transcriptions=self._resolved_transcriptions(),
            audio_index=self._resolved_audio(),
        )


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
    path: Path,
    partition_id: int,
    name: str | None = None,
    *,
    stats_store: WordStatsStore | None = None,
    user_id_provider: UserIdProvider | None = None,
) -> TaskGenerator | None:
    kind = _detect_kind(path)
    display = name or f"Английский: {path.stem}"
    if kind == "words":
        return WordsTrainerGenerator(
            name=display, words_path=path, partition_id=partition_id,
            stats_store=stats_store, user_id_provider=user_id_provider,
        )
    if kind == "sentences":
        return SentenceFillGenerator(
            name=display, sentences_path=path, partition_id=partition_id,
        )
    return None


def all_generators(
    words_dir,
    *,
    stats_store: WordStatsStore | None = None,
    user_id_provider: UserIdProvider | None = None,
) -> list[TaskGenerator]:
    words_dir = Path(words_dir)
    if not words_dir.exists():
        return []
    out: list[TaskGenerator] = []
    for path in sorted(words_dir.glob("*.json")):
        gen = english_generators_for_path(
            path, partition_id=0,
            stats_store=stats_store, user_id_provider=user_id_provider,
        )
        if gen is not None:
            out.append(gen)
    return out