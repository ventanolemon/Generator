"""
Тесты узлов предложений с пропусками: sentences_file и sentence_pick.

`sentence_fill` был здесь до того, как его убрали целиком. Он отдавал
наружу собранные блоки, а не значения, и задание получалось
непроверяемым (`is_checkable == False`), с правильными ответами прямо в
условии — сверять их было больше негде. Замена отдаёт части, а ввод по
месту стал режимом показа (виджет `slot_inline` у `task`).
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
        self.assertIn("sentence_pick", ids)
        # Убран целиком, а не оставлен «на всякий случай»: узел, делающий
        # задание непроверяемым, в палитре — это ловушка для автора.
        self.assertNotIn("sentence_fill", ids)


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


class SentencePickTests(unittest.TestCase):
    """Узел отдаёт ЧАСТИ предложения — их дальше проверяет слот `много`."""

    def test_gives_out_the_parts(self):
        from core.graph.nodes.english import SentencePickNode
        single = [{"template": "A ___ runs code.", "answers": ["computer"],
                   "translation": "Компьютер выполняет код."}]
        out = SentencePickNode("p", {}).compute({"in": single}, _ctx())
        self.assertEqual(out["answers"], ["computer"])
        self.assertIn("___", out["template"])
        self.assertEqual(out["filled"], "A computer runs code.")
        self.assertEqual(out["translation"], "Компьютер выполняет код.")

    def test_blank_marker_is_a_parameter(self):
        from core.graph.nodes.english import SentencePickNode
        single = [{"template": "A ___ runs code.", "answers": ["computer"]}]
        out = SentencePickNode("p", {"blank": "…"}).compute({"in": single},
                                                            _ctx())
        self.assertIn("…", out["template"])
        self.assertNotIn("___", out["template"])

    def test_empty_input_retries(self):
        from core.graph.nodes.english import SentencePickNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            SentencePickNode("p", {}).compute({"in": []}, _ctx())

    def test_malformed_item_retries(self):
        from core.graph.nodes.english import SentencePickNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            SentencePickNode("p", {}).compute({"in": [{"foo": "bar"}]}, _ctx())

    def test_blank_count_must_match_the_answers(self):
        """
        Пропусков в шаблоне и ответов должно быть поровну. Иначе поле
        встанет не в тот пропуск, и предложение сменит смысл.
        """
        from core.graph.nodes.english import SentencePickNode
        from core.graph import RetryGeneration
        bad = [{"template": "A ___ runs ___.", "answers": ["computer"]}]
        with self.assertRaises(RetryGeneration):
            SentencePickNode("p", {}).compute({"in": bad}, _ctx())

    def test_reproducible_choice(self):
        from core.graph.nodes.english import SentencePickNode
        a = SentencePickNode("p", {}).compute({"in": _SENTENCES}, _ctx(5))
        b = SentencePickNode("p", {}).compute({"in": _SENTENCES}, _ctx(5))
        self.assertEqual(a["filled"], b["filled"])

    def test_full_graph_gives_a_checkable_task(self):
        """
        Главное отличие от прежнего узла: задание проверяется, а ответы
        клиенту не показываются.
        """
        path = _write(_SENTENCES)
        try:
            graph = {
                "nodes": [
                    {"id": "sf", "type": "sentences_file",
                     "params": {"file": path}},
                    {"id": "pick", "type": "sentence_pick"},
                    {"id": "task", "type": "task", "params": {
                        "statement": "Вставьте слова:\n#предложение#",
                        "slots": ["пропуск:text:много"],
                        "widget": "slot_inline"}},
                ],
                "edges": [
                    {"from": "sf:out", "to": "pick:in"},
                    {"from": "pick:template", "to": "task:предложение"},
                    {"from": "pick:answers", "to": "task:пропуск"},
                ],
                "meta": {"seed": 1},
            }
            task = GraphExecutor(GraphSpec.parse(graph)).run()
            from core.task import StaticTask
            self.assertIsInstance(task, StaticTask)
            self.assertTrue(task.is_checkable)
            shown = " ".join(b.render_plain() for b in task.statement)
            for item in _SENTENCES:
                for answer in item["answers"]:
                    self.assertNotIn(answer, shown)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
