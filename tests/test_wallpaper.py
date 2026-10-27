"""Tests for crop and render maths.

These deliberately never call ``set_wallpaper``: it would change the desktop
background of whoever runs the suite. Only the pure image work is exercised.
"""

from pathlib import Path

import pytest

from wallpaper_manager.wallpaper import WallpaperError, crop_rect, render_wallpaper

SIXTEEN_NINE = 16 / 9


def test_crop_of_matching_image_is_the_whole_image():
    rect = crop_rect(1920, 1080, SIXTEEN_NINE)
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == (0, 0, 1920, 1080)


def test_too_wide_image_is_trimmed_at_the_sides():
    rect = crop_rect(4000, 1000, 2.0)
    assert rect.height() == 1000, "full height is kept"
    assert rect.width() == 2000
    assert rect.x() == 1000, "crop is centred"
    assert rect.y() == 0


def test_too_tall_image_is_trimmed_top_and_bottom():
    rect = crop_rect(1000, 4000, 2.0)
    assert rect.width() == 1000, "full width is kept"
    assert rect.height() == 500
    assert rect.y() == 1750, "crop is centred"
    assert rect.x() == 0


def test_crop_never_exceeds_the_source():
    for width, height in ((1920, 1080), (100, 3000), (3000, 100), (7, 7)):
        rect = crop_rect(width, height, SIXTEEN_NINE)
        assert rect.x() >= 0 and rect.y() >= 0
        assert rect.x() + rect.width() <= width
        assert rect.y() + rect.height() <= height


def test_position_slides_a_wide_crop_horizontally():
    left = crop_rect(4000, 1000, 2.0, position=0.0)
    centre = crop_rect(4000, 1000, 2.0, position=0.5)
    right = crop_rect(4000, 1000, 2.0, position=1.0)

    assert (left.x(), centre.x(), right.x()) == (0, 1000, 2000)
    assert right.x() + right.width() == 4000, "flush against the right edge"
    assert {r.y() for r in (left, centre, right)} == {0}, "tight axis must not move"
    assert {r.size() for r in (left, centre, right)} == {left.size()}, "size must not change"


def test_position_slides_a_tall_crop_vertically():
    top = crop_rect(1000, 4000, 2.0, position=0.0)
    bottom = crop_rect(1000, 4000, 2.0, position=1.0)

    assert (top.y(), bottom.y()) == (0, 3500)
    assert bottom.y() + bottom.height() == 4000
    assert (top.x(), bottom.x()) == (0, 0), "tight axis must not move"


def test_position_defaults_to_centred():
    assert crop_rect(4000, 1000, 2.0) == crop_rect(4000, 1000, 2.0, position=0.5)


def test_position_is_clamped():
    assert crop_rect(4000, 1000, 2.0, position=-5.0) == crop_rect(4000, 1000, 2.0, position=0.0)
    assert crop_rect(4000, 1000, 2.0, position=99.0) == crop_rect(4000, 1000, 2.0, position=1.0)


def test_position_cannot_push_the_crop_outside_the_image():
    for position in (0.0, 0.25, 0.5, 0.75, 1.0):
        rect = crop_rect(3000, 1000, SIXTEEN_NINE, position)
        assert rect.x() >= 0 and rect.y() >= 0
        assert rect.x() + rect.width() <= 3000
        assert rect.y() + rect.height() <= 1000


def test_crop_rejects_nonsense_dimensions():
    with pytest.raises(ValueError):
        crop_rect(0, 1080, SIXTEEN_NINE)
    with pytest.raises(ValueError):
        crop_rect(1920, 1080, 0)


def test_render_produces_exact_monitor_size(tmp_path: Path, make_image):
    source = make_image(tmp_path / "tall.png", 1000, 4000)
    rendered = render_wallpaper(source, 2560, 1440)
    assert (rendered.width(), rendered.height()) == (2560, 1440)


def test_render_upscales_small_images(tmp_path: Path, make_image):
    source = make_image(tmp_path / "small.png", 320, 180)
    rendered = render_wallpaper(source, 1920, 1080)
    assert (rendered.width(), rendered.height()) == (1920, 1080)


def test_render_honours_the_crop_position(tmp_path: Path, make_split_image):
    """A dragged crop must change the pixels that end up on the desktop."""
    source = make_split_image(tmp_path / "split.png", 400, 1200)

    top = render_wallpaper(source, 400, 200, position=0.0)
    bottom = render_wallpaper(source, 400, 200, position=1.0)

    assert top.pixelColor(200, 100).name() == "#ff0000", "top crop should be all red"
    assert bottom.pixelColor(200, 100).name() == "#0000ff", "bottom crop should be all blue"


def test_render_reports_unreadable_files(tmp_path: Path, qapp):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    with pytest.raises(WallpaperError):
        render_wallpaper(broken, 1920, 1080)
