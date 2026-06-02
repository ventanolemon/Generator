"""
GraphHistory — буфер снимков графа для undo/redo.

Снимок = spec-dict документа (то, что отдаёт GraphDocument.to_spec_dict).
Документ полностью восстанавливается из снимка через from_spec_dict, поэтому
храним именно снимки целиком: это просто и надёжно (без отслеживания дельт),
а графы в редакторе небольшие.

Модель как у текстового редактора: указатель _index показывает на текущее
состояние. push() обрезает «хвост» redo и добавляет новый снимок. undo/redo
сдвигают указатель и возвращают соответствующий снимок (или None на границе).
"""

from __future__ import annotations

import copy


class GraphHistory:
    """Линейная история снимков с указателем текущего состояния."""

    def __init__(self, limit: int = 100):
        self._snaps: list[dict] = []
        self._index: int = -1
        self._limit = max(2, limit)

    def reset(self, snapshot: dict) -> None:
        """Начать историю заново с одного базового снимка (при загрузке графа)."""
        self._snaps = [copy.deepcopy(snapshot)]
        self._index = 0

    def push(self, snapshot: dict) -> None:
        """
        Зафиксировать новое состояние. Дубликат предыдущего снимка игнорируется
        (не засоряем историю повторами). Хвост redo обрезается.
        """
        snap = copy.deepcopy(snapshot)
        if 0 <= self._index < len(self._snaps) and self._snaps[self._index] == snap:
            return
        del self._snaps[self._index + 1:]
        self._snaps.append(snap)
        if len(self._snaps) > self._limit:
            self._snaps.pop(0)
        self._index = len(self._snaps) - 1

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return self._index < len(self._snaps) - 1

    def undo(self) -> dict | None:
        if not self.can_undo():
            return None
        self._index -= 1
        return copy.deepcopy(self._snaps[self._index])

    def redo(self) -> dict | None:
        if not self.can_redo():
            return None
        self._index += 1
        return copy.deepcopy(self._snaps[self._index])
