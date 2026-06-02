"""
Тесты узлов предложений с пропусками: sentences_file и sentence_fill.

Загрузка — headless через json; построение блоков и полный граф — под Qt
(FillInTheBlankBlock тянет PyQt6).
"""

from __future__ import annotations
import json
import os
import random
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


def _write(obj) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    return path


_SENTENCES = [
    {"template": "A ___ translates source code.", "answers": ["compiler"],
     "translation": "Компилятор переводит исходный код."},
    {"template": "___ is a markup ___.", "answers": ["HTML", "language"]},
]


class RegistryTests(unittest.TestCase):
    def test_sentences_type(self):
        self.assertTrue(hasattr(PortType, "SENTENCES"))
        self.assertEqual(PortType.SENTENCES.value, "sentences")

    def test_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("sentences_file", ids)
        self.assertIn("sentence_fill", ids)


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class SentencesFileTests(unittest.TestCase):
    def test_load_list(self):
        from core.graph.nodes.english import SentencesFileNode
        path = _write(_SENTENCES)
        try:
            out = SentencesFileNode("s", {"file": path}).compute({}, _ctx())["out"]
            self.assertEqual(len(out), 2)
            self.assertEqual(out[0]["answers"], ["compiler"])
        finally:
            os.remove(path)

    def test_non_list_rejected(self):
        from core.graph.nodes.english import SentencesFileNode
        from core.graph import GraphValidationError
        path = _write({"not": "a list"})
        try:
            with self.assertRaises(GraphValidationError):
                SentencesFileNode("s", {"file": path}).compute({}, _ctx())
        finally:
            os.remove(path)

    def test_missing_file_validate(self):
        from core.graph.nodes.english import SentencesFileNode
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            SentencesFileNode("s", {"file": ""})


@unittest.skipUnless(HAS_QT, "нужен PyQt6")
class SentenceFillTests(unittest.TestCase):
    def test_builds_statement_and_answer(self):
        from core.graph.nodes.english import SentenceFillNode
        out = SentenceFillNode("f", {}).compute({"in": _SENTENCES}, _ctx())
        self.assertIn("statement", out)
        self.assertIn("answer", out)
        self.assertGreaterEqual(len(out["statement"]), 2)
        self.assertGreaterEqual(len(out["answer"]), 3)

    def test_answer_fills_blanks(self):
        from core.graph.nodes.english import SentenceFillNode
        # единственное предложение -> детерминированный выбор
        single = [{"template": "A ___ runs code.", "answers": ["computer"]}]
        out = SentenceFillNode("f", {}).compute({"in": single}, _ctx())
        full = out["answer"][1].render_plain()
        self.assertIn("computer", full)
        self.assertNotIn("___", full)

    def test_empty_input_retries(self):
        from core.graph.nodes.english import SentenceFillNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            SentenceFillNode("f", {}).compute({"in": []}, _ctx())

    def test_malformed_item_retries(self):
        from core.graph.nodes.english import SentenceFillNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            SentenceFillNode("f", {}).compute({"in": [{"foo": "bar"}]}, _ctx())

    def test_reproducible_choice(self):
        from core.graph.nodes.english import SentenceFillNode
        a = SentenceFillNode("f", {}).compute({"in": _SENTENCES}, _ctx(5))
        b = SentenceFillNode("f", {}).compute({"in": _SENTENCES}, _ctx(5))
        self.assertEqual(a["answer"][1].render_plain(), b["answer"][1].render_plain())

    def test_full_graph_to_static_task(self):
        path = _write(_SENTENCES)
        try:
            graph = {
                "nodes": [
                    {"id": "sf", "type": "sentences_file", "params": {"file": path}},
                    {"id": "fill", "type": "sentence_fill"},
                    {"id": "task", "type": "static_task"},
                ],
                "edges": [
                    {"from": "sf:out", "to": "fill:in"},
                    {"from": "fill:statement", "to": "task:statement"},
                    {"from": "fill:answer", "to": "task:answer"},
                ],
                "meta": {"seed": 1},
            }
            task = GraphExecutor(GraphSpec.parse(graph)).run()
            from core.task import StaticTask
            self.assertIsInstance(task, StaticTask)
            self.assertTrue(task.statement)
            self.assertTrue(task.answer)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
