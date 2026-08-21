"""
Засеять реальные предметы «Ряды» и «Комплексный анализ» из JSON-библиотеки
(resources/graph_library/) в БД приложения (constracted=4 — редактируемые
граф-разделы). После запуска разделы открываются в GraphEditor как обычные
разделы: GeneratorWindow → предмет → двойной клик по разделу → правка мышью,
«Сохранить» пишет обратно в Partitions.generation_parametrs.

ВАЖНО про id: словари английского получают id = 1000 + номер файла в
отсортированном списке resources/words/*.json, пересчитываемый заново при
КАЖДОМ запуске приложения (bootstrap.build_registry/sync_database) — это
диапазон, который растёт вместе с числом словарей у конкретного пользователя
и никак не согласован с id остальных разделов. Раздел БД с id, попавшим в этот
диапазон, будет молча вытеснен английским генератором (bootstrap регистрирует
словари первыми, а строка `if registry.has(part.id): continue` в build_registry
тихо пропускает раздел с совпавшим id — без ошибки, просто открывается не то
задание). Поэтому эти сиды используют ЯВНЫЙ диапазон id (_ID_BASE=9000+),
заведомо недостижимый для схемы «1000 + число словарей» — заводить туда новые
разделы вручную через UI не нужно (upsert_partition без partition_id даёт
следующий свободный id автоматически и в эту область не попадёт).

Идемпотентно: repo.upsert_partition ищет запись по паре (subject_id, name) и
обновляет её, если она уже есть (id не меняется) — повторный запуск не плодит
дубликаты, но ПЕРЕЗАПИШЕТ содержимое раздела текущим JSON (если вы
отредактировали раздел в приложении и хотите сохранить правки, не запускайте
этот скрипт повторно для него — либо сначала выгрузите изменённый граф
обратно в JSON).

Запуск: python scripts/seed_graph_library.py [--db PATH]
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import Repository

LIBRARY_DIR = ROOT / "resources" / "graph_library"

# Начало зарезервированного диапазона id для сидов этой библиотеки (см. ВАЖНО
# выше про коллизию с id английских словарей). Разделы нумеруются подряд в
# порядке файлов в _SUBJECTS/каждой папки — стабильно между запусками, пока
# порядок файлов и число предметов не меняются.
_ID_BASE = 9000

# Новые предметы: (subject_id, имя, родитель, папка библиотеки).
_SUBJECTS = [
    (12, "Ряды", "Математический анализ", "series"),
    (13, "Комплексный анализ", "Математический анализ", "complex"),
]


def seed(repo: Repository) -> None:
    next_id = _ID_BASE
    for subject_id, name, parent, subdir in _SUBJECTS:
        sid = repo.ensure_subject(subject_id, name, parent)
        folder = LIBRARY_DIR / subdir
        files = sorted(folder.glob("*.json"))
        if not files:
            print(f"  ⚠ {folder} пуст — сначала запустите "
                  f"export_graph_library.py")
            continue
        print(f"Предмет «{name}» (id={sid}):")
        for path in files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = repo.upsert_partition(
                subject_id=sid,
                name=payload["title"],
                constracted=4,
                generation_params=payload["graph"],
                partition_id=next_id,
            )
            print(f"  [{pid}] {payload['title']}  ({path.name})")
            next_id += 1


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=None,
                     help="Путь к БД (по умолчанию resources/users_database.db)")
    args = ap.parse_args()

    if args.db is None:
        from const import DB_TEMPLATE as DB_PATH
        db_path = DB_PATH
    else:
        db_path = args.db

    print(f"БД: {db_path}")
    repo = Repository(db_path)
    seed(repo)
    print("Готово.")


if __name__ == "__main__":
    main()
