from .base import PartitionEditor
from .group_editor import GroupEditor
from .test_editor import TestEditor
from .fisic_editor import FisicEditor

__all__ = ["PartitionEditor", "GroupEditor", "TestEditor", "FisicEditor"]


def create_editor(kind: str, **kwargs) -> PartitionEditor:
    """
    Фабрика по строковому ключу editor_kind, который выдаёт Repository.editor_kind_for.

    Принимает kwargs для соответствующего конструктора.
    """
    if kind == "group":
        return GroupEditor(**kwargs)
    if kind == "test":
        return TestEditor(**kwargs)
    if kind == "fisic":
        # FisicEditor не нужен registry
        kwargs.pop("registry", None)
        return FisicEditor(**kwargs)
    raise ValueError(f"Неизвестный тип редактора: {kind}")
