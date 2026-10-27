"""Application bootstrap: builds the QApplication and shows the main window."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from wallpaper_manager.main_window import MainWindow
from wallpaper_manager.resources import app_icon

APP_NAME = "Wallpaper Manager"
ORG_NAME = "WallpaperManager"

# CompanyName.ProductName.SubProduct.VersionInformation, per Microsoft's
# guidance for an AppUserModelID.
APP_USER_MODEL_ID = "WallpaperManager.WallpaperManager.App.1"


def _claim_windows_taskbar_identity() -> None:
    """Tell Windows this process is its own app, not the Python interpreter.

    Otherwise the taskbar groups the window under python.exe and shows the
    Python icon there instead of ours. Purely cosmetic, so failures are ignored.
    """
    if sys.platform != "win32":
        return

    import ctypes

    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (OSError, AttributeError):
        pass


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create (or reuse) the QApplication with app-wide identity set.

    Identity is set before any QSettings use so settings land in a stable
    location on every platform.
    """
    _claim_windows_taskbar_identity()
    app = QApplication.instance() or QApplication(argv if argv is not None else [])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    # Windows and menus pick this up for every window that does not set its own.
    app.setWindowIcon(app_icon())
    return app


def main(argv: list[str] | None = None) -> int:
    app = create_app(argv if argv is not None else sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
