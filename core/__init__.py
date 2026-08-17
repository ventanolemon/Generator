"""
Публичный API ядра. Всё, что нужно модулям, — импортируется отсюда.

Пример:
    from core import TaskGenerator, StaticTask, TextBlock, FormulaBlock, Capability

Импорт ленивый (PEP 562): подпакеты подгружаются только при первом обращении
к имени. Это нужно, чтобы чистые слои (контракт генератора, задачи, реестр,
движок графа) можно было импортировать headless — без PyQt6. Тяжёлые
Qt-зависимые модули (`blocks`, `dynamic_blocks`) и всё, что их тянет
(`composites`), подгружаются только когда их действительно используют.
Сам публичный API при этом не меняется.
"""

from __future__ import annotations
import importlib
from typing import Any

# Имя → модуль, в котором оно определено.
_EXPORTS: dict[str, str] = {
    # content
    "Block": ".content",
    # blocks (Qt)
    "TextBlock": ".blocks",
    "FormulaBlock": ".blocks",
    "ImageBlock": ".blocks",
    "CodeBlock": ".blocks",
    "TableBlock": ".blocks",
    "block_from_dict": ".blocks",
    "blocks_from_dicts": ".blocks",
    # dynamic blocks (Qt)
    "AudioBlock": ".dynamic_blocks",
    "FillInTheBlankBlock": ".dynamic_blocks",
    "TranscriptionChoiceBlock": ".dynamic_blocks",
    "WordCorrectionBlock": ".dynamic_blocks",
    # tasks
    "Task": ".task",
    "StaticTask": ".task",
    "InteractiveTask": ".task",
    "TurnResult": ".task",
    # generator contract
    "TaskGenerator": ".generator",
    "Capability": ".generator",
    "STATIC_DEFAULT": ".generator",
    "CHECKABLE_DEFAULT": ".generator",
    # спецификация ответа (headless: ни Qt, ни БД)
    "AnswerSpec": ".answers",
    "CheckMode": ".answers",
    "NumberSpec": ".answers",
    "TextSpec": ".answers",
    "ExpressionSpec": ".answers",
    "SlotsSpec": ".answers",
    "Tolerance": ".answers",
    "ToleranceKind": ".answers",
    "Verdict": ".answers",
    "InputField": ".answers",
    # реестр виджетов ответа
    "Widget": ".widgets",
    "widgets_for": ".widgets",
    "resolve_widget": ".widgets",
    # сценарий прохождения (headless)
    "Scenario": ".scenarios",
    "SessionMode": ".scenarios",
    "Layer": ".scenarios",
    "Setting": ".scenarios",
    "default_scenario": ".scenarios",
    # модель попытки (headless; запись — серверная)
    "AttemptRecord": ".attempts",
    "attempts_from_session": ".attempts",
    # общая интерактивная сессия (тянет blocks → Qt)
    "Question": ".interactive",
    "Outcome": ".interactive",
    "SpecSession": ".interactive",
    "session_from_task": ".interactive",
    "session_from_tasks": ".interactive",
    # registry
    "GeneratorRegistry": ".registry",
    "GeneratorFactory": ".registry",
    # composites (тянут blocks → Qt)
    "GroupGenerator": ".composites",
    "TestGenerator": ".composites",
    # data
    "Repository": ".repository",
    "Subject": ".repository",
    "Partition": ".repository",
    "WordStat": ".word_stats",
    "WordStatsStore": ".word_stats",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value          # кэшируем: повторный доступ без импорта
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
