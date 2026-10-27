"""Tests for dragging the crop region around the preview."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt

from wallpaper_manager.preview import PreviewWidget

SIXTEEN_NINE = 16 / 9


@pytest.fixture
def preview(qtbot):
    widget = PreviewWidget()
    qtbot.addWidget(widget)
    widget.resize(600, 400)
    widget.show()
    qtbot.waitExposed(widget)
    return widget


def drag(qtbot, widget, start: QPoint, end: QPoint) -> None:
    qtbot.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    qtbot.mouseMove(widget, pos=end)
    qtbot.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)


def test_starts_centred(preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)
    assert preview.position == 0.5


def test_tall_image_drags_vertically(preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)
    assert preview.drag_axis() == Qt.Orientation.Vertical


def test_wide_image_drags_horizontally(preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "wide.png", 4000, 400), SIXTEEN_NINE)
    assert preview.drag_axis() == Qt.Orientation.Horizontal


def test_exact_fit_has_nothing_to_drag(preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "exact.png", 1920, 1080), SIXTEEN_NINE)
    assert preview.drag_axis() is None


def test_crop_follows_the_cursor_upwards(qtbot, preview, tmp_path: Path, make_image):
    """The crop window tracks the mouse: drag up, it moves towards the top."""
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)

    drag(qtbot, preview, QPoint(300, 300), QPoint(300, 200))

    assert preview.position < 0.5


def test_crop_follows_the_cursor_downwards(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)

    drag(qtbot, preview, QPoint(300, 200), QPoint(300, 300))

    assert preview.position > 0.5


def test_position_never_leaves_the_image(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)

    drag(qtbot, preview, QPoint(300, 380), QPoint(300, -5000))
    assert preview.position == 0.0, "crop pinned to the top edge"

    drag(qtbot, preview, QPoint(300, 20), QPoint(300, 5000))
    assert preview.position == 1.0, "crop pinned to the bottom edge"


def test_drag_emits_position_changed(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)

    with qtbot.waitSignal(preview.position_changed, timeout=1000):
        drag(qtbot, preview, QPoint(300, 300), QPoint(300, 200))


def test_exact_fit_ignores_drags(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "exact.png", 1920, 1080), SIXTEEN_NINE)

    drag(qtbot, preview, QPoint(300, 300), QPoint(300, 100))

    assert preview.position == 0.5


def test_double_click_recentres(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)
    drag(qtbot, preview, QPoint(300, 300), QPoint(300, 200))
    assert preview.position != 0.5

    qtbot.mouseDClick(preview, Qt.MouseButton.LeftButton, pos=QPoint(300, 200))

    assert preview.position == 0.5


def test_selecting_a_new_image_resets_the_crop(qtbot, preview, tmp_path: Path, make_image):
    preview.set_image(make_image(tmp_path / "tall.png", 400, 2000), SIXTEEN_NINE)
    drag(qtbot, preview, QPoint(300, 300), QPoint(300, 200))
    assert preview.position != 0.5

    preview.set_image(make_image(tmp_path / "other.png", 400, 1600), SIXTEEN_NINE)

    assert preview.position == 0.5, "a new image should not inherit the previous drag"
