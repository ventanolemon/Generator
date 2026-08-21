"""
Произношение в упражнениях: словарный тренажёр и выбор транскрипции.

Главное правило здесь одно и оно не про код: **произношение показывается
в РАЗБОРЕ, а не в задании**. Озвученное английское слово в условии — это
подсказка к переводу, который и спрашивают; транскрипция — то же слово
другой записью. Показать их до ответа значит отменить задание.

Отсюда и построение проверок: сначала убеждаемся, что в условии их нет,
и только потом — что в разборе они есть.

Запуск:
    python -m unittest tests.test_english_pronunciation
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core import pronunciation
from core.dynamic_blocks import (
    AudioBlock, TranscriptionChoiceBlock, WordCorrectionBlock,
)
from exercises.english.generators import (
    TranscriptionChoiceGenerator, WordsSession, WordsTrainerGenerator,
)
from tests.tmpdb import temp_path  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORDS_DIR = ROOT / "resources" / "words"


def _a_dictionary() -> pathlib.Path:
    """Поставочный словарь, в котором есть и звук, и транскрипции."""
    for path in sorted(WORDS_DIR.glob("*.json")):
        from exercises.english.generators import _detect_kind
        if _detect_kind(path) != "words":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            words = WordsTrainerGenerator._flatten_words(data)
        except Exception:                       # noqa: BLE001
            continue
        covered = [t for t in words
                   if pronunciation.transcription_of(t)
                   and pronunciation.audio_of(t)]
        if len(covered) >= 4:
            return path
    raise unittest.SkipTest("в поставке нет подходящего словаря")


class TrainerFeedbackTests(unittest.TestCase):

    def setUp(self):
        self.path = _a_dictionary()
        self.generator = WordsTrainerGenerator(
            name="Английский: проверка", words_path=self.path, partition_id=1)

    def _covered_session(self) -> tuple[WordsSession, str, str]:
        """Сессия из одного слова, у которого есть и звук, и транскрипция."""
        words = self.generator._load()
        term = next(t for t in words
                    if pronunciation.transcription_of(t)
                    and pronunciation.audio_of(t))
        session = WordsSession({term: words[term]})
        session.initial_prompt()
        return session, term, words[term]

    def test_prompt_does_not_leak_the_pronunciation(self):
        """
        Сердцевина. Звук и транскрипция в условии — подсказка к ответу.
        """
        session, term, _translation = self._covered_session()
        prompt_text = " ".join(b.render_plain() for b in session.initial_prompt())
        self.assertNotIn(term, prompt_text)
        self.assertNotIn(pronunciation.transcription_of(term), prompt_text)
        for block in session.initial_prompt():
            self.assertNotIsInstance(block, AudioBlock)

    def test_feedback_carries_the_sound(self):
        session, term, _ = self._covered_session()
        feedback = session.submit("заведомо неверно").feedback
        sounds = [b for b in feedback if isinstance(b, AudioBlock)]
        self.assertEqual(len(sounds), 1)
        self.assertEqual(sounds[0].resource, pronunciation.audio_of(term))

    def test_feedback_carries_the_transcription(self):
        session, term, _ = self._covered_session()
        card = next(b for b in session.submit("неверно").feedback
                    if isinstance(b, WordCorrectionBlock))
        self.assertEqual(card.transcription,
                         pronunciation.transcription_of(term))
        self.assertIn(card.transcription, card.render_plain())

    def test_correct_answer_still_shows_the_transcription(self):
        """
        Написал верно — строки «ответ» нет, но как слово ЗВУЧИТ, из
        английского написания по-прежнему не следует.
        """
        session, term, _ = self._covered_session()
        result = session.submit(term)
        self.assertTrue(result.correct)
        card = next(b for b in result.feedback
                    if isinstance(b, WordCorrectionBlock))
        self.assertEqual(card.transcription,
                         pronunciation.transcription_of(term))

    def test_a_word_without_audio_simply_has_no_button(self):
        session = WordsSession({"совершенно выдуманное слово": "перевод"})
        session.initial_prompt()
        feedback = session.submit("мимо").feedback
        self.assertFalse([b for b in feedback if isinstance(b, AudioBlock)])

    def test_inline_transcription_wins_in_the_session(self):
        session, term, translation = self._covered_session()
        own = WordsSession({term: translation},
                           inline_transcriptions={term: "/моя запись/"})
        own.initial_prompt()
        card = next(b for b in own.submit("мимо").feedback
                    if isinstance(b, WordCorrectionBlock))
        self.assertEqual(card.transcription, "/моя запись/")

    def test_web_form_carries_both(self):
        """Веб получает те же данные, а не «то же, но без звука»."""
        session, term, _ = self._covered_session()
        blocks = [b.to_dict() for b in session.submit("мимо").feedback
                  if hasattr(b, "to_dict")]
        kinds = {b["type"] for b in blocks}
        self.assertIn("audio", kinds)
        card = next(b for b in blocks if b["type"] == "word_correction")
        self.assertEqual(card["transcription"],
                         pronunciation.transcription_of(term))


class TranscriptionChoiceTests(unittest.TestCase):

    def setUp(self):
        self.generator = TranscriptionChoiceGenerator(
            name="Английский: проверка (транскрипция)",
            words_path=_a_dictionary(), partition_id=2)

    def test_task_offers_several_options_one_of_which_is_right(self):
        task = self.generator.generate()
        block = task.statement[0]
        self.assertIsInstance(block, TranscriptionChoiceBlock)
        self.assertGreaterEqual(len(block.options), 2)
        self.assertEqual(block.options[block.correct_index], block.correct)

    def test_the_right_option_is_the_transcription_of_the_term(self):
        block = self.generator.generate().statement[0]
        self.assertEqual(
            block.correct,
            pronunciation.transcription_of(block.term, self.generator._inline))

    def test_options_are_all_different(self):
        """Два одинаковых варианта делают задание неразрешимым."""
        for _ in range(20):
            block = self.generator.generate().statement[0]
            with self.subTest(термин=block.term):
                self.assertEqual(len(set(block.options)), len(block.options))

    def test_distractors_are_comparable_in_length(self):
        """
        Без фильтра по длине ответ виден, не читая: короткая строка среди
        трёх длинных опознаётся по форме.
        """
        for _ in range(20):
            block = self.generator.generate().statement[0]
            lengths = [len(o) for o in block.options]
            with self.subTest(термин=block.term):
                self.assertLessEqual(max(lengths), min(lengths) * 4)

    def test_options_do_not_reshuffle_between_renders(self):
        block = self.generator.generate().statement[0]
        first = list(block.options)
        block.render_plain()
        block.render_plain()
        self.assertEqual(block.options, first)

    def test_answer_names_the_term_and_may_carry_the_sound(self):
        task = self.generator.generate()
        text = " ".join(b.render_plain() for b in task.answer)
        self.assertIn(task.statement[0].term, text)

    def test_dictionary_without_transcriptions_says_so_instead_of_failing(self):
        empty = pathlib.Path(tempfile.mkdtemp()) / "пусто.json"
        empty.write_text(json.dumps({"выдуманное": "слово"},
                                    ensure_ascii=False), encoding="utf-8")
        generator = TranscriptionChoiceGenerator(
            name="пусто", words_path=empty, partition_id=3)
        task = generator.generate()
        self.assertIn("нет терминов", task.statement[0].render_plain())

    def test_choice_is_counted_once(self):
        """Повторный клик не должен считаться вторым ответом."""
        seen: list[bool] = []
        block = TranscriptionChoiceBlock(
            "cat", "/kæt/", ["/dɒɡ/", "/faɪl/"], on_answer=seen.append)
        from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
        app = QApplication.instance() or QApplication([])   # noqa: F841
        # Родителя держим: без ссылки он собирается вместе с потомками,
        # и виджет оказывается удалён на стороне C++.
        parent = QWidget()
        widget = block.render_qt(parent)
        buttons = widget.findChildren(QPushButton)
        buttons[block.correct_index].click()
        buttons[block.correct_index].click()
        self.assertEqual(seen, [True])


class SectionRegistrationTests(unittest.TestCase):
    """Разбор транскрипции — отдельный раздел, рядом со словарём."""

    def test_it_gets_its_own_band_of_numbers(self):
        from core import partition_ids
        stem = "term_4_unit1_internet"
        self.assertIn(partition_ids.english_words_id(stem),
                      partition_ids.ENGLISH_WORDS)
        self.assertIn(partition_ids.english_transcription_id(stem),
                      partition_ids.ENGLISH_TRANSCRIPTION)

    def test_both_sections_appear_and_both_open(self):
        import warnings

        from const import DB_TEMPLATE as DB_PATH
        import shutil

        import bootstrap
        from core import Repository

        copy = temp_path(suffix=".db")
        shutil.copyfile(DB_PATH, copy)
        self.addCleanup(lambda: os.path.exists(copy) and os.unlink(copy))
        repo = Repository(copy)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bootstrap.sync_database(repo, WORDS_DIR)
            registry = bootstrap.build_registry(repo, WORDS_DIR)

        names = [p.name for p in repo.list_partitions_for_subject(2)]
        self.assertTrue([n for n in names if n.endswith("(транскрипция)")])
        self.assertEqual(bootstrap.unserved_partitions(repo, registry), [])

    def test_a_dictionary_without_transcriptions_gets_no_second_section(self):
        import bootstrap
        empty = pathlib.Path(tempfile.mkdtemp()) / "пусто.json"
        empty.write_text(json.dumps({"выдуманное": "слово"},
                                    ensure_ascii=False), encoding="utf-8")
        self.assertFalse(bootstrap._has_transcriptions(empty))


if __name__ == "__main__":
    unittest.main()
