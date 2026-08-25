from __future__ import annotations

import copy
from typing import Any

MAX_HISTORY = 50


class EditHistory:
    """Snapshot stack for preview-editor undo/redo."""

    def __init__(self, limit: int = MAX_HISTORY) -> None:
        self._undo: list[list[dict[str, Any]]] = []
        self._redo: list[list[dict[str, Any]]] = []
        self._limit = limit

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, state: list[dict[str, Any]]) -> None:
        snapshot = copy.deepcopy(state)
        if self._undo and self._undo[-1] == snapshot:
            return
        self._undo.append(snapshot)
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self, current: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if not self._undo:
            return None
        self._redo.append(copy.deepcopy(current))
        return copy.deepcopy(self._undo.pop())

    def redo(self, current: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
        if not self._redo:
            return None
        self._undo.append(copy.deepcopy(current))
        if len(self._undo) > self._limit:
            self._undo.pop(0)
        return copy.deepcopy(self._redo.pop())
