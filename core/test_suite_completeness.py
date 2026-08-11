"""
Каждый файл с тестами должен ИСПОЛНЯТЬСЯ прогоном набора.

Найдено не рассуждением, а замером. `core/test_graph_api.py` был написан
со своим раннером — голые `assert`, список функций, `if __name__ ==
"__main__"`. Классов `TestCase` в нём не было, поэтому `unittest
discover` не находил там ни одного теста; полный прогон показывал «OK», а
семь проверок не выполнялись. К моменту находки одна из них уже падала:
в каталог узлов прибавились модели, а прибитые в тесте число и хэш
остались прежними. Сколько времени она падала молча — неизвестно, и это
и есть цена такой дыры.

Здесь закрывается сам класс ошибки, а не один случай:

  1. файл `test_*.py`, из которого `discover` не берёт НИ ОДНОГО теста,
     считается ошибкой — если только он не назван ниже явно;
  2. файлы со своим раннером запускаются отсюда ПОДПРОЦЕССОМ и
     проверяются по коду возврата (на десктопе таких сейчас нет);
  3. отдельно назван рабочий код с именем `test_*`: «тест» на десктопе —
     доменное слово (раздел-тест из заданий), и `test_editor.py` — это
     редактор ТЕСТА, а не тест редактора.

Второй пункт важнее первого: список-исключение, который никто не
запускает, — это тот же самый молчаливый пропуск, только записанный.

Запуск:
    python -m unittest core.test_suite_completeness
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Файлы со своим раннером: печатают свой отчёт и возвращают код выхода.
#: На десктопе таких нет — список оставлен пустым намеренно, чтобы файл
#: оставался зеркалом серверного и правился одинаково с обеих сторон.
SELF_RUNNING: tuple[str, ...] = ()

#: НЕ тесты, а рабочий код, чьё имя начинается на `test_`: «тест» здесь —
#: доменное слово (раздел-тест из нескольких заданий), а не проверка.
#: `test_editor.py` — это редактор ТЕСТА, а не тест редактора.
#:
#: Список нужен по делу: `unittest discover -p "test_*.py"` эти модули
#: ИМПОРТИРУЕТ — то есть тянет Qt-виджеты в каждый прогон набора, — и без
#: записи здесь они выглядят как файлы, где почему-то нет ни одного теста.
NOT_TESTS = (
    "ui/editors/test_editor.py",
    "ui/views/test_view.py",
)

#: Каталоги, которые обходить не нужно.
SKIP_PARTS = {".git", "node_modules", "__pycache__", "dist", "build", ".venv"}


def _test_files() -> list[pathlib.Path]:
    out = []
    for path in sorted(_ROOT.rglob("test_*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        out.append(path)
    return out


class EveryTestFileIsCollected(unittest.TestCase):

    def test_no_file_is_silently_empty(self):
        """
        Файл без единого собираемого теста — это не «мало тестов», это
        отсутствие проверки при её видимости. Такой файл читается как
        покрытие и покрытием не является.
        """
        loader = unittest.TestLoader()
        silent = []
        for path in _test_files():
            rel = path.relative_to(_ROOT).as_posix()
            if rel in SELF_RUNNING or rel in NOT_TESTS:
                continue
            module = rel[:-3].replace("/", ".")
            try:
                count = loader.loadTestsFromName(module).countTestCases()
            except Exception as exc:            # noqa: BLE001
                silent.append(f"{rel}: не импортируется ({exc})")
                continue
            if count == 0:
                silent.append(f"{rel}: собрано 0 тестов")
        self.assertEqual(silent, [], "\n".join(silent))

    def test_exception_lists_still_point_at_existing_files(self):
        # Список-исключение обязан устаревать ГРОМКО: переименованный или
        # удалённый файл иначе просто выпадет из проверки, и мы вернёмся
        # ровно туда, откуда ушли.
        for rel in SELF_RUNNING + NOT_TESTS:
            with self.subTest(file=rel):
                self.assertTrue((_ROOT / rel).is_file())

    def test_files_listed_as_not_tests_really_have_no_tests(self):
        """
        Обратная проверка: если в «рабочий код с именем test_*» однажды
        допишут настоящий тест, он будет молча пропускаться — то есть
        исключение из правила превратится в ту же дыру, ради которой
        правило и заведено.
        """
        loader = unittest.TestLoader()
        for rel in NOT_TESTS:
            module = rel[:-3].replace("/", ".")
            with self.subTest(file=rel):
                self.assertEqual(
                    loader.loadTestsFromName(module).countTestCases(), 0,
                    f"{rel} перестал быть рабочим кодом — уберите из NOT_TESTS")


class SelfRunningFilesActuallyRun(unittest.TestCase):
    """Свой раннер — не повод не запускаться вместе со всеми."""

    def test_every_self_running_file_exits_clean(self):
        for rel in SELF_RUNNING:
            with self.subTest(file=rel):
                env = dict(os.environ, PYTHONPATH=str(_ROOT))
                proc = subprocess.run(
                    [sys.executable, str(_ROOT / rel)],
                    cwd=str(_ROOT), env=env, capture_output=True, text=True,
                    timeout=600)
                self.assertEqual(
                    proc.returncode, 0,
                    f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")


if __name__ == "__main__":
    unittest.main()
