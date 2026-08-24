from __future__ import annotations


def point_in_rect(
    x: float,
    y: float,
    rect_x: float,
    rect_y: float,
    width: float,
    height: float,
) -> bool:
    return rect_x <= x < rect_x + width and rect_y <= y < rect_y + height


def to_local(x: float, y: float, rect_x: float, rect_y: float) -> tuple[float, float]:
    return x - rect_x, y - rect_y


def to_pixels(local_x: float, local_y: float, scale: float) -> tuple[int, int]:
    return int(round(local_x * scale)), int(round(local_y * scale))


def scale_from_image(image_width: int, image_height: int, logical_width: float, logical_height: float) -> float:
    if logical_width <= 0 or logical_height <= 0:
        return 1.0
    return max(image_width / logical_width, image_height / logical_height)
