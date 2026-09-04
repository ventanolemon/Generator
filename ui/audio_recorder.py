"""
Запись голоса с микрофона — десктопная половина задания на произношение.

Где проходит граница
--------------------
Правило приёма живёт в ядре (`core.pronunciation_match`, `VoiceSpec`) и
одинаково всюду. Здесь — то, чем ответ СНЯТ, и это платформа: у десктопа
`QAudioSource`, у браузера был бы `MediaRecorder`, у них разные форматы и
разные разрешения. Ядро об этом не знает и знать не должно.

Что здесь проверяемо, а что нет
-------------------------------
Модуль намеренно разделён на две части.

* `to_mono_int16` и `write_wav` — обычные функции без Qt. Именно они
  делают опасное: переводят то, что отдало устройство, в файл, который
  обязан прочитаться `pronunciation_match.read_wav`. Ошибка здесь —
  молчаливая: WAV получится, откроется и будет содержать шум вместо
  голоса. Поэтому они отделены и проверяются прогоном.
* `VoiceRecorder` — кнопка и работа с устройством. Микрофона в проверке
  нет, поэтому этот путь проверкой не покрыт; сказано об этом прямо, а
  не умолчано.

Отсутствие звукового модуля или микрофона — не отказ
----------------------------------------------------
Тот же приём, что у `AudioBlock`: нет QtMultimedia или устройства ввода —
кнопка выключена с пояснением, а задание остаётся карточкой с эталоном.
Приложение обязано работать на машине без микрофона.

Запись не хранится
------------------
Файл создаётся во временном каталоге, живёт до следующей записи и
удаляется вместе с виджетом. В попытку идёт ВЕРДИКТ, а не голос:
двоичного поля под запись в схеме попыток нет, и заводить его ради
тренажёра — отдельная работа с хранением, квотами и согласием на запись
голоса.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import wave

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from core.pronunciation_match import TARGET_RATE

#: Формат, который просим у устройства. Совпадает с частотой эталонов —
#: тогда приведение частоты при разборе признаков вырождается в ничто.
#: Устройство вправе не согласиться; тогда берётся его собственный формат,
#: а разницу снимает `pronunciation_match.resample`.
WANTED_RATE = TARGET_RATE
WANTED_CHANNELS = 1

#: Сколько байт на отсчёт у форматов, которые устройство может предложить.
#: `float` в списке потому, что `preferredFormat()` его возвращает, а
#: `read_wav` работает только с целочисленным PCM.
_WIDTHS = {"uint8": 1, "int16": 2, "int32": 4, "float": 4}


def to_mono_int16(raw: bytes, *, sample_format: str, channels: int) -> bytes:
    """
    Отсчёты устройства → моно 16-битный PCM.

    Два приведения, и оба обязательные, а не косметические:

    * **в моно** — потому что `read_wav` усредняет каналы сам, но эталоны
      моно, и складывать это приведение в два разных места значит однажды
      их рассогласовать;
    * **в int16** — потому что `read_wav` понимает 8/16/32-битный целый
      PCM и не понимает float, а `preferredFormat()` устройства вполне
      может оказаться float32.

    Неполный последний отсчёт отбрасывается: устройство отдаёт данные
    порциями, и последняя порция обрывается там, где нажали «стоп».
    """
    import numpy as np

    width = _WIDTHS.get(sample_format)
    if width is None:
        raise ValueError(f"Неизвестный формат отсчётов: {sample_format!r}")
    channels = max(1, int(channels))

    frame = width * channels
    if frame and len(raw) % frame:
        raw = raw[:len(raw) - (len(raw) % frame)]
    if not raw:
        return b""

    dtype = {"uint8": np.uint8, "int16": np.int16,
             "int32": np.int32, "float": np.float32}[sample_format]
    data = np.frombuffer(raw, dtype=dtype).astype(np.float32)

    # К диапазону [-1, 1] — единственная форма, в которой каналы можно
    # усреднять, не думая о разрядности.
    if sample_format == "uint8":
        data = (data - 128.0) / 128.0
    elif sample_format != "float":
        data = data / float(np.iinfo(dtype).max)

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    peak = np.max(np.abs(data)) if data.size else 0.0
    if peak > 1.0:
        # float с устройства не обязан укладываться в единицу; обрезка
        # вместо нормировки исказила бы громкие места сильнее тихих.
        data = data / peak
    return np.clip(data * 32767.0, -32768.0, 32767.0).astype(np.int16).tobytes()


def write_wav(path, pcm16: bytes, rate: int = WANTED_RATE) -> pathlib.Path:
    """Записать моно 16-битный PCM в WAV, читаемый `read_wav`."""
    target = pathlib.Path(path)
    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(rate))
        handle.writeframes(pcm16)
    return target


def _sample_format_name(fmt) -> str:
    """Имя формата отсчётов QAudioFormat — в наш словарь ширин."""
    from PyQt6.QtMultimedia import QAudioFormat

    return {
        QAudioFormat.SampleFormat.UInt8: "uint8",
        QAudioFormat.SampleFormat.Int16: "int16",
        QAudioFormat.SampleFormat.Int32: "int32",
        QAudioFormat.SampleFormat.Float: "float",
    }.get(fmt.sampleFormat(), "")


def input_availability() -> tuple[bool, str]:
    """
    Можно ли здесь записывать: `(да/нет, причина отказа)`.

    Причина возвращается текстом, а не кодом, потому что показывается
    человеку подсказкой к выключенной кнопке. Разница между «нет модуля» и
    «нет микрофона» для него настоящая: первое чинит установка пакета,
    второе — устройство.
    """
    try:
        # Здесь проверяется только наличие backend. Опрос устройства намеренно
        # отложен до нажатия «Записать»: на части Windows-драйверов вызов
        # defaultAudioInput() во время построения окна аварийно завершает весь
        # процесс (0xC0000409), и Python не может перехватить native crash.
        from PyQt6.QtMultimedia import QAudioSource  # noqa: F401
    except Exception as exc:                            # noqa: BLE001
        return False, f"Звуковой модуль QtMultimedia недоступен: {exc}"
    return True, ""


class VoiceRecorder(QWidget):
    """
    Кнопка «записать / стоп» и подпись состояния.

    Сигнал `recorded(str)` несёт путь к WAV — МЕСТНУЮ форму ответа
    (см. `core.answers._recording_source`). Проверка идёт на этой же
    машине в этом же процессе, поэтому путь тут законен.

    По сети путь передавать по-прежнему нельзя: он назвал бы файл на
    чужой машине. У веба поэтому своя форма — сама запись
    (`data:audio/wav;base64,…`), и кодирует её браузер. Спецификация и
    правило приёма при этом общие: вердикт у обоих клиентов один.
    """

    recorded = pyqtSignal(str)

    IDLE = "Нажмите «Записать» и произнесите слово."

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._source = None
        self._stream = None
        self._chunks: list[bytes] = []
        self._path: pathlib.Path | None = None
        # Файл, который создал ЭТОТ виджет, — и единственное, что он
        # вправе удалить. См. `discard`.
        self._owned: pathlib.Path | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("● Записать", self)
        self.button.setMaximumWidth(180)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.status = QLabel(self.IDLE, self)
        row.addWidget(self.button)
        row.addWidget(self.status, stretch=1)

        available, reason = input_availability()
        if not available:
            self.button.setEnabled(False)
            self.button.setToolTip(reason)
            self.status.setText(reason)
        else:
            self.button.clicked.connect(self.toggle)

    # ---------- состояние ----------

    def is_recording(self) -> bool:
        return self._source is not None

    def recording_path(self) -> str:
        """Последняя запись или пустая строка."""
        return str(self._path) if self._path is not None else ""

    # ---------- запись ----------

    def toggle(self) -> None:
        self.stop() if self.is_recording() else self.start()

    def start(self) -> None:
        from PyQt6.QtMultimedia import (
            QAudioSource, QMediaDevices,
        )

        device = QMediaDevices.defaultAudioInput()
        if device is None or device.isNull():
            self.status.setText("Микрофон не найден.")
            return

        # Используем формат самого устройства. Запрос искусственного 16 kHz
        # Int16 заставлял некоторые Windows-драйверы пройти нестабильную ветку
        # isFormatSupported; частоту, каналы и float/int всё равно безопасно
        # нормализуют resample и to_mono_int16 после записи.
        fmt = device.preferredFormat()

        self._chunks = []
        self._source = QAudioSource(device, fmt, self)
        self._stream = self._source.start()
        if self._stream is None:
            self._source = None
            self.status.setText("Устройство не отдало поток записи.")
            return
        self._stream.readyRead.connect(self._drain)
        self.button.setText("■ Стоп")
        self.status.setText("Идёт запись…")

    def _drain(self) -> None:
        """Забрать накопившееся. Без этого поток встанет по переполнению."""
        if self._stream is None:
            return
        data = self._stream.readAll()
        if data:
            self._chunks.append(bytes(data))

    def stop(self) -> None:
        if self._source is None:
            return
        self._drain()
        source, self._source = self._source, None
        self._stream = None
        fmt = source.format()
        source.stop()

        raw = b"".join(self._chunks)
        self._chunks = []
        self.button.setText("● Записать")

        name = _sample_format_name(fmt)
        if not name:
            self.status.setText("Устройство отдало формат, который мы не читаем.")
            return
        try:
            pcm = to_mono_int16(raw, sample_format=name,
                                channels=fmt.channelCount())
        except ValueError as exc:
            self.status.setText(f"Запись не разобрана: {exc}")
            return
        if not pcm:
            self.status.setText("Записи не получилось — тишина.")
            return

        self._replace(write_wav(self._fresh_file(), pcm, fmt.sampleRate()))
        self.status.setText("Записано. Нажмите «Ответить».")
        self.recorded.emit(str(self._path))

    # ---------- временный файл ----------

    def _fresh_file(self) -> pathlib.Path:
        handle, name = tempfile.mkstemp(prefix="pronounce-", suffix=".wav")
        os.close(handle)
        return pathlib.Path(name)

    def _replace(self, path: pathlib.Path) -> None:
        """Новая запись вытесняет предыдущую — хранить их незачем."""
        self.discard()
        self._path = self._owned = path

    def discard(self) -> None:
        """
        Убрать последнюю запись с диска. Идемпотентно.

        Удаляется ТОЛЬКО файл, созданный этим виджетом, а не то, на что
        сейчас указывает `_path`. Разница не теоретическая: пока правило
        держалось на договорённости «`_path` всегда временный», проверка,
        подставившая туда поставочный эталон, стёрла восемь файлов
        произношения из поставки. Договорённость, которую нельзя нарушить
        по невнимательности, стоит одного поля.
        """
        owned, self._owned, self._path = self._owned, None, None
        if owned is None:
            return
        try:
            owned.unlink()
        except OSError:
            pass

    def reset(self) -> None:
        """Вернуть в исходное: записи нет, подпись прежняя."""
        if self.is_recording():
            self.stop()
        self.discard()
        if self.button.isEnabled():
            self.status.setText(self.IDLE)

    # Запись — временный файл, и он не должен пережить виджет. Qt зовёт
    # это при удалении родителя, то есть при закрытии раздела.
    def closeEvent(self, event) -> None:                 # noqa: N802
        self.reset()
        super().closeEvent(event)

    def __del__(self):
        try:
            self.discard()
        except Exception:                                # noqa: BLE001
            pass
