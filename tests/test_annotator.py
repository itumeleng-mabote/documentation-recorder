from PIL import Image

from docrecorder.annotator import annotate_click, crop_around_click


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
    crop = crop_around_click(image, logical_x=400, logical_y=300, scale=1.0, size=480)
    assert crop.size == (480, 480)
    red, green, blue = crop.getpixel((240, 240))
    assert red > green
    assert red > blue


def test_crop_clamps_to_image_bounds():
    image = Image.new("RGB", (100, 80), (255, 255, 255))
    crop = crop_around_click(image, logical_x=5, logical_y=5, scale=1.0, size=480)
    assert crop.size == (100, 80)


def test_crop_does_not_mutate_source():
    image = Image.new("RGB", (200, 200), (10, 20, 30))
    crop_around_click(image, logical_x=100, logical_y=100, scale=1.0, size=80)
    assert image.getpixel((100, 100)) == (10, 20, 30)
