"""Read the accessible name of the control under a screen point via Windows UI Automation."""

from __future__ import annotations

import sys
import threading
import time
from typing import Any

SLOW_LOOKUP_SECONDS = 0.4
ANCESTOR_LIMIT = 3
# Stop walking up here: these name the window, not the thing that was clicked.
CONTAINER_TYPES = frozenset({50030, 50032, 50033, 50037})

# UIA_ControlTypeIds -> the vocabulary in docrecorder.vision.VALID_KINDS.
CONTROL_TYPE_KINDS = {
    50000: "button",
    50002: "checkbox",
    50003: "field",
    50004: "field",
    50005: "link",
    50006: "icon",
    50007: "item",
    50009: "menu",
    50010: "menu",
    50011: "menu",
    50013: "checkbox",
    50018: "tab",
    50019: "tab",
    50021: "menu",
    50024: "item",
    50029: "item",
    50031: "button",
    50035: "item",
}

_local = threading.local()


class UIAUnavailable(Exception):
    """Raised once when UI Automation cannot be used on this machine."""


def _automation() -> Any:
    cached = getattr(_local, "automation", None)
    if cached is not None:
        return cached
    if sys.platform != "win32":
        raise UIAUnavailable("UI Automation is only available on Windows.")
    try:
        import comtypes
        import comtypes.client
    except ImportError as exc:
        raise UIAUnavailable(
            "comtypes is not installed. Install it with: pip install -e .[uia]"
        ) from exc
    try:
        comtypes.CoInitialize()
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as client

        automation = comtypes.client.CreateObject(
            client.CUIAutomation,
            interface=client.IUIAutomation,
        )
    except Exception as exc:
        raise UIAUnavailable(f"UI Automation could not start: {exc}") from exc
    _local.automation = automation
    return automation


def _point(x: float, y: float) -> Any:
    import ctypes.wintypes

    return ctypes.wintypes.POINT(int(round(x)), int(round(y)))


def element_at_point(screen_x: float, screen_y: float) -> dict[str, str] | None:
    """Return {"label", "kind", "source"} for the control at a physical screen point."""
    automation = _automation()
    element = automation.ElementFromPoint(_point(screen_x, screen_y))
    walker = automation.ControlViewWalker
    for _ in range(ANCESTOR_LIMIT + 1):
        if element is None:
            return None
        control_type = int(element.CurrentControlType or 0)
        label = str(element.CurrentName or "").strip()
        if not label:
            label = str(element.CurrentAutomationId or "").strip()
        if label:
            return {
                "label": label,
                "kind": CONTROL_TYPE_KINDS.get(control_type, "unknown"),
                "source": "uia",
            }
        if control_type in CONTAINER_TYPES:
            return None
        element = walker.GetParentElement(element)
    return None


class ElementProbe:
    """Best-effort UIA lookups that disable themselves on failure or if they get slow."""

    def __init__(self) -> None:
        self.enabled = sys.platform == "win32"
        self.warning: str | None = None
        self._lookups = 0

    def lookup(self, screen_x: float, screen_y: float) -> dict[str, str] | None:
        if not self.enabled:
            return None
        started = time.monotonic()
        try:
            target = element_at_point(screen_x, screen_y)
        except UIAUnavailable as exc:
            self.enabled = False
            self.warning = str(exc)
            return None
        except Exception:
            self.enabled = False
            self.warning = "Reading control names failed; falling back to image recognition."
            return None
        elapsed = time.monotonic() - started
        self._lookups += 1
        # The first lookup pays for COM start-up, so it never counts against the budget.
        if self._lookups > 1 and elapsed > SLOW_LOOKUP_SECONDS:
            self.enabled = False
            self.warning = "Reading control names was too slow; falling back to image recognition."
        return target
