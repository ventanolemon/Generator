"""
Экспорт готовых граф-генераторов в отдельные JSON-файлы («библиотека»).

Источник правды по-прежнему Python-модули exercises/graph_examples/
(series_exam.py, complex_exam.py) — там структура графа живёт как литерал
рядом с комментариями, объясняющими приём. Этот скрипт разворачивает те же
словари в человекочитаемые .json-файлы под resources/graph_library/, чтобы
их можно было версионировать/просматривать отдельно и засеять ими БД
(см. scripts/seed_graph_library.py).

Запуск: python scripts/export_graph_library.py
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exercises.graph_examples.series_exam import SERIES_EXAM
from exercises.graph_examples.complex_exam import COMPLEX_EXAM

LIBRARY_DIR = ROOT / "resources" / "graph_library"


def _slug(name: str) -> str:
    return name.replace(":", "").replace(" ", "_")


def export_group(catalogue: dict, subdir: str) -> list[Path]:
    out_dir = LIBRARY_DIR / subdir
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, (key, entry) in enumerate(catalogue.items(), start=1):
        payload = {
            "title": entry["title"],
            "note": entry.get("note", ""),
            "graph": entry["graph"],
        }
        path = out_dir / f"{i:02d}_{key}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def main() -> None:
    series_files = export_group(SERIES_EXAM, "series")
    complex_files = export_group(COMPLEX_EXAM, "complex")
    for p in series_files + complex_files:
        print(f"  {p.relative_to(ROOT)}")
    print(f"Готово: {len(series_files)} + {len(complex_files)} файлов "
          f"в {LIBRARY_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
