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


class TextNode(Node):
    """
    Текстовый блок с подстановкой #имя# прямо из параметра. Объединяет шаблон,
    подстановку и обёртку в блок — для типового «текст с числами» достаточно
    ОДНОГО узла. Входы-числа создаются по маркерам #имя# в тексте; запасной
    вход vars (NUMBER_DICT) тоже принимается. Текст без маркеров — просто текст.
    """
    type_id = "text"
    category = "content"
    display_name = "Текст"
    description = ("Текстовый блок с подстановкой #имя# (числа на входах). "
                   "Один узел вместо шаблон+блок. Выход: BLOCK.")
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {"text": {"type": "text", "default": ""}}

    def input_ports(self):
        from .compute import _marker_names
        ports = [Port(n, PortType.NUMBER, required=False)
                 for n in _marker_names(self.params.get("text", ""))]
        ports.append(Port("vars", PortType.NUMBER_DICT, required=False))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock          # ленивый: тянет Qt
        from .compute import _fill_template
        return {"out": TextBlock(_fill_template(self.params.get("text", ""), inputs))}
