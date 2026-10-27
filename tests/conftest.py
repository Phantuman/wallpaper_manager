from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage


def write_image(path: Path, width: int, height: int) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("steelblue"))
    assert image.save(str(path)), f"could not write {path}"
    return path


def write_split_image(path: Path, width: int, height: int) -> Path:
    """An image whose top half is red and bottom half is blue.

    Lets a test tell *which part* of an image a crop actually kept.
    """
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("red"))
    for y in range(height // 2, height):
        for x in range(width):
            image.setPixelColor(x, y, QColor("blue"))
    assert image.save(str(path)), f"could not write {path}"
    return path


@pytest.fixture
def make_image(qapp):
    """Write a solid-colour image of a given size and return its path."""
    return write_image


@pytest.fixture
def make_split_image(qapp):
    """Write a red-over-blue image, for checking which region a crop kept."""
    return write_split_image


@pytest.fixture
def image_folder(tmp_path: Path, qapp) -> Path:
    """A folder of images with a spread of aspect ratios, plus some noise."""
    folder = tmp_path / "images"
    (folder / "nested").mkdir(parents=True)

    write_image(folder / "wide_16x9.png", 1920, 1080)
    write_image(folder / "ultrawide_21x9.png", 3440, 1440)
    write_image(folder / "square.png", 1000, 1000)
    write_image(folder / "portrait.png", 1080, 1920)
    write_image(folder / "nested" / "small_16x9.png", 640, 360)

    (folder / "notes.txt").write_text("not an image")
    (folder / "broken.png").write_bytes(b"this is not a png")

    return folder
