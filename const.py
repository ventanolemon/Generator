"""
Константы и пути проекта. Все пути — относительно корня проекта,
без хардкода вроде C:\\Users\\... .
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = ROOT_DIR / "resources"
DB_PATH = RESOURCES_DIR / "users_database.db"
WORDS_DIR = RESOURCES_DIR / "words"
UI_FILES_DIR = RESOURCES_DIR / "ui_files"
# Глобальный файл черновых IPA-транскрипций (см. tools/generate_transcriptions.py).
# Используется WordsSession как fallback, если в самом vocab-JSON нет inline
# поля "transcription". Файл опционален: если его нет — тренажёр работает без IPA.
TRANSCRIPTIONS_PATH = RESOURCES_DIR / "transcriptions.json"
# Каталог с пре-рендеренным аудио произношения и манифестом index.json
# (см. tools/generate_audio.py). Опционален: без него тренажёр работает без звука.
AUDIO_DIR = RESOURCES_DIR / "audio"
