"""Регрессии build-time обработки образцового произношения."""

from __future__ import annotations

import struct
import wave

from tools.generate_audio import _trim_silence, downsample_wav, parse_args


def _pcm16(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_quiet_final_consonant_is_not_trimmed() -> None:
    rate = 1000
    # Гласная, тихое окончание, затем пауза синтезатора. Прежний отсечный
    # порог 350 считал всё после гласной тишиной и оставлял лишь 40 мс.
    source = _pcm16([2000] * 100 + [140] * 100 + [0] * 400)
    trimmed = _trim_silence(source, 2, rate)
    # 100 мс окончания + 160 мс безопасного хвоста обязаны сохраниться.
    assert len(trimmed) // 2 >= 360


def test_audio_is_generated_at_speech_recognition_rate_by_default() -> None:
    assert parse_args([]).rate == 16000


def test_postprocess_works_without_removed_audioop(tmp_path) -> None:
    path = tmp_path / "reference.wav"
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(32000)
        target.writeframes(_pcm16([0] * 3200 + [2000] * 3200 + [140] * 1600
                                  + [0] * 6400))

    downsample_wav(path, 16000)

    with wave.open(str(path), "rb") as result:
        assert result.getframerate() == 16000
        assert result.getnchannels() == 1
        assert result.getsampwidth() == 2
        # Весь длинный хвост убран, тихое окончание осталось.
        assert 3500 < result.getnframes() < 7000
