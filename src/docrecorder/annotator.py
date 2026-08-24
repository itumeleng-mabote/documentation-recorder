from __future__ import annotations

from typing import NamedTuple

from PIL import Image, ImageDraw


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
