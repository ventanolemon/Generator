"""
Тесты компилятора графа в Python (GraphCompiler).

Главная проверка — паритет: скомпилированный модуль на том же seed выдаёт тот же
результат, что и GraphExecutor. Покрываем инлайн-узлы (формулы/случайные/блоки) и
универсальный путь (linalg/symbolic/control). Требует Qt (блоки тянут PyQt6).
"""

from __future__ import annotations
import importlib.util
import os
import random
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import GraphExecutor, GraphSpec
from core.graph.compiler import compile_graph
from core.graph.compiler import _ident

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


def _run_compiled(src: str, seed):
    """Записать исходник во временный модуль, импортировать и вызвать generate."""
    fd, path = tempfile.mkstemp(suffix=".py", dir=".")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    name = os.path.basename(path)[:-3]
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.generate(seed=seed)
    finally:
        os.remove(path)


def _statement_answer(task):
    s = [b.render_plain() for b in getattr(task, "statement", [])]
    a = [b.render_plain() for b in getattr(task, "answer", [])]
    return s, a


# Простой генератор «a+b» (полностью на инлайн-узлах).
def _arith_graph(seed):
    return {
        "nodes": [
            {"id": "ra", "type": "random_natural", "params": {"min": 1, "max": 9}},
            {"id": "rb", "type": "random_natural", "params": {"min": 1, "max": 9}},
            {"id": "vd", "type": "var_dict", "params": {"names": ["a", "b"]}},
            {"id": "f", "type": "formula", "params": {"expr": "a+b"}},
            {"id": "rvd", "type": "var_dict", "params": {"names": ["a", "b", "s"]}},
            {"id": "tpl", "type": "template", "params": {"text": "#a# + #b# = #s#"}},
            {"id": "tb", "type": "text_block"},
            {"id": "bl", "type": "block_list", "params": {"count": 1}},
            {"id": "avd", "type": "var_dict", "params": {"names": ["s"]}},
            {"id": "atpl", "type": "template", "params": {"text": "#s#"}},
            {"id": "atb", "type": "text_block"},
            {"id": "abl", "type": "block_list", "params": {"count": 1}},
            {"id": "task", "type": "static_task"},
        ],
        "edges": [
            {"from": "ra:out", "to": "vd:a"}, {"from": "rb:out", "to": "vd:b"},
            {"from": "vd:out", "to": "f:vars"},
            {"from": "ra:out", "to": "rvd:a"}, {"from": "rb:out", "to": "rvd:b"},
            {"from": "f:out", "to": "rvd:s"},
            {"from": "rvd:out", "to": "tpl:vars"}, {"from": "tpl:out", "to": "tb:text"},
            {"from": "tb:out", "to": "bl:in0"}, {"from": "bl:out", "to": "task:statement"},
            {"from": "f:out", "to": "avd:s"}, {"from": "avd:out", "to": "atpl:vars"},
            {"from": "atpl:out", "to": "atb:text"}, {"from": "atb:out", "to": "abl:in0"},
            {"from": "abl:out", "to": "task:answer"},
        ],
        "meta": {"seed": seed},
    }


# Граф на универсальном пути (linalg).
def _matrix_graph():
    return {
        "nodes": [
            {"id": "m", "type": "matrix_const", "params": {"data": "2,1;1,3"}},
            {"id": "d", "type": "matrix_det"},
            {"id": "blk", "type": "expr_block", "params": {"prefix": "det"}},
            {"id": "sbl", "type": "block_list", "params": {"count": 1}},
            {"id": "task", "type": "static_task"},
            {"id": "cn", "type": "constant_number", "params": {"value": 1}},
            {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
            {"id": "atpl", "type": "template", "params": {"text": "ответ"}},
            {"id": "atb", "type": "text_block"},
            {"id": "abl", "type": "block_list", "params": {"count": 1}},
        ],
        "edges": [
            {"from": "m:out", "to": "d:in"}, {"from": "d:out", "to": "blk:in"},
            {"from": "blk:out", "to": "sbl:in0"}, {"from": "sbl:out", "to": "task:statement"},
            {"from": "cn:out", "to": "avd:z"}, {"from": "avd:out", "to": "atpl:vars"},
            {"from": "atpl:out", "to": "atb:text"}, {"from": "atb:out", "to": "abl:in0"},
            {"from": "abl:out", "to": "task:answer"},
        ],
        "meta": {"seed": 5, "max_attempts": 1},
    }


class IdentTests(unittest.TestCase):
    def test_sanitizes(self):
        self.assertEqual(_ident("repeat_1"), "repeat_1")
        self.assertEqual(_ident("3bad"), "n_3bad")
        self.assertEqual(_ident("a-b.c"), "a_b_c")

    def test_keyword(self):
        self.assertEqual(_ident("class"), "class_")


class CompileSmokeTests(unittest.TestCase):
    def test_produces_valid_python(self):
        src = compile_graph(_arith_graph(1))
        # компилируется как валидный Python
        compile(src, "<compiled>", "exec")

    def test_has_generate_func(self):
        src = compile_graph(_arith_graph(1))
        self.assertIn("def generate(", src)
        self.assertIn("def _run(ctx):", src)


@unittest.skipUnless(HAS_QT, "нужен PyQt6 (блоки)")
class ParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_arith_parity_multiple_seeds(self):
        for seed in (1, 7, 42, 100, 2024):
            g = _arith_graph(seed)
            exec_task = GraphExecutor(GraphSpec.parse(g)).run()
            comp_task = _run_compiled(compile_graph(g), seed)
            self.assertEqual(_statement_answer(exec_task),
                             _statement_answer(comp_task),
                             f"расхождение на seed={seed}")

    def test_matrix_generic_path_parity(self):
        g = _matrix_graph()
        exec_task = GraphExecutor(GraphSpec.parse(g)).run()
        comp_task = _run_compiled(compile_graph(g), 5)
        self.assertEqual(_statement_answer(exec_task),
                         _statement_answer(comp_task))

    def test_compiled_runs_standalone(self):
        task = _run_compiled(compile_graph(_arith_graph(3)), 3)
        s, a = _statement_answer(task)
        self.assertTrue(s and a)
        # ответ — сумма из условия
        self.assertEqual(a[0], s[0].split("= ")[-1])

    def test_symbolic_parity(self):
        # expr_const -> factor -> expr_block (универсальный путь, symbolic)
        g = {
            "nodes": [
                {"id": "e", "type": "expr_const",
                 "params": {"expr": "x^2-1", "vars": ["x"]}},
                {"id": "f", "type": "factor"},
                {"id": "blk", "type": "expr_block", "params": {"prefix": "y"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "task", "type": "static_task"},
                {"id": "cn", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ok"}},
                {"id": "atb", "type": "text_block"},
                {"id": "abl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "e:out", "to": "f:in"}, {"from": "f:out", "to": "blk:in"},
                {"from": "blk:out", "to": "sbl:in0"},
                {"from": "sbl:out", "to": "task:statement"},
                {"from": "cn:out", "to": "avd:z"}, {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"}, {"from": "atb:out", "to": "abl:in0"},
                {"from": "abl:out", "to": "task:answer"},
            ],
            "meta": {"seed": 1, "max_attempts": 1},
        }
        exec_task = GraphExecutor(GraphSpec.parse(g)).run()
        comp_task = _run_compiled(compile_graph(g), 1)
        self.assertEqual(_statement_answer(exec_task),
                         _statement_answer(comp_task))

    def test_repeat_subgraph_parity(self):
        # repeat с вложенным телом — body передаётся через универсальный путь.
        body = {
            "nodes": [
                {"id": "li", "type": "loop_index"},
                {"id": "vd", "type": "var_dict", "params": {"names": ["i"]}},
                {"id": "tpl", "type": "template", "params": {"text": "строка #i#"}},
                {"id": "tb", "type": "text_block"},
            ],
            "edges": [
                {"from": "li:out", "to": "vd:i"},
                {"from": "vd:out", "to": "tpl:vars"},
                {"from": "tpl:out", "to": "tb:text"},
            ],
        }
        g = {
            "nodes": [
                {"id": "n", "type": "constant_number", "params": {"value": 3}},
                {"id": "rep", "type": "repeat", "params": {"count": 3, "body": body}},
                {"id": "task", "type": "static_task"},
                {"id": "cn", "type": "constant_number", "params": {"value": 1}},
                {"id": "avd", "type": "var_dict", "params": {"names": ["z"]}},
                {"id": "atpl", "type": "template", "params": {"text": "ok"}},
                {"id": "atb", "type": "text_block"},
                {"id": "abl", "type": "block_list", "params": {"count": 1}},
            ],
            "edges": [
                {"from": "n:out", "to": "rep:count"},
                {"from": "rep:out", "to": "task:statement"},
                {"from": "cn:out", "to": "avd:z"}, {"from": "avd:out", "to": "atpl:vars"},
                {"from": "atpl:out", "to": "atb:text"}, {"from": "atb:out", "to": "abl:in0"},
                {"from": "abl:out", "to": "task:answer"},
            ],
            "meta": {"seed": 1, "max_attempts": 1},
        }
        exec_task = GraphExecutor(GraphSpec.parse(g)).run()
        comp_task = _run_compiled(compile_graph(g), 1)
        self.assertEqual([b.render_plain() for b in exec_task.statement],
                         [b.render_plain() for b in comp_task.statement])


if __name__ == "__main__":
    unittest.main()
