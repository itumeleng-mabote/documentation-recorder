from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    title: str
    app_name: str
    pid: int
    x: float
    y: float
    width: float
    height: float

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.width, self.height)

    @property
    def label(self) -> str:
        title = self.title.strip()
        app_name = self.app_name.strip()
        if title and app_name and title != app_name:
            return f"{app_name} — {title}"
        return app_name or title or f"Window {self.window_id}"


class CaptureError(RuntimeError):
    """Raised when a window cannot be listed or captured."""
