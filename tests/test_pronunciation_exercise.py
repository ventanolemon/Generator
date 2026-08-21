"""
Десктопная половина задания на произношение: захват звука и ввод голосом.

Что проверяется здесь, а что в ядре
-----------------------------------
Правило приёма и спецификация ответа — общие, они проверены в
`core/test_voice_answer.py` и `core/test_pronunciation_match.py`. Здесь
проверяется то, что есть только у десктопа:

* превращение отсчётов устройства в WAV, который прочитает проверка;
* подмена способа ввода: поле ввода → кнопка записи;
* попадание попытки в статистику БЕЗ самой записи;
* появление раздела в списке.

Чего эти тесты НЕ проверяют
---------------------------
**Самого захвата с микрофона.** `QAudioSource` требует звукового
устройства, которого в проверке нет (в этом окружении не грузится и
QtMultimedia — нет `libpulse.so.0`). Поэтому разделение в
`ui/audio_recorder.py` не косметическое: опасная часть — перевод отсчётов
в файл — вынесена в обычные функции и проверяется прогоном, а работа с
устройством остаётся непокрытой, и сказано об этом прямо.

Запуск:
    QT_QPA_PLATFORM=offscreen python -m unittest tests.test_pronunciation_exercise
"""

from __future__ import annotations

import pathlib
import unittest

import numpy as np

from PyQt6.QtWidgets import QApplication

from core import pronunciation as P
from core import pronunciation_match as M
from core.answers import CheckMode, Reason, VoiceSpec
from core.graph.resources import resolve
from core.interactive import SolvingGenerator
from exercises.english.generators import PronunciationGenerator
from ui.audio_recorder import to_mono_int16, write_wav
from ui.views.checkable_view import CheckableTaskView
from ui.views.interactive_view import InteractiveTaskView
from tests.tmpdb import temp_path  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _dictionary_with_audio() -> pathlib.Path:
    for path in sorted(pathlib.Path("resources/words").glob("*.json")):
        if PronunciationGenerator("x", path)._load():
            return path
    raise unittest.SkipTest("нет словаря с готовым звуком")


def _generator() -> PronunciationGenerator:
    return PronunciationGenerator(name="Английский: произношение",
                                  words_path=_dictionary_with_audio(),
                                  partition_id=3_000_001)


def _recording_of(term: str) -> pathlib.Path:
    """
    КОПИЯ эталона во временном файле — то, чем притворяется запись.

    Именно копия, а не сам эталон. Первая версия этих тестов подставляла
    виджету поставочный файл, и очистка после ответа стёрла восемь WAV из
    `resources/audio/`. Заслон с тех пор есть и в самом виджете
    (`VoiceRecorder.discard` удаляет только то, что создал сам), но
    подсовывать проверке поставку незачем и при заслоне.
    """
    source = pathlib.Path(resolve(P.audio_of(term)))
    copy = pathlib.Path(temp_path(".wav"))
    copy.write_bytes(source.read_bytes())
    return copy


class CaptureConversionTests(unittest.TestCase):
    """
    Отсчёты устройства → WAV, который читает проверка.

    Самое опасное место всей десктопной половины, потому что ошибка здесь
    МОЛЧАЛИВАЯ: файл получится, откроется и будет содержать шум вместо
    голоса. Никакого исключения при этом не возникнет — просто вердикт
    станет случайным.
    """

    def _round_trip(self, signal: np.ndarray, *, sample_format: str,
                    channels: int, raw: bytes) -> np.ndarray:
        pcm = to_mono_int16(raw, sample_format=sample_format,
                            channels=channels)
        path = pathlib.Path(temp_path(".wav"))
        self.addCleanup(path.unlink)
        write_wav(path, pcm, M.TARGET_RATE)
        back, rate = M.read_wav(path)
        self.assertEqual(rate, M.TARGET_RATE)
        return back

    def test_int16_survives_the_round_trip(self):
        wave_form = np.sin(np.linspace(0, 40 * np.pi, 2000)) * 0.5
        raw = (wave_form * 32767).astype(np.int16).tobytes()
        back = self._round_trip(wave_form, sample_format="int16",
                                channels=1, raw=raw)
        np.testing.assert_allclose(back, wave_form, atol=1e-3)

    def test_float_from_the_device_becomes_readable_pcm(self):
        """
        `preferredFormat()` вполне может оказаться float32, а `read_wav`
        понимает только целочисленный PCM. Без приведения WAV получился бы
        формально верным и совершенно неверным по содержимому.
        """
        wave_form = (np.sin(np.linspace(0, 30 * np.pi, 1500)) * 0.4
                     ).astype(np.float32)
        back = self._round_trip(wave_form, sample_format="float",
                                channels=1, raw=wave_form.tobytes())
        np.testing.assert_allclose(back, wave_form, atol=1e-3)

    def test_stereo_is_mixed_down_to_one_channel(self):
        left = np.sin(np.linspace(0, 20 * np.pi, 800)) * 0.5
        right = np.sin(np.linspace(0, 20 * np.pi, 800) + 0.3) * 0.5
        stereo = np.empty(left.size * 2, dtype=np.float32)
        stereo[0::2], stereo[1::2] = left, right
        back = self._round_trip(left, sample_format="float", channels=2,
                                raw=stereo.tobytes())
        self.assertEqual(back.size, left.size)
        np.testing.assert_allclose(back, (left + right) / 2, atol=1e-3)

    def test_unsigned_eight_bit_is_centred(self):
        """8-битный PCM беззнаковый: середина шкалы — 128, а не 0."""
        raw = bytes([128, 200, 56, 128])
        back = self._round_trip(np.zeros(4), sample_format="uint8",
                                channels=1, raw=raw)
        self.assertAlmostEqual(float(back[0]), 0.0, places=2)
        self.assertGreater(back[1], 0.4)
        self.assertLess(back[2], -0.4)

    def test_a_truncated_last_sample_is_dropped_not_misread(self):
        """
        Устройство отдаёт порциями, и «стоп» обрывает последнюю. Лишний
        байт, оставленный на месте, сдвинул бы всю запись на полотсчёта —
        и дальше она читалась бы как шум.
        """
        raw = np.array([100, -100, 300], dtype=np.int16).tobytes() + b"\x01"
        pcm = to_mono_int16(raw, sample_format="int16", channels=1)
        self.assertEqual(len(pcm), 3 * 2)

    def test_an_unknown_device_format_is_refused_loudly(self):
        with self.assertRaises(ValueError):
            to_mono_int16(b"\x00\x01", sample_format="int24", channels=1)

    def test_nothing_recorded_gives_nothing_back(self):
        self.assertEqual(to_mono_int16(b"", sample_format="int16",
                                       channels=1), b"")

    def test_a_captured_reference_is_still_recognised(self):
        """
        Сквозная проверка: эталон, проведённый через ВЕСЬ путь записи
        (отсчёты устройства → приведение → WAV → чтение → признаки →
        правило), по-прежнему опознаётся как своё слово. Именно это
        связывает десктопную половину с ядром.
        """
        terms = sorted(P.audio_index())[:5]
        signal, rate = M.read_wav(resolve(P.audio_of(terms[0])))
        signal = M.resample(signal, rate)
        raw = signal.astype(np.float32).tobytes()

        pcm = to_mono_int16(raw, sample_format="float", channels=1)
        path = pathlib.Path(temp_path(".wav"))
        self.addCleanup(path.unlink)
        write_wav(path, pcm, M.TARGET_RATE)

        spec = VoiceSpec(term=terms[0], vocabulary=tuple(terms),
                         mode=CheckMode.STRICT)
        self.assertTrue(spec.check(str(path)).accepted)

    def test_a_quiet_recording_is_judged_and_not_dismissed(self):
        """
        Порог тишины не должен отбрасывать того, кто говорит тихо. Замер:
        отбрасывается запись слабее ≈1.6% от громкости эталона, то есть
        около 36 дБ вниз; на 5% вердикт выносится как обычно.
        """
        terms = sorted(P.audio_index())[:5]
        signal, rate = M.read_wav(resolve(P.audio_of(terms[0])))
        quiet = M.resample(signal, rate) * 0.05
        path = pathlib.Path(temp_path(".wav"))
        self.addCleanup(path.unlink)
        write_wav(path, to_mono_int16(quiet.astype(np.float32).tobytes(),
                                      sample_format="float", channels=1),
                  M.TARGET_RATE)
        spec = VoiceSpec(term=terms[0], vocabulary=tuple(terms))
        verdict = spec.check(str(path))
        self.assertNotEqual(verdict.reason, Reason.EMPTY)
        self.assertTrue(verdict.accepted)


class InputControlTests(unittest.TestCase):
    """Способ ввода выбирается вопросом, а не представлением."""

    def test_a_voice_question_switches_from_the_text_field(self):
        view = InteractiveTaskView(SolvingGenerator(_generator()))
        self.addCleanup(view.deleteLater)
        self.assertIsNotNone(view.recorder)
        self.assertIs(view.input_stack.currentWidget(), view.recorder)

    def test_a_typed_question_keeps_the_text_field(self):
        """
        Проверка в обратную сторону: подмена не должна распространиться на
        обычные сессии. Словарный диктант отвечает с клавиатуры, и поле
        ввода обязано остаться на месте.
        """
        from exercises.english.generators import WordsTrainerGenerator
        trainer = WordsTrainerGenerator(name="Диктант",
                                        words_path=_dictionary_with_audio(),
                                        partition_id=1_000_001)
        view = InteractiveTaskView(trainer)
        self.addCleanup(view.deleteLater)
        self.assertIs(view.input_stack.currentWidget(), view.input_field)
        # Лениво: сессия без голоса не должна опрашивать устройства ввода.
        self.assertIsNone(view.recorder)

    def test_without_a_recording_pressing_answer_does_nothing(self):
        """
        Кнопка «Ответить» нажимается раньше, чем что-то записано, — это
        нормальный ход событий, а не ошибка. Ход при этом не должен
        засчитываться: пустая попытка испортила бы статистику.
        """
        view = InteractiveTaskView(SolvingGenerator(_generator()))
        self.addCleanup(view.deleteLater)
        self.assertEqual(view.recorder.recording_path(), "")
        view._on_submit()
        self.assertEqual(view.score_total, 0)

    def test_the_answer_is_taken_from_the_recorder(self):
        view = InteractiveTaskView(SolvingGenerator(_generator()))
        self.addCleanup(view.deleteLater)
        term = view.task.current().spec.term
        recording = _recording_of(term)
        self.addCleanup(lambda: recording.exists() and recording.unlink())
        view.recorder._path = recording
        self.assertEqual(view._answer(), str(recording))
        # Напечатанное в поле ввода при этом игнорируется — ответом служит
        # запись, и брать его из двух мест сразу нельзя.
        view.input_field.setText("что-то напечатанное")
        self.assertEqual(view._answer(), str(recording))


class AttemptRecordingTests(unittest.TestCase):
    """Попытка уходит в статистику, запись — нет."""

    class _Spy:
        def __init__(self):
            self.calls = []

        def queue_attempt(self, partition_id, payload, *, correct,
                          assignment_id=None):
            self.calls.append((partition_id, payload, correct))

    def _solve_once(self):
        view = InteractiveTaskView(SolvingGenerator(_generator()))
        self.addCleanup(view.deleteLater)
        spy = self._Spy()
        view.attach_stats(partition_id=3_000_001, sync_client=spy)
        term = view.task.current().spec.term
        recording = _recording_of(term)
        self.addCleanup(lambda: recording.exists() and recording.unlink())
        view.recorder._path = recording
        view._on_submit()
        return spy, term

    def test_the_attempt_is_recorded(self):
        spy, _ = self._solve_once()
        self.assertEqual(len(spy.calls), 1)
        partition_id, _payload, correct = spy.calls[0]
        self.assertEqual(partition_id, 3_000_001)
        self.assertTrue(correct)

    def test_the_payload_names_the_word_and_the_outcome(self):
        spy, term = self._solve_once()
        payload = spy.calls[0][1]
        self.assertEqual(payload["term"], term)
        self.assertEqual(payload["kind"], "voice")
        self.assertIn("reason", payload)

    def test_the_payload_carries_no_file_path(self):
        """
        Путь к записи бессмыслен всюду, кроме этой машины и этой минуты, а
        попытка уезжает по синку на сервер. Класть его туда — то же, что
        адресовать файл путём в графе, только заметить труднее.
        """
        spy, _ = self._solve_once()
        text = repr(spy.calls[0][1])
        self.assertNotIn(".wav", text)
        self.assertNotIn("resources", text)
        self.assertNotIn("input", spy.calls[0][1])

    def test_the_recording_is_forgotten_after_the_answer(self):
        from ui.audio_recorder import write_wav
        view = InteractiveTaskView(SolvingGenerator(_generator()))
        self.addCleanup(view.deleteLater)
        term = view.task.current().spec.term

        # Через `_replace`, а не присваиванием: так виджет считает файл
        # СВОИМ, и именно этот путь проходит настоящая запись.
        made = _recording_of(term)
        self.addCleanup(lambda: made.exists() and made.unlink())
        view.recorder._replace(made)

        view._on_submit()
        self.assertEqual(view.recorder.recording_path(), "")
        self.assertFalse(made.exists(), "запись не должна оставаться на диске")


class CheckableViewStatsTests(unittest.TestCase):
    """
    Проверяемый раздел получает контекст статистики.

    Регрессия: `CheckableTaskView` не наследует `BaseTaskView` (хром
    приносит вложенное представление), а владелец зовёт `attach_stats` у
    всего, что вернул `_pick_view`. Метода не было — и КАЖДЫЙ проверяемый
    раздел падал с `AttributeError` при открытии: физика, матан со
    спецификацией, графы с проверяемым слотом. Прежние тесты этого не
    видели, потому что строили представление напрямую, минуя владельца.
    """

    def test_attach_stats_exists_and_reaches_the_inner_views(self):
        view = CheckableTaskView(_generator())
        self.addCleanup(view.deleteLater)
        view.attach_stats(partition_id=3_000_001, sync_client=None,
                          assignment_id=7)
        self.assertEqual(view.static_view._stats_partition_id, 3_000_001)

    def test_a_view_built_later_still_gets_the_context(self):
        """
        Решающее представление строится лениво — уже ПОСЛЕ вызова
        `attach_stats`. Без запоминания контекста попытки из режима
        «Решать» пропадали бы молча.
        """
        view = CheckableTaskView(_generator())
        self.addCleanup(view.deleteLater)
        view.attach_stats(partition_id=3_000_001, sync_client=None,
                          assignment_id=7)
        view.set_mode(CheckableTaskView.SOLVE)
        self.assertEqual(view.solving_view._stats_partition_id, 3_000_001)
        self.assertEqual(view.solving_view._stats_assignment_id, 7)

    def test_the_look_mode_is_still_the_default(self):
        view = CheckableTaskView(_generator())
        self.addCleanup(view.deleteLater)
        self.assertEqual(view.current_mode(), CheckableTaskView.LOOK)


class RecorderWidgetTests(unittest.TestCase):
    """
    Кнопка записи там, где записывать нечем.

    Это не край, а обычное положение дел: машина без микрофона, сборка без
    QtMultimedia, окружение проверки. Приложение обязано работать.
    """

    def test_it_degrades_to_a_disabled_button_with_a_reason(self):
        from ui.audio_recorder import VoiceRecorder, input_availability
        available, reason = input_availability()
        recorder = VoiceRecorder()
        self.addCleanup(recorder.deleteLater)
        if available:
            self.assertTrue(recorder.button.isEnabled())
        else:
            self.assertFalse(recorder.button.isEnabled())
            self.assertTrue(reason, "отказ обязан называть причину")
            self.assertEqual(recorder.button.toolTip(), reason)

    def test_discard_is_idempotent(self):
        from ui.audio_recorder import VoiceRecorder
        recorder = VoiceRecorder()
        self.addCleanup(recorder.deleteLater)
        recorder.discard()
        recorder.discard()
        self.assertEqual(recorder.recording_path(), "")

    def test_it_deletes_only_what_it_created(self):
        """
        Регрессия, и не гипотетическая: пока очистка удаляла то, на что
        указывает `_path`, проверка, подставившая туда поставочный эталон,
        стёрла восемь WAV из `resources/audio/`. Поймано сверкой рабочего
        дерева с коммитом, а не тестом, — тесты при этом были зелёные.
        """
        from ui.audio_recorder import VoiceRecorder
        recorder = VoiceRecorder()
        self.addCleanup(recorder.deleteLater)

        outsider = pathlib.Path(temp_path(".wav"))
        outsider.write_bytes("чужой файл".encode("utf-8"))
        self.addCleanup(lambda: outsider.exists() and outsider.unlink())

        recorder._path = outsider          # как если бы путь пришёл извне
        recorder.discard()
        self.assertTrue(outsider.exists(),
                        "виджет удалил файл, которого не создавал")
        self.assertEqual(recorder.recording_path(), "")

    def test_it_does_delete_its_own_file(self):
        from ui.audio_recorder import VoiceRecorder
        recorder = VoiceRecorder()
        self.addCleanup(recorder.deleteLater)
        own = pathlib.Path(temp_path(".wav"))
        recorder._replace(own)
        recorder.discard()
        self.assertFalse(own.exists())


class SectionRegistrationTests(unittest.TestCase):
    """Раздел появляется в списке и открывается."""

    @classmethod
    def setUpClass(cls):
        import shutil
        from const import DB_TEMPLATE as DB_PATH, WORDS_DIR
        from core import Repository
        import bootstrap

        # Поставочную БД открываем на КОПИИ (docs/handbook/05 §10):
        # разовые сценарии уже трижды меняли её в коммите.
        cls.copy = temp_path(suffix=".db")
        shutil.copyfile(DB_PATH, cls.copy)
        cls.repo = Repository(cls.copy)
        bootstrap.sync_database(cls.repo, WORDS_DIR)
        cls.registry = bootstrap.build_registry(cls.repo, WORDS_DIR)
        cls.words_dir = WORDS_DIR

    def _pronunciation_partitions(self):
        from core import partition_ids as ids
        return [p for p in self.repo.list_partitions_for_subject(2)
                if p.id in ids.ENGLISH_PRONUNCIATION]

    def test_dictionaries_with_sound_get_a_section(self):
        self.assertTrue(self._pronunciation_partitions())

    def test_every_section_has_a_generator(self):
        """
        Раздел без генератора — это «Нет генератора для partition_id=…» по
        клику. Ровно так выглядели пять мёртвых разделов английского,
        оставшихся от переименованных файлов.
        """
        for part in self._pronunciation_partitions():
            with self.subTest(part=part.name):
                self.assertTrue(self.registry.has(part.id))

    def test_the_section_is_named_so_it_is_distinguishable(self):
        for part in self._pronunciation_partitions():
            self.assertIn("произношение", part.name)

    def test_running_bootstrap_twice_changes_nothing(self):
        """
        Повторный запуск не должен ни плодить разделы, ни сносить только
        что заведённые: `_drop_stale_english_partitions` удаляет всё в
        полосе, чего нет среди живых, и новую полосу надо было туда внести.
        """
        import bootstrap
        before = {p.id for p in self._pronunciation_partitions()}
        bootstrap.sync_database(self.repo, self.words_dir)
        self.assertEqual({p.id for p in self._pronunciation_partitions()},
                         before)

    def test_the_section_opens_as_a_checkable_view(self):
        from core import Capability
        for part in self._pronunciation_partitions():
            generator = self.registry.get(part.id)
            self.assertIn(Capability.CHECKABLE, generator.capabilities)
            break


if __name__ == "__main__":
    unittest.main()
