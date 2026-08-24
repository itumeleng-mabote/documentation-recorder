from __future__ import annotations

import sys

from PIL import Image

from docrecorder.capture.base import CaptureError, WindowInfo

if sys.platform == "darwin":
    import Quartz
else:
    Quartz = None  # type: ignore[assignment]


_MIN_SIZE = 50
_SKIP_OWNERS = {"Window Server", "Dock", "Control Center", "Notification Center"}


class MacOSCapture:
    def list_windows(self, exclude_pids: list[int] | None = None) -> list[WindowInfo]:
        self._require_quartz()
        exclude = set(exclude_pids or ())
        onscreen = self._collect(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            exclude,
        )
        others = self._collect(Quartz.kCGWindowListExcludeDesktopElements, exclude)
        merged: list[WindowInfo] = []
        seen: set[int] = set()
        for info in onscreen + others:
            if info.window_id in seen:
                continue
            seen.add(info.window_id)
            merged.append(info)
        merged.sort(key=lambda item: item.width * item.height, reverse=True)
        return merged

    def get_window(self, window_id: int) -> WindowInfo | None:
        self._require_quartz()
        raw_list = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionIncludingWindow,
            window_id,
        ) or []
        for item in raw_list:
            info = self._parse(item)
            if info is not None and info.window_id == window_id:
                return info
        for item in Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListExcludeDesktopElements, Quartz.kCGNullWindowID
        ) or []:
            info = self._parse(item)
            if info is not None and info.window_id == window_id:
                return info
        return None

    def _collect(self, options: int, exclude: set[int]) -> list[WindowInfo]:
        windows: list[WindowInfo] = []
        seen: set[int] = set()
        for item in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
            info = self._parse(item)
            if info is None or info.window_id in seen:
                continue
            if info.pid in exclude or info.app_name in _SKIP_OWNERS:
                continue
            if not self._is_pickable(item, info):
                continue
            seen.add(info.window_id)
            windows.append(info)
        return windows

    def capture(self, window_id: int) -> Image.Image:
        self._require_quartz()
        image_ref = Quartz.CGWindowListCreateImage(
            Quartz.CGRectNull,
            Quartz.kCGWindowListOptionIncludingWindow,
            window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageShouldBeOpaque,
        )
        if image_ref is None:
            raise CaptureError(
                "Window capture failed. Grant Screen Recording permission in System Settings."
            )
        return self._cgimage_to_pil(image_ref)

    def _parse(self, item) -> WindowInfo | None:
        window_id = int(item.get("kCGWindowNumber", 0) or 0)
        if window_id <= 0:
            return None
        bounds = item.get("kCGWindowBounds") or {}
        title = str(item.get("kCGWindowName") or "").strip()
        app_name = str(item.get("kCGWindowOwnerName") or "").strip()
        pid = int(item.get("kCGWindowOwnerPID", 0) or 0)
        return WindowInfo(
            window_id=window_id,
            title=title,
            app_name=app_name,
            pid=pid,
            x=float(bounds.get("X", 0) or 0),
            y=float(bounds.get("Y", 0) or 0),
            width=float(bounds.get("Width", 0) or 0),
            height=float(bounds.get("Height", 0) or 0),
        )

    def _is_pickable(self, item, info: WindowInfo) -> bool:
        layer = int(item.get("kCGWindowLayer", 0) or 0)
        if layer != 0:
            return False
        if info.width < _MIN_SIZE or info.height < _MIN_SIZE:
            return False
        if not info.title and not info.app_name:
            return False
        return True

    def _cgimage_to_pil(self, cg_image) -> Image.Image:
        width = int(Quartz.CGImageGetWidth(cg_image))
        height = int(Quartz.CGImageGetHeight(cg_image))
        if width <= 0 or height <= 0:
            raise CaptureError("Captured image was empty.")
        bytes_per_row = int(Quartz.CGImageGetBytesPerRow(cg_image))
        provider = Quartz.CGImageGetDataProvider(cg_image)
        raw = Quartz.CGDataProviderCopyData(provider)
        data = bytes(raw)
        image = Image.frombuffer(
            "RGBA",
            (width, height),
            data,
            "raw",
            "BGRA",
            bytes_per_row,
            1,
        )
        return image.convert("RGB").copy()

    def _require_quartz(self) -> None:
        if Quartz is None:
            raise CaptureError("macOS capture is only available on Darwin.")

