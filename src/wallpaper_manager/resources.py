"""Assets shipped with the package, and how to load them as Qt objects."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

RESOURCES_DIR = Path(__file__).parent / "resources"
ICON_FILE = RESOURCES_DIR / "icon.svg"


def app_icon() -> QIcon:
    """The application icon, rendered from SVG at whatever size Qt asks for.

    Call this only once a `QGuiApplication` exists: Qt loads its SVG image
    plugin through the application instance, and without it the returned icon
    is silently null.
    """
    return QIcon(str(ICON_FILE))
