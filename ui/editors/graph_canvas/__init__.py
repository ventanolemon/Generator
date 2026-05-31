"""
Визуальный канвас графа (Qt). Слой поверх чистой модели core.graph.GraphDocument.

Сцена ничего не вычисляет: она редактирует GraphDocument и сериализует его в
тот же GraphSpec, что исполняет движок. Вся «умность» (типы, retry, генерация)
живёт в core.graph.
"""

from .scene import GraphScene, GraphCanvasView
from .palette import NodePalette

__all__ = ["GraphScene", "GraphCanvasView", "NodePalette"]
