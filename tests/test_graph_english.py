"""
Тесты узлов английского языка: words_file (загрузка/inline) и words_trainer,
а также диалог предпросмотра/правки слов.

Загрузка слов — headless (json + flatten); сессия-тренажёр и диалог — под Qt
(тянут динамические блоки / виджеты).
"""

from __future__ import annotations
import json
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from core.tmpdb import temp_path  # noqa: E402

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx():
    return ExecContext(rng=random.Random(0))


def _write_json(obj) -> str:
    path = temp_path(suffix=".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


class PortTypeTests(unittest.TestCase):
    def test_words_type_exists(self):
        self.assertTrue(hasattr(PortType, "WORDS"))
        self.assertEqual(PortType.WORDS.value, "words")

    def test_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("words_file", ids)
        self.assertIn("words_trainer", ids)

    def test_english_category(self):
        cats = {e["category"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("english", cats)


@unittest.skipUnless(HAS_QT, "нужен PyQt6 (english тянет динамические блоки)")
class WordsFileTests(unittest.TestCase):
    def test_load_vocabulary_format(self):
        from core.graph.nodes.english import WordsFileNode
        path = _write_json({"title": "T", "vocabulary": [
            {"term": "cat", "translation": "кот"},
            {"term": "dog", "translation": "собака"},
        ]})
        try:
            out = WordsFileNode("w", {"file": path}).compute({}, _ctx())["out"]
            self.assertEqual(out, {"cat": "кот", "dog": "собака"})
        finally:
            os.remove(path)

    def test_load_old_direct_format(self):
        from core.graph.nodes.english import WordsFileNode
        path = _write_json({"sun": "солнце", "moon": "луна"})
        try:
            out = WordsFileNode("w", {"file": path}).compute({}, _ctx())["out"]
            self.assertEqual(out, {"sun": "солнце", "moon": "луна"})
        finally:
            os.remove(path)

    def test_inline_overrides_file(self):
        from core.graph.nodes.english import WordsFileNode
        out = WordsFileNode("w", {"file": "/nonexistent.json",
                                  "inline": {"a": "б"}}).compute({}, _ctx())["out"]
        self.assertEqual(out, {"a": "б"})

    def test_missing_file_raises_on_validate(self):
        from core.graph.nodes.english import WordsFileNode
        from core.graph import GraphValidationError
        # ни файла, ни inline — ошибка валидации
        with self.assertRaises(GraphValidationError):
            WordsFileNode("w", {"file": "", "inline": None})

    def test_empty_words_retry(self):
        from core.graph.nodes.english import WordsFileNode
        from core.graph import RetryGeneration
        path = _write_json({"vocabulary": []})
        try:
            with self.assertRaises(RetryGeneration):
                WordsFileNode("w", {"file": path}).compute({}, _ctx())
        finally:
            os.remove(path)


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class WordsTrainerTests(unittest.TestCase):
    def test_trainer_builds_session(self):
        from core.graph.nodes.english import WordsTrainerNode
        from exercises.english.generators import WordsSession
        task = WordsTrainerNode("t", {}).compute(
            {"words": {"cat": "кот", "dog": "собака"}}, _ctx())["out"]
        self.assertIsInstance(task, WordsSession)

    def test_trainer_empty_retries(self):
        from core.graph.nodes.english import WordsTrainerNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            WordsTrainerNode("t", {}).compute({"words": {}}, _ctx())

    def test_full_graph_to_task(self):
        path = _write_json({"vocabulary": [
            {"term": "cat", "translation": "кот"}]})
        try:
            graph = {
                "nodes": [
                    {"id": "wf", "type": "words_file", "params": {"file": path}},
                    {"id": "wt", "type": "words_trainer"},
                ],
                "edges": [{"from": "wf:out", "to": "wt:words"}],
                "meta": {},
            }
            task = GraphExecutor(GraphSpec.parse(graph)).run()
            from exercises.english.generators import WordsSession
            self.assertIsInstance(task, WordsSession)
        finally:
            os.remove(path)


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class WordEditorDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_round_trip(self):
        from ui.editors.graph_canvas.word_editor import WordEditorDialog
        d = WordEditorDialog({"cat": "кот", "dog": "собака"})
        self.assertEqual(d.table.rowCount(), 2)
        self.assertEqual(d.result_words(), {"cat": "кот", "dog": "собака"})

    def test_add_and_collect(self):
        from ui.editors.graph_canvas.word_editor import WordEditorDialog
        d = WordEditorDialog({})
        d._append_row("bird", "птица")
        d._append_row("", "пусто")          # пустой термин должен отсеяться
        self.assertEqual(d.result_words(), {"bird": "птица"})


if __name__ == "__main__":
    unittest.main()
