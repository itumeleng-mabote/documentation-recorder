from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import Image

from docrecorder.capture.base import CaptureError, WindowInfo

_MIN_SIZE = 50
PW_RENDERFULLCONTENT = 2
SRCCOPY = 0x00CC0020
BI_RGB = 0
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOT = 2

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
    except OSError:
        dwmapi = None
else:
    user32 = None  # type: ignore[assignment]
    gdi32 = None  # type: ignore[assignment]
    kernel32 = None  # type: ignore[assignment]
    dwmapi = None


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class WindowsCapture:
    def __init__(self) -> None:
        self._enable_dpi_awareness()

    def list_windows(self, exclude_pids: list[int] | None = None) -> list[WindowInfo]:
        self._require_win32()
        exclude = set(exclude_pids or ())
        windows: list[WindowInfo] = []

        def callback(hwnd, _lparam):
            info = self._window_info(hwnd)
            if info is not None and info.pid not in exclude:
                windows.append(info)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return windows

    def get_window(self, window_id: int) -> WindowInfo | None:
        self._require_win32()
        hwnd = wintypes.HWND(window_id)
        if not user32.IsWindow(hwnd):
            return None
        return self._window_info(hwnd, require_visible=False)

    def capture(self, window_id: int) -> Image.Image:
        self._require_win32()
        hwnd = wintypes.HWND(window_id)
        if not user32.IsWindow(hwnd):
            raise CaptureError("The selected window no longer exists.")
        if user32.IsIconic(hwnd):
            raise CaptureError("The selected window is minimized.")

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise CaptureError("Could not read the window rectangle.")
        width = int(rect.right - rect.left)
        height = int(rect.bottom - rect.top)
        if width <= 0 or height <= 0:
            raise CaptureError("Window is minimized or has no size.")

        hwnd_dc = user32.GetWindowDC(hwnd)
        if not hwnd_dc:
            raise CaptureError("Could not get the window device context.")
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        old = gdi32.SelectObject(mem_dc, bmp)
        try:
            printed = user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)
            if not printed:
                screen_dc = user32.GetDC(0)
                gdi32.BitBlt(mem_dc, 0, 0, width, height, screen_dc, rect.left, rect.top, SRCCOPY)
                user32.ReleaseDC(0, screen_dc)

            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = width
            bmi.bmiHeader.biHeight = -height
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = BI_RGB
            buffer = ctypes.create_string_buffer(width * height * 4)
            bits = gdi32.GetDIBits(mem_dc, bmp, 0, height, buffer, ctypes.byref(bmi), 0)
            if bits == 0:
                raise CaptureError("Could not copy window pixels.")
            image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
            return image.copy()
        finally:
            gdi32.SelectObject(mem_dc, old)
            gdi32.DeleteObject(bmp)
            gdi32.DeleteDC(mem_dc)
            user32.ReleaseDC(hwnd, hwnd_dc)

    def _window_info(self, hwnd, require_visible: bool = True) -> WindowInfo | None:
        if require_visible and not user32.IsWindowVisible(hwnd):
            return None
        if user32.IsIconic(hwnd):
            return None
        if user32.GetAncestor(hwnd, GA_ROOT) != hwnd:
            return None
        if self._is_cloaked(hwnd):
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return None
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width = float(rect.right - rect.left)
        height = float(rect.bottom - rect.top)
        if width < _MIN_SIZE or height < _MIN_SIZE:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return WindowInfo(
            window_id=int(hwnd),
            title=title,
            app_name=self._process_name(pid.value),
            pid=int(pid.value),
            x=float(rect.left),
            y=float(rect.top),
            width=width,
            height=height,
        )

    def _is_cloaked(self, hwnd) -> bool:
        if dwmapi is None:
            return False
        cloaked = wintypes.DWORD(0)
        result = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return result == 0 and cloaked.value != 0

    def _process_name(self, pid: int) -> str:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return Path(buf.value).stem
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def _enable_dpi_awareness(self) -> None:
        if sys.platform != "win32":
            return
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass

    def _require_win32(self) -> None:
        if sys.platform != "win32" or user32 is None:
            raise CaptureError("Windows capture is only available on Windows.")

