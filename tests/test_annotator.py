from PIL import Image

from docrecorder.annotator import (
    annotate_click,
    apply_overlays,
    crop_around_click,
    mark_crop,
    normalize_annotation,
    upscale_for_vision,
)


def test_annotate_marks_scaled_click_pixel():
    image = Image.new("RGB", (200, 100), (255, 255, 255))
    out = annotate_click(image, logical_x=50, logical_y=40, scale=2.0)
    red, green, blue = out.getpixel((100, 80))
    assert red > 150
    assert red > green
    assert red > blue


def test_annotate_does_not_mutate_source():
    image = Image.new("RGB", (80, 80), (10, 20, 30))
    annotate_click(image, logical_x=10, logical_y=10, scale=1.0)
    assert image.getpixel((10, 10)) == (10, 20, 30)


def test_annotate_clamps_out_of_bounds():
    image = Image.new("RGB", (40, 40), (255, 255, 255))
    out = annotate_click(image, logical_x=400, logical_y=400, scale=1.0)
    red, green, _blue = out.getpixel((39, 39))
    assert red > green


def test_crop_centered_on_click():
    image = Image.new("RGB", (800, 600), (20, 40, 60))
    crop, cx, cy = crop_around_click(image, logical_x=400, logical_y=300, scale=1.0, size=480)
    assert crop.size == (480, 480)
    assert (cx, cy) == (240, 240)


def test_crop_is_unmarked():
    image = Image.new("RGB", (800, 600), (20, 40, 60))
    crop, cx, cy = crop_around_click(image, logical_x=400, logical_y=300, scale=1.0, size=480)
    assert crop.getpixel((cx, cy)) == (20, 40, 60)


def test_mark_crop_encircles_without_covering_click():
    image = Image.new("RGB", (800, 600), (20, 40, 60))
    crop, cx, cy = crop_around_click(image, logical_x=400, logical_y=300, scale=1.0, size=480)
    marked = mark_crop(crop, cx, cy)
    assert marked.getpixel((cx, cy)) == (20, 40, 60)
    radius = max(16, min(marked.width, marked.height) // 12)
    red, green, blue = marked.getpixel((cx + radius, cy))
    assert red > green
    assert red > blue


def test_upscale_for_vision_respects_max_side():
    assert upscale_for_vision(Image.new("RGB", (480, 480)), factor=2).size == (960, 960)
    assert upscale_for_vision(Image.new("RGB", (1000, 800)), factor=2).size == (1000, 800)


def test_crop_clamps_to_image_bounds():
    image = Image.new("RGB", (100, 80), (255, 255, 255))
    crop, _cx, _cy = crop_around_click(image, logical_x=5, logical_y=5, scale=1.0, size=480)
    assert crop.size == (100, 80)


def test_crop_does_not_mutate_source():
    image = Image.new("RGB", (200, 200), (10, 20, 30))
    crop_around_click(image, logical_x=100, logical_y=100, scale=1.0, size=80)
    assert image.getpixel((100, 100)) == (10, 20, 30)


def _is_red(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 150 and red > green and red > blue


def test_apply_overlay_rect_marks_edge():
    image = Image.new("RGB", (120, 120), (255, 255, 255))
    out = apply_overlays(
        image,
        [{"type": "rect", "color": "#E12D2D", "stroke": 6, "x1": 20, "y1": 20, "x2": 80, "y2": 80}],
    )
    assert any(_is_red(out.getpixel((x, 50))) for x in range(17, 24))
    assert image.getpixel((20, 50)) == (255, 255, 255)


def test_apply_overlay_arrow_marks_line():
    image = Image.new("RGB", (120, 80), (255, 255, 255))
    out = apply_overlays(
        image,
        [{"type": "arrow", "color": "#E12D2D", "stroke": 6, "x1": 10, "y1": 40, "x2": 100, "y2": 40}],
    )
    assert _is_red(out.getpixel((50, 40)))
    assert _is_red(out.getpixel((100, 40)))


def test_apply_overlay_circle_marks_ellipse():
    image = Image.new("RGB", (120, 120), (255, 255, 255))
    out = apply_overlays(
        image,
        [{"type": "circle", "color": "#E12D2D", "stroke": 6, "x1": 20, "y1": 20, "x2": 80, "y2": 80}],
    )
    assert any(_is_red(out.getpixel((50, y))) for y in range(17, 24))


def test_apply_overlay_text_paints():
    image = Image.new("RGB", (200, 80), (255, 255, 255))
    out = apply_overlays(
        image,
        [{"type": "text", "color": "#111827", "x1": 8, "y1": 8, "text": "Hello", "size": 28}],
    )
    assert out.tobytes() != image.tobytes()


def test_apply_overlays_ignores_empty_and_invalid():
    image = Image.new("RGB", (40, 40), (10, 20, 30))
    out = apply_overlays(image, [{"type": "unknown"}, {"type": "text", "text": "  "}])
    assert out.getpixel((10, 10)) == (10, 20, 30)


def test_normalize_annotation_round_trip():
    item = normalize_annotation(
        {"type": "arrow", "color": "#2563EB", "stroke": 3, "x1": 1.6, "y1": 2.2, "x2": 9, "y2": 8}
    )
    assert item == {
        "type": "arrow",
        "color": "#2563EB",
        "stroke": 3,
        "x1": 2,
        "y1": 2,
        "x2": 9,
        "y2": 8,
    }
    assert normalize_annotation({"type": "text", "text": ""}) is None
    assert normalize_annotation({"type": "line"}) is None
