from __future__ import annotations

import sys

from docrecorder.capture.base import CaptureError, WindowInfo

__all__ = ["CaptureError", "WindowInfo", "get_capture"]


def get_capture():
    if sys.platform == "darwin":
        from docrecorder.capture.macos import MacOSCapture

        return MacOSCapture()
    if sys.platform == "win32":
        from docrecorder.capture.windows import WindowsCapture

        return WindowsCapture()
    raise CaptureError("Unsupported platform. Documentation Recorder supports macOS and Windows.")
