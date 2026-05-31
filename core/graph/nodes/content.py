"""
Узлы-блоки контента — обёртки над core.blocks. Каждый принимает данные и
возвращает объект Block. Никакой новой логики рендеринга.

Импорт классов блоков — ленивый, внутри compute(): они тянут PyQt6, а движок
графа в остальном headless (нужен для тестов и будущего безоконного исполнения).
"""

from __future__ import annotations

from ..node import ExecContext, Node, Port
from ..port_types import PortType


class TextBlockNode(Node):
    """Текстовый блок из строки."""
    type_id = "text_block"
    category = "content"
    display_name = "Текстовый блок"
    INPUTS = [Port("text", PortType.STRING)]
    OUTPUTS = [Port("out", PortType.BLOCK)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock          # ленивый: тянет Qt
        return {"out": TextBlock(str(inputs.get("text", "")))}
