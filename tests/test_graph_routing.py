"""
Тесты совместной трассировки проводов (core/graph/routing.py) и медианной
раскладки по слоям. Проверяются ГАРАНТИИ трассировщика (те же, что у ОПВС):
ортогональность, отсутствие наложений сегментов разных цепей, обход тел
узлов — на синтетических случаях и на реальных графах-примерах.

Headless (Qt не нужен). Qt-интеграция сцены — tests/test_graph_routing_qt.py.
"""

from __future__ import annotations
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.graph.document import GraphDocument  # noqa: E402
from core.graph.routing import EdgeSpec, TRACK_SEP, route_edges  # noqa: E402

NODE_W, HEADER_H, ROW_H = 180.0, 26.0, 22.0


# ---------- Помощники: сцена из документа ----------

def _node_rect(doc: GraphDocument, nid: str) -> tuple:
    node = doc.nodes[nid]
    ins, outs = doc.ports(nid)
    h = HEADER_H + max(len(ins), len(outs), 1) * ROW_H + 8
    return (node.x, node.y, NODE_W, h)


def _port_point(doc: GraphDocument, nid: str, port: str, side: str) -> tuple:
    node = doc.nodes[nid]
    ins, outs = doc.ports(nid)
    names = [p.name for p in (ins if side == "in" else outs)]
    idx = names.index(port)
    x = node.x if side == "in" else node.x + NODE_W
    return (x, node.y + HEADER_H + ROW_H / 2 + idx * ROW_H)


def _specs_for(doc: GraphDocument):
    rects = {nid: _node_rect(doc, nid) for nid in doc.nodes}
    specs = []
    for i, e in enumerate(doc.edges):
        specs.append(EdgeSpec(
            key=i,
            src=_port_point(doc, e.from_node, e.from_port, "out"),
            dst=_port_point(doc, e.to_node, e.to_port, "in"),
            net=(e.from_node, e.from_port),
            src_node=e.from_node,
            dst_node=e.to_node,
        ))
    return rects, specs


# ---------- Помощники: проверка гарантий ----------

def _segments(route: list) -> list[tuple]:
    """[(ориентация, конст-координата, лежащий диапазон, конец1, конец2)]"""
    segs = []
    for a, b in zip(route, route[1:]):
        if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
            continue
        if abs(a[1] - b[1]) < 1e-6:
            segs.append(("h", a[1], (min(a[0], b[0]), max(a[0], b[0]))))
        elif abs(a[0] - b[0]) < 1e-6:
            segs.append(("v", a[0], (min(a[1], b[1]), max(a[1], b[1]))))
        else:
            segs.append(("diagonal", 0.0, (0.0, 0.0)))
    return segs


def _overlaps(routes: dict, nets: dict) -> list[str]:
    """Наложения параллельных сегментов РАЗНЫХ цепей (гарантия №1 ОПВС)."""
    flat = []
    for key, route in routes.items():
        for seg in _segments(route):
            flat.append((key, nets[key], seg))
    bad = []
    for i in range(len(flat)):
        for j in range(i + 1, len(flat)):
            k1, n1, (o1, c1, r1) = flat[i]
            k2, n2, (o2, c2, r2) = flat[j]
            if n1 == n2 or o1 != o2 or o1 == "diagonal":
                continue
            if abs(c1 - c2) >= 1.0:      # разные линии — не наложение
                continue
            if max(r1[0], r2[0]) < min(r1[1], r2[1]) - 1e-6:
                bad.append(f"{o1}-наложение рёбер {k1} и {k2} на {c1:.0f}: "
                           f"{r1} × {r2}")
    return bad


def _body_hits(routes: dict, rects: dict, specs: list) -> list[str]:
    """Сегменты, проходящие сквозь тела ЧУЖИХ узлов (свои — порты/усы)."""
    own = {s.key: {s.src_node, s.dst_node} for s in specs}
    bad = []
    for key, route in routes.items():
        for orient, const, rng in _segments(route):
            for nid, (x, y, w, h) in rects.items():
                if nid in own[key]:
                    continue
                l, t, r, b = x + 1, y + 1, x + w - 1, y + h - 1
                if orient == "h" and t < const < b and \
                        max(rng[0], l) < min(rng[1], r):
                    bad.append(f"ребро {key}: h-сегмент y={const:.0f} сквозь {nid}")
                if orient == "v" and l < const < r and \
                        max(rng[0], t) < min(rng[1], b):
                    bad.append(f"ребро {key}: v-сегмент x={const:.0f} сквозь {nid}")
    return bad


def _route_and_check(tc: unittest.TestCase, doc: GraphDocument):
    rects, specs = _specs_for(doc)
    routes = route_edges(rects, specs)
    nets = {s.key: s.net for s in specs}

    tc.assertEqual(set(routes), {s.key for s in specs}, "все рёбра проложены")
    for s in specs:
        route = routes[s.key]
        tc.assertEqual(route[0], s.src, "трасса начинается в выходном порту")
        tc.assertEqual(route[-1], s.dst, "трасса кончается во входном порту")
        for seg in _segments(route):
            tc.assertNotEqual(seg[0], "diagonal",
                              f"неортогональный сегмент в ребре {s.key}")

    tc.assertEqual(_overlaps(routes, nets), [], "наложения сегментов разных цепей")
    tc.assertEqual(_body_hits(routes, rects, specs), [], "трассы сквозь узлы")
    return routes


# ---------- Синтетика: худшие случаи старого роутера ----------

class OverlapRegressionTests(unittest.TestCase):
    """Случаи, где старый одиночный Z-роутер гарантированно накладывал."""

    def test_parallel_edges_between_two_columns_do_not_overlap(self):
        # 4 источника → 4 приёмника, один канал: у старого роутера все
        # вертикали ложились на общую середину канала.
        doc = GraphDocument()
        for i in range(4):
            doc.add_node("random_natural", {}, x=40, y=40 + i * 140,
                         node_id=f"s{i}")
        doc.add_node("var_dict", {"names": ["a", "b", "c", "d"]},
                     x=520, y=200, node_id="v")
        for i, name in enumerate(["a", "b", "c", "d"]):
            doc.add_edge(f"s{i}", "out", "v", name)
        _route_and_check(self, doc)

    def test_same_row_sources_do_not_overlap_horizontally(self):
        # Два источника на одной Y-координате в соседних колонках — их
        # горизонтальные сегменты идут по одной прямой.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, x=40, y=100, node_id="a")
        doc.add_node("random_natural", {}, x=300, y=100, node_id="b")
        doc.add_node("var_dict", {"names": ["x", "y"]},
                     x=640, y=80, node_id="v")
        doc.add_edge("a", "out", "v", "x")
        doc.add_edge("b", "out", "v", "y")
        _route_and_check(self, doc)

    def test_fanout_from_one_port_is_allowed_to_share(self):
        # Один выход на три входа: сегменты одной цепи МОГУТ совпадать
        # (это один сигнал) — роутер не должен их разгонять или падать.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, x=40, y=200, node_id="s")
        doc.add_node("var_dict", {"names": ["a"]}, x=520, y=40, node_id="v1")
        doc.add_node("var_dict", {"names": ["a"]}, x=520, y=220, node_id="v2")
        doc.add_node("var_dict", {"names": ["a"]}, x=520, y=400, node_id="v3")
        for v in ("v1", "v2", "v3"):
            doc.add_edge("s", "out", v, "a")
        _route_and_check(self, doc)

    def test_backward_edge_routes_around_nodes(self):
        # Вход левее выхода (обратное ребро) — перелёт, не диагональ и не
        # проход сквозь узлы.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, x=600, y=200, node_id="s")
        doc.add_node("var_dict", {"names": ["a"]}, x=60, y=200, node_id="v")
        doc.add_node("constant_number", {"value": 1}, x=330, y=200, node_id="mid")
        doc.add_edge("s", "out", "v", "a")
        _route_and_check(self, doc)

    def test_track_through_node_body_is_avoided(self):
        # Узел стоит ровно в канале между источником и приёмником.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, x=40, y=200, node_id="s")
        doc.add_node("constant_number", {"value": 1}, x=330, y=170,
                     node_id="wall")
        doc.add_node("var_dict", {"names": ["a"]}, x=700, y=200, node_id="v")
        doc.add_edge("s", "out", "v", "a")
        _route_and_check(self, doc)


# ---------- Реальные графы-примеры + раскладка ----------

class ExampleGraphTests(unittest.TestCase):
    """Раскладка по слоям + трассировка на реальных графах витрины."""

    def _check_example(self, name: str):
        from exercises.graph_examples import EXAMPLES
        doc = GraphDocument.from_spec_dict(EXAMPLES[name]["graph"])
        doc.apply_layered_layout(y_gap=170.0)
        _route_and_check(self, doc)

    def test_physics_force(self):
        self._check_example("physics_force")

    def test_series_table(self):
        # Граф с циклом-таблицей — больше слоёв и рёбер.
        from exercises.graph_examples import EXAMPLES
        for name in EXAMPLES:
            if "table" in name or "cycle" in name or "loop" in name:
                self._check_example(name)
                return
        self.skipTest("нет примера с таблицей")

    def test_all_examples_route_clean(self):
        from exercises.graph_examples import EXAMPLES
        for name in EXAMPLES:
            with self.subTest(example=name):
                self._check_example(name)


class MedianLayoutTests(unittest.TestCase):
    """Медианное упорядочение слоёв (перенос из ОПВС calculate_positions)."""

    def test_consumer_aligns_with_its_sources(self):
        # Три источника; потребитель c питается от нижней пары, потребитель
        # d — от верхней. При порядке добавления d>c старая раскладка ставила
        # d ниже c, порождая пересечение; медианная — разводит.
        doc = GraphDocument()
        doc.add_node("random_natural", {}, node_id="s0")   # строка 0
        doc.add_node("random_natural", {}, node_id="s1")   # строка 1
        doc.add_node("random_natural", {}, node_id="s2")   # строка 2
        doc.add_node("var_dict", {"names": ["a", "b"]}, node_id="c")
        doc.add_node("var_dict", {"names": ["a", "b"]}, node_id="d")
        # c ← нижние (s1, s2); d ← верхние (s0, s1). Добавлен c раньше d.
        doc.add_edge("s1", "out", "c", "a")
        doc.add_edge("s2", "out", "c", "b")
        doc.add_edge("s0", "out", "d", "a")
        doc.add_edge("s1", "out", "d", "b")

        pos = doc.layered_positions()
        self.assertLess(pos["d"][1], pos["c"][1],
                        "потребитель верхних источников лёг выше")

    def test_sources_keep_insertion_order(self):
        doc = GraphDocument()
        doc.add_node("random_natural", {}, node_id="b_src")
        doc.add_node("random_natural", {}, node_id="a_src")
        pos = doc.layered_positions()
        self.assertLess(pos["b_src"][1], pos["a_src"][1],
                        "слой 0 — в порядке добавления")

    def test_layout_positions_do_not_collide(self):
        from exercises.graph_examples import EXAMPLES
        doc = GraphDocument.from_spec_dict(EXAMPLES["physics_force"]["graph"])
        pos = doc.layered_positions()
        self.assertEqual(len(set(pos.values())), len(pos), "без коллизий")


if __name__ == "__main__":
    unittest.main()
