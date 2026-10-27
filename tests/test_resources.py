from PySide6.QtCore import QSize

from wallpaper_manager.app import create_app
from wallpaper_manager.resources import ICON_FILE, app_icon


def test_icon_file_is_shipped():
    assert ICON_FILE.is_file()


def test_app_icon_renders_at_every_size(qapp):
    icon = app_icon()
    assert not icon.isNull(), "SVG icon did not load — is the Qt SVG plugin available?"

    # SVG has no native size, so QIcon must scale to whatever is requested;
    # a null pixmap here would mean the icon silently renders as nothing.
    for size in (16, 32, 64, 256):
        pixmap = icon.pixmap(QSize(size, size))
        assert not pixmap.isNull()
        assert pixmap.size() == QSize(size, size)


def test_create_app_sets_the_window_icon(qapp):
    app = create_app([])
    assert not app.windowIcon().isNull()
