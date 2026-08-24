from docrecorder.capture.coords import point_in_rect, scale_from_image, to_local, to_pixels


def test_point_in_rect_inside_and_edges():
    assert point_in_rect(10, 20, 10, 20, 100, 50)
    assert not point_in_rect(110, 20, 10, 20, 100, 50)
    assert not point_in_rect(10, 70, 10, 20, 100, 50)
    assert not point_in_rect(9, 20, 10, 20, 100, 50)


def test_to_local_and_pixels_retina_scale():
    local_x, local_y = to_local(240, 160, 100, 80)
    assert (local_x, local_y) == (140, 80)
    assert to_pixels(local_x, local_y, 2.0) == (280, 160)


def test_scale_from_image():
    assert scale_from_image(2000, 1200, 1000, 600) == 2.0
    assert scale_from_image(800, 600, 800, 600) == 1.0
    assert scale_from_image(100, 100, 0, 10) == 1.0
