"""
Доказательство, что граф воспроизводит физику headless.

Строится граф, эквивалентный физической задаче «путь = v * t, натуральный,
1..500». Многократный прогон проверяет, что:
  * результат всегда равен v * t,
  * ограничение natural / [1, 500] реально соблюдается (значит, whole-graph
    retry работает — без него произведение могло бы превысить 500),
  * подстановка #v#/#t# в шаблон не оставляет маркеров.

Эти проверки не требуют PyQt6 (читаем выходы compute-узлов напрямую).
Полная сборка StaticTask и GraphConstructorGenerator тестируются отдельно
под skipUnless(PyQt6) — они создают TextBlock, который тянет Qt.
"""

from __future__ import annotations
import unittest

from core.graph import GraphExecutor, GraphSpec

try:
    import PyQt6  # noqa: F401
    HAS_QT = True
except Exception:
    HAS_QT = False


def physics_math_graph(vmax=50, tmax=50, rmax=500):
    """Граф до уровня строк (без узлов-блоков): источники → формула → проверка → шаблоны."""
    return {
        "version": 1,
        "nodes": [
            {"id": "v",    "type": "random_natural", "params": {"min": 1, "max": vmax}},
            {"id": "t",    "type": "random_natural", "params": {"min": 1, "max": tmax}},
            {"id": "vars", "type": "var_dict",       "params": {"names": ["v", "t"]}},
            {"id": "f",    "type": "formula",         "params": {"expr": "v * t"}},
            {"id": "chk",  "type": "constraint",
             "params": {"kind": "natural", "min": 1, "max": rmax}},
            {"id": "res",  "type": "var_dict",        "params": {"names": ["N"]}},
            {"id": "cond", "type": "template",
             "params": {"text": "Путь при v=#v#, t=#t#."}},
            {"id": "ans",  "type": "template",        "params": {"text": "N = #N#"}},
        ],
        "edges": [
            {"from": "v:out",    "to": "vars:v"},
            {"from": "t:out",    "to": "vars:t"},
            {"from": "vars:out", "to": "f:vars"},
            {"from": "f:out",    "to": "chk:in"},
            {"from": "chk:out",  "to": "res:N"},
            {"from": "vars:out", "to": "cond:vars"},
            {"from": "res:out",  "to": "ans:vars"},
        ],
        "meta": {"max_attempts": 200},
    }


class PhysicsReproductionTests(unittest.TestCase):
    def test_result_consistency_and_constraint_over_many_runs(self):
        ex = GraphExecutor(GraphSpec.parse(physics_math_graph()))
        for _ in range(300):
            out = ex.run_full()
            v = out["vars"]["out"]["v"]
            t = out["vars"]["out"]["t"]
            result = out["chk"]["out"]
            # формула воспроизведена
            self.assertEqual(result, v * t)
            # ограничение соблюдено (доказывает работу retry)
            self.assertEqual(result, round(result))
            self.assertGreaterEqual(result, 1)
            self.assertLessEqual(result, 500)
            # подстановка завершена
            self.assertNotIn("#", out["cond"]["out"])
            self.assertTrue(out["ans"]["out"].startswith("N = "))

    def test_seed_makes_run_deterministic(self):
        data = physics_math_graph()
        data["meta"]["seed"] = 12345
        a = GraphExecutor(GraphSpec.parse(data)).run_full()
        b = GraphExecutor(GraphSpec.parse(data)).run_full()
        self.assertEqual(a["vars"]["out"], b["vars"]["out"])
        self.assertEqual(a["chk"]["out"], b["chk"]["out"])

    def test_impossible_constraint_exhausts(self):
        from core.graph import GraphError
        # v,t ≥ 40 → произведение ≥ 1600, а максимум результата 100.
        data = physics_math_graph(vmax=40, tmax=40, rmax=100)
        # сузим минимум источников, чтобы произведение точно превышало 100
        data["nodes"][0]["params"] = {"min": 40, "max": 50}
        data["nodes"][1]["params"] = {"min": 40, "max": 50}
        data["meta"]["max_attempts"] = 20
        ex = GraphExecutor(GraphSpec.parse(data))
        with self.assertRaises(GraphError):
            ex.run_full()


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен — пропуск тестов с блоками")
class FullPipelineTests(unittest.TestCase):
    def test_generator_produces_static_task(self):
        from exercises.graph.generators import EXAMPLE_GRAPH, GraphConstructorGenerator
        from core import StaticTask
        gen = GraphConstructorGenerator(partition_id=0, name="demo", config=EXAMPLE_GRAPH)
        task = gen.generate()
        self.assertIsInstance(task, StaticTask)
        self.assertEqual(len(task.statement), 1)
        self.assertEqual(len(task.answer), 1)
        self.assertNotIn("#", task.statement[0].render_plain())


if __name__ == "__main__":
    unittest.main()
