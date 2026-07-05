"""
Регрессия: раздел constracted=4 (граф) «Ряды»/«ТФКП» генерировал одно и то же
задание при каждом клике — все 15 JSON-файлов resources/graph_library/*/*.json
(экспортированных из exercises/graph_examples/{series_exam,complex_exam}.py)
несли зафиксированный meta.seed (11-19, 21-26), задуманный только как удобство
воспроизводимости для собственных тестов автора этих генераторов, но случайно
попавший в экспортируемый JSON (export_graph_library.py копирует graph как
есть) и оттуда — в реальную БД приложения (seed_graph_library.py).

GraphExecutor.run_full() безусловно чтит meta.seed, если он присутствует:
сидит и random.seed(seed), и собственный ExecContext.rng. Фиксированный сид
делает КАЖДЫЙ вызов GraphConstructorGenerator.generate() побитово идентичным
навсегда — раздел выглядит «сломанным» (всегда один и тот же вариант).

Тесты проверяют: (1) ни один файл библиотеки не несёт meta.seed; (2) реальное
исполнение через GraphSpec.parse(...).run_full() без явного сида даёт разные
результаты при повторных запусках.
"""

from __future__ import annotations
import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphSpec
from core.graph.executor import GraphExecutor

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "resources" / "graph_library"


def _library_files() -> list[Path]:
    return sorted(LIBRARY_DIR.glob("*/*.json"))


class NoFixedSeedInLibraryTests(unittest.TestCase):
    def test_library_is_not_empty(self):
        files = _library_files()
        self.assertGreaterEqual(len(files), 15,
                                 "ожидал хотя бы 15 файлов библиотеки "
                                 "(9 «Ряды» + 6 «ТФКП»)")

    def test_no_file_carries_a_fixed_seed(self):
        offenders = []
        for path in _library_files():
            payload = json.loads(path.read_text(encoding="utf-8"))
            seed = payload.get("graph", {}).get("meta", {}).get("seed")
            if seed is not None:
                offenders.append((path.name, seed))
        self.assertEqual(
            offenders, [],
            f"библиотечные графы с зафиксированным seed вернут одно и то же "
            f"задание навсегда: {offenders}",
        )

    def test_source_dicts_carry_no_fixed_seed_either(self):
        """export_graph_library.py копирует graph как есть — источник (Python
        словари SERIES_EXAM/COMPLEX_EXAM) обязан быть чист сам по себе, иначе
        следующий экспорт молча вернёт баг."""
        from exercises.graph_examples.series_exam import SERIES_EXAM
        from exercises.graph_examples.complex_exam import COMPLEX_EXAM

        offenders = []
        for catalogue, label in ((SERIES_EXAM, "series"), (COMPLEX_EXAM, "complex")):
            for key, entry in catalogue.items():
                seed = entry["graph"].get("meta", {}).get("seed")
                if seed is not None:
                    offenders.append((label, key, seed))
        self.assertEqual(
            offenders, [],
            f"источники банка заданий несут зафиксированный seed — очередной "
            f"export_graph_library.py снова заморозит вариант: {offenders}",
        )


class LibraryGraphsVaryAcrossRunsTests(unittest.TestCase):
    """Без явного сида повторные запуски обязаны использовать свежий random.

    GraphConstructorGenerator.generate() кэширует ОДИН GraphExecutor и зовёт
    .run() на нём при каждой генерации (см. exercises/graph/generators.py) —
    воспроизводим ровно этот паттерн: один executor, несколько run().
    """

    def test_each_library_graph_varies_across_repeated_runs(self):
        frozen = []
        for path in _library_files():
            payload = json.loads(path.read_text(encoding="utf-8"))
            spec = GraphSpec.parse(payload["graph"])
            self.assertIsNone(
                spec.meta.get("seed"),
                f"{path.name}: GraphSpec всё ещё несёт зафиксированный seed",
            )
            executor = GraphExecutor(spec)
            self.assertIsNotNone(
                executor.result, f"{path.name}: граф без финального TASK-узла"
            )
            signatures = {_task_signature(executor.run()) for _ in range(6)}
            if len(signatures) == 1:
                frozen.append(path.name)
        self.assertEqual(
            frozen, [],
            f"эти графы дают одинаковый результат все 6 запусков подряд без "
            f"сида — подозрение на скрытый детерминизм: {frozen}",
        )


def _task_signature(task_value) -> str:
    """Грубая, но устойчивая подпись Task: текст условия+ответа."""
    parts = []
    for block in getattr(task_value, "statement", []) or []:
        parts.append(block.render_plain())
    for block in getattr(task_value, "answer", []) or []:
        parts.append(block.render_plain())
    return "\x1f".join(parts)


if __name__ == "__main__":
    unittest.main()
