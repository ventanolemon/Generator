"""
Засеять реальные предметы «Ряды» и «Комплексный анализ» из JSON-библиотеки
(resources/graph_library/) в БД приложения (constracted=4 — редактируемые
граф-разделы). После запуска разделы открываются в GraphEditor как обычные
разделы: GeneratorWindow → предмет → двойной клик по разделу → правка мышью,
«Сохранить» пишет обратно в Partitions.generation_parametrs.

Идемпотентно: repo.upsert_partition ищет запись по паре (subject_id, name) и
обновляет её, если она уже есть — повторный запуск не плодит дубликаты, но
ПЕРЕЗАПИШЕТ содержимое раздела текущим JSON (если вы отредактировали раздел
в приложении и хотите сохранить правки, не запускайте этот скрипт повторно
для него — либо сначала выгрузите изменённый граф обратно в JSON).

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

# Новые предметы: (subject_id, имя, родитель, папка библиотеки).
_SUBJECTS = [
    (12, "Ряды", "Математический анализ", "series"),
    (13, "Комплексный анализ", "Математический анализ", "complex"),
]


def seed(repo: Repository) -> None:
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
            )
            print(f"  [{pid}] {payload['title']}  ({path.name})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=None,
                     help="Путь к БД (по умолчанию resources/users_database.db)")
    args = ap.parse_args()

    if args.db is None:
        from const import DB_PATH
        db_path = DB_PATH
    else:
        db_path = args.db

    print(f"БД: {db_path}")
    repo = Repository(db_path)
    seed(repo)
    print("Готово.")


if __name__ == "__main__":
    main()
