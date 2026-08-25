from __future__ import annotations

import math
from pathlib import Path
from typing import Any, NamedTuple

from PIL import Image, ImageDraw, ImageFont

ANNOTATION_TYPES = frozenset({"arrow", "rect", "circle", "text"})
DEFAULT_OVERLAY_COLOR = "#E12D2D"
DEFAULT_OVERLAY_STROKE = 4
DEFAULT_TEXT_SIZE = 32

_FONT_CANDIDATES = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "C:\\Windows\\Fonts\\arial.ttf",
    "C:\\Windows\\Fonts\\segoeui.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_font_cache: dict[int, ImageFont.ImageFont] = {}
_font_path: str | None | bool = False


def click_pixel(
    image: Image.Image,
    logical_x: float,
    logical_y: float,
    scale: float = 1.0,
) -> tuple[int, int]:
    px = int(round(logical_x * scale))
    py = int(round(logical_y * scale))
    px = max(0, min(image.width - 1, px))
    py = max(0, min(image.height - 1, py))
    return px, py


def annotate_click(
    image: Image.Image,
    logical_x: float,
    logical_y: float,
    scale: float = 1.0,
) -> Image.Image:
    """Draw a high-contrast click ring at logical window coordinates."""
    rgb = image.convert("RGB")
    overlay_base = rgb.convert("RGBA")
    overlay = Image.new("RGBA", overlay_base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    px, py = click_pixel(overlay, logical_x, logical_y, scale)

    radius = max(14, min(overlay.width, overlay.height) // 36)
    glow = radius + max(6, radius // 3)
    inner = max(4, radius // 4)

    _ellipse(draw, px, py, glow, fill=(255, 90, 20, 70), outline=None, width=0)
    _ellipse(draw, px, py, radius, fill=None, outline=(255, 45, 45, 255), width=max(3, radius // 6))
    _ellipse(draw, px, py, inner, fill=(255, 50, 50, 230), outline=(255, 255, 255, 220), width=2)

    return Image.alpha_composite(overlay_base, overlay).convert("RGB")


class ClickCrop(NamedTuple):
    image: Image.Image
    cx: int
    cy: int


def crop_around_click(
    image: Image.Image,
    logical_x: float,
    logical_y: float,
    scale: float = 1.0,
    size: int = 480,
) -> ClickCrop:
    """Crop around a click. Returns the unmarked crop and the click position inside it."""
    rgb = image.convert("RGB")
    px, py = click_pixel(rgb, logical_x, logical_y, scale)
    crop_w = min(size, rgb.width)
    crop_h = min(size, rgb.height)
    left = max(0, min(px - crop_w // 2, rgb.width - crop_w))
    top = max(0, min(py - crop_h // 2, rgb.height - crop_h))
    cropped = rgb.crop((left, top, left + crop_w, top + crop_h))
    return ClickCrop(cropped, px - left, py - top)


def mark_crop(crop: Image.Image, cx: int, cy: int) -> Image.Image:
    """Encircle the click point without painting over it, so the label stays readable."""
    overlay_base = crop.convert("RGBA")
    overlay = Image.new("RGBA", overlay_base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    radius = max(16, min(overlay.width, overlay.height) // 12)
    _ellipse(draw, cx, cy, radius, fill=None, outline=(255, 45, 45, 255), width=3)
    return Image.alpha_composite(overlay_base, overlay).convert("RGB")


def upscale_for_vision(image: Image.Image, factor: int = 2, max_side: int = 1400) -> Image.Image:
    """Enlarge a crop so small UI text survives the vision model's own downsampling."""
    long_side = max(image.width, image.height)
    if long_side <= 0:
        return image
    factor = min(factor, max(1, max_side // long_side))
    if factor <= 1:
        return image
    return image.resize((image.width * factor, image.height * factor), Image.LANCZOS)


def normalize_annotation(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "")
    if kind not in ANNOTATION_TYPES:
        return None
    try:
        x1 = int(round(float(raw.get("x1") or 0)))
        y1 = int(round(float(raw.get("y1") or 0)))
        x2 = int(round(float(raw.get("x2") if raw.get("x2") is not None else x1)))
        y2 = int(round(float(raw.get("y2") if raw.get("y2") is not None else y1)))
        stroke = int(raw.get("stroke") or DEFAULT_OVERLAY_STROKE)
    except (TypeError, ValueError):
        return None
    color = str(raw.get("color") or DEFAULT_OVERLAY_COLOR).strip() or DEFAULT_OVERLAY_COLOR
    if not color.startswith("#"):
        color = DEFAULT_OVERLAY_COLOR
    annotation: dict[str, Any] = {
        "type": kind,
        "color": color,
        "stroke": max(1, stroke),
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
    }
    if kind == "text":
        text = str(raw.get("text") or "")
        if not text.strip():
            return None
        try:
            size = int(raw.get("size") or DEFAULT_TEXT_SIZE)
        except (TypeError, ValueError):
            size = DEFAULT_TEXT_SIZE
        annotation["text"] = text
        annotation["size"] = max(8, size)
    return annotation


def apply_overlays(image: Image.Image, annotations: list[Any] | None) -> Image.Image:
    """Draw user overlays in image-pixel space. Does not mutate the source image."""
    rgb = image.convert("RGB")
    items = [normalized for item in (annotations or []) if (normalized := normalize_annotation(item))]
    if not items:
        return rgb
    overlay_base = rgb.convert("RGBA")
    overlay = Image.new("RGBA", overlay_base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for item in items:
        _draw_overlay(draw, item)
    return Image.alpha_composite(overlay_base, overlay).convert("RGB")


def _draw_overlay(draw: ImageDraw.ImageDraw, item: dict[str, Any]) -> None:
    color = _rgba(item["color"])
    stroke = int(item["stroke"])
    x1, y1, x2, y2 = item["x1"], item["y1"], item["x2"], item["y2"]
    kind = item["type"]
    if kind == "arrow":
        _draw_arrow(draw, x1, y1, x2, y2, color, stroke)
        return
    box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
    if kind == "rect":
        draw.rectangle(box, outline=color, width=stroke)
        return
    if kind == "circle":
        draw.ellipse(box, outline=color, width=stroke)
        return
    font = overlay_font(int(item.get("size") or DEFAULT_TEXT_SIZE))
    draw.text((x1, y1), str(item.get("text") or ""), fill=color, font=font)


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    color: tuple[int, int, int, int],
    stroke: int,
) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=color, width=stroke)
    angle = math.atan2(y2 - y1, x2 - x1)
    length = max(12, stroke * 4)
    left = (
        x2 - length * math.cos(angle - math.pi / 6),
        y2 - length * math.sin(angle - math.pi / 6),
    )
    right = (
        x2 - length * math.cos(angle + math.pi / 6),
        y2 - length * math.sin(angle + math.pi / 6),
    )
    draw.polygon([(x2, y2), left, right], fill=color)


def overlay_font(size: int) -> ImageFont.ImageFont:
    cached = _font_cache.get(size)
    if cached is not None:
        return cached
    path = _resolve_font_path()
    font: ImageFont.ImageFont
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _resolve_font_path() -> str | None:
    global _font_path
    if _font_path is not False:
        return _font_path
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            _font_path = candidate
            return candidate
    _font_path = None
    return None


def _rgba(value: str) -> tuple[int, int, int, int]:
    hex_color = value[1:] if value.startswith("#") else value
    if len(hex_color) != 6:
        hex_color = DEFAULT_OVERLAY_COLOR[1:]
    try:
        red = int(hex_color[0:2], 16)
        green = int(hex_color[2:4], 16)
        blue = int(hex_color[4:6], 16)
    except ValueError:
        return (225, 45, 45, 255)
    return (red, green, blue, 255)


def _ellipse(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    radius: int,
    *,
    fill,
    outline,
    width: int,
) -> None:
    box = [cx - radius, cy - radius, cx + radius, cy + radius]
    draw.ellipse(box, fill=fill, outline=outline, width=width)
