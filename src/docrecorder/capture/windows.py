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
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GA_ROOT = 2
GA_ROOTOWNER = 3
GW_OWNER = 4
# Processes that host file pickers on behalf of another app.
_DIALOG_HOST_PROCESSES = {"explorer", "pickerhost", "dllhost", "applicationframehost"}
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}

if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # HWNDs are pointer-sized; without these the default c_int restype truncates them.
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmGetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
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
        hwnd = int(window_id)
        if not user32.IsWindow(hwnd):
            return None
        return self._window_info(hwnd, require_visible=False)

    def resolve_active_window(
        self,
        window_id: int,
        x: float | None = None,
        y: float | None = None,
    ) -> WindowInfo | None:
        """The recorded window, or a dialog it opened (file picker, message box)."""
        self._require_win32()
        base = self.get_window(window_id)
        if x is None or y is None:
            candidate = user32.GetForegroundWindow()
        else:
            candidate = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
            if candidate:
                candidate = user32.GetAncestor(candidate, GA_ROOT)
        if not candidate or int(candidate) == int(window_id):
            return base
        if not self._is_companion(candidate, int(window_id)):
            return base
        return self._window_info(candidate, require_visible=False) or base

    def _is_companion(self, hwnd, root_id: int) -> bool:
        if user32.GetAncestor(hwnd, GA_ROOTOWNER) == root_id:
            return True
        owner = user32.GetWindow(hwnd, GW_OWNER)
        seen = 0
        while owner and seen < 8:
            if int(owner) == root_id:
                return True
            owner = user32.GetWindow(owner, GW_OWNER)
            seen += 1
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        root_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(root_id), ctypes.byref(root_pid))
        if pid.value and pid.value == root_pid.value:
            return True
        if self._class_name(hwnd) in _SHELL_CLASSES:
            return False
        if user32.GetForegroundWindow() != hwnd:
            return False
        return self._process_name(pid.value).lower() in _DIALOG_HOST_PROCESSES

    def _class_name(self, hwnd) -> str:
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, len(buf))
        return buf.value

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
            return self._crop_to_frame(hwnd, image, rect).copy()
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
        rect = self._extended_frame_bounds(hwnd) or rect
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

    def _extended_frame_bounds(self, hwnd):
        """Visible frame, excluding the invisible DWM resize border and drop shadow."""
        if dwmapi is None:
            return None
        bounds = wintypes.RECT()
        result = dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(bounds),
            ctypes.sizeof(bounds),
        )
        if result != 0 or bounds.right <= bounds.left or bounds.bottom <= bounds.top:
            return None
        return bounds

    def _crop_to_frame(self, hwnd, image: Image.Image, rect) -> Image.Image:
        bounds = self._extended_frame_bounds(hwnd)
        if bounds is None:
            return image
        left = max(0, int(bounds.left - rect.left))
        top = max(0, int(bounds.top - rect.top))
        right = min(image.width, image.width - int(rect.right - bounds.right))
        bottom = min(image.height, image.height - int(rect.bottom - bounds.bottom))
        if right - left < _MIN_SIZE or bottom - top < _MIN_SIZE:
            return image
        if (left, top, right, bottom) == (0, 0, image.width, image.height):
            return image
        return image.crop((left, top, right, bottom))

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

