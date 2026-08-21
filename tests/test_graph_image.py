"""
Тесты узлов изображений / ОПВС: logic_circuit, image_file, image_block.

Все узлы тянут PIL/Qt (рендер схем, ImageBlock) — под Qt (offscreen).
"""

from __future__ import annotations
import os
import random
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.graph import (
    DEFAULT_REGISTRY, ExecContext, GraphExecutor, GraphSpec, PortType,
)
from tests.tmpdb import temp_path  # noqa: E402

try:
    import PyQt6  # noqa: F401
    from PIL import Image  # noqa: F401
    HAS_DEPS = True
except Exception:
    HAS_DEPS = False


def _ctx(seed=0):
    return ExecContext(rng=random.Random(seed))


class RegistryTests(unittest.TestCase):
    def test_nodes_registered(self):
        ids = {e["type_id"] for e in DEFAULT_REGISTRY.palette()}
        for tid in ("logic_circuit", "image_file", "image_block"):
            self.assertIn(tid, ids)

    def test_image_category(self):
        cats = {e["category"] for e in DEFAULT_REGISTRY.palette()}
        self.assertIn("image", cats)

    def test_image_type_exists(self):
        self.assertTrue(hasattr(PortType, "IMAGE"))


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и Pillow")
class LogicCircuitTests(unittest.TestCase):
    def test_produces_image_and_formula(self):
        from core.graph.nodes.image import LogicCircuitNode
        from PIL import Image
        random.seed(1)
        out = LogicCircuitNode("c", {}).compute({}, _ctx())
        self.assertIsInstance(out["image"], Image.Image)
        self.assertIsInstance(out["formula"], str)
        self.assertTrue(out["formula"])

    def test_outputs_typed(self):
        from core.graph.nodes.image import LogicCircuitNode
        ports = {p.name: p.type for p in LogicCircuitNode("c", {}).output_ports()}
        self.assertEqual(ports["image"], PortType.IMAGE)
        self.assertEqual(ports["formula"], PortType.STRING)


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и Pillow")
class ImageBlockTests(unittest.TestCase):
    def test_wraps_image(self):
        from core.graph.nodes.image import ImageBlockNode
        from core.blocks import ImageBlock
        from PIL import Image
        img = Image.new("RGB", (10, 10), "white")
        out = ImageBlockNode("b", {"caption": "Подпись"}).compute({"in": img}, _ctx())["out"]
        self.assertIsInstance(out, ImageBlock)
        self.assertIn("Подпись", out.render_plain())

    def test_missing_image_retries(self):
        from core.graph.nodes.image import ImageBlockNode
        from core.graph import RetryGeneration
        with self.assertRaises(RetryGeneration):
            ImageBlockNode("b", {}).compute({}, _ctx())


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и Pillow")
class ImageFileTests(unittest.TestCase):
    def _png(self):
        import tempfile
        from PIL import Image
        path = temp_path(suffix=".png")
        Image.new("RGB", (20, 20), "blue").save(path)
        return path

    def test_loads_image(self):
        from core.graph.nodes.image import ImageFileNode
        from PIL import Image
        path = self._png()
        try:
            out = ImageFileNode("f", {"file": path}).compute({}, _ctx())["out"]
            self.assertIsInstance(out, Image.Image)
            self.assertEqual(out.size, (20, 20))
        finally:
            os.remove(path)

    def test_empty_file_validate(self):
        from core.graph.nodes.image import ImageFileNode
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            ImageFileNode("f", {"file": ""})

    def test_missing_file_raises(self):
        from core.graph.nodes.image import ImageFileNode
        from core.graph import GraphValidationError
        with self.assertRaises(GraphValidationError):
            ImageFileNode("f", {"file": "/nonexistent/x.png"}).compute({}, _ctx())


@unittest.skipUnless(HAS_DEPS, "нужны PyQt6 и Pillow")
class FullGraphTests(unittest.TestCase):
    def test_circuit_to_task(self):
        # logic_circuit -> image_block (statement) + formula -> text_block (answer)
        graph = {
            "nodes": [
                {"id": "c", "type": "logic_circuit"},
                {"id": "ib", "type": "image_block", "params": {"caption": "Схема"}},
                {"id": "sbl", "type": "block_list", "params": {"count": 1}},
                {"id": "atb", "type": "text_block"},
                {"id": "abl", "type": "block_list", "params": {"count": 1}},
                {"id": "task", "type": "static_task"},
            ],
            "edges": [
                {"from": "c:image", "to": "ib:in"},
                {"from": "ib:out", "to": "sbl:in0"},
                {"from": "sbl:out", "to": "task:statement"},
                {"from": "c:formula", "to": "atb:text"},
                {"from": "atb:out", "to": "abl:in0"},
                {"from": "abl:out", "to": "task:answer"},
            ],
            "meta": {"seed": 2, "max_attempts": 3},
        }
        task = GraphExecutor(GraphSpec.parse(graph)).run()
        from core.task import StaticTask
        from core.blocks import ImageBlock
        self.assertIsInstance(task, StaticTask)
        self.assertIsInstance(task.statement[0], ImageBlock)
        self.assertTrue(task.answer[0].render_plain())


if __name__ == "__main__":
    unittest.main()
