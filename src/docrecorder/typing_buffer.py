from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TypingBuffer:
    idle_seconds: float = 1.5
    _parts: list[str] = field(default_factory=list)
    _last_event_at: float | None = None

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def has_text(self) -> bool:
        return bool(self._parts)

    def push_char(self, char: str, now: float) -> None:
        if not char:
            return
        self._parts.append(char)
        self._last_event_at = now

    def backspace(self, now: float) -> None:
        if self._parts:
            self._parts.pop()
        self._last_event_at = now

    def idle_due(self, now: float) -> bool:
        if not self._parts or self._last_event_at is None:
            return False
        return (now - self._last_event_at) >= self.idle_seconds

    def flush(self) -> str | None:
        if not self._parts:
            self._last_event_at = None
            return None
        text = "".join(self._parts)
        self._parts.clear()
        self._last_event_at = None
        return text
