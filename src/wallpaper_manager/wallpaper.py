"""Cropping images to a monitor's aspect ratio and applying them as wallpaper."""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PySide6.QtCore import QRect, QStandardPaths, Qt
from PySide6.QtGui import QImage, QImageReader

# SystemParametersInfoW constants (winuser.h)
_SPI_SETDESKWALLPAPER = 0x0014
_SPIF_UPDATEINIFILE = 0x01
_SPIF_SENDWININICHANGE = 0x02

_KEEP_GENERATED = 3


class WallpaperError(RuntimeError):
    """Raised when a wallpaper could not be generated or applied."""


CENTRED = 0.5


def crop_rect(width: int, height: int, target_ratio: float, position: float = CENTRED) -> QRect:
    """The largest rectangle inside *width* x *height* at *target_ratio*.

    Only one axis is ever free: the crop already spans the other one fully.
    *position* slides the rectangle along that free axis — 0.0 is flush against
    the left or top edge, 0.5 centred, 1.0 flush right or bottom. It is applied
    to both axes, which is harmless because the tight axis has no slack to move
    along. Values outside [0, 1] are clamped.
    """
    if width <= 0 or height <= 0 or target_ratio <= 0:
        raise ValueError("width, height and target_ratio must be positive")

    position = min(1.0, max(0.0, position))

    if width / height > target_ratio:
        # Image is wider than the target: keep full height, trim the sides.
        crop_width = min(width, max(1, round(height * target_ratio)))
        crop_height = height
    else:
        # Image is taller than the target: keep full width, trim top and bottom.
        crop_width = width
        crop_height = min(height, max(1, round(width / target_ratio)))

    return QRect(
        round((width - crop_width) * position),
        round((height - crop_height) * position),
        crop_width,
        crop_height,
    )


def render_wallpaper(
    source: Path, target_width: int, target_height: int, position: float = CENTRED
) -> QImage:
    """Crop *source* to the target aspect ratio and scale it to that size.

    *position* is where the crop sits along the free axis; see `crop_rect`.
    Images smaller than the target are still scaled up, so the result always
    matches the monitor exactly and Windows never has to rescale it.
    """
    reader = QImageReader(str(source))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise WallpaperError(f"Could not read image: {reader.errorString()}")

    rect = crop_rect(image.width(), image.height(), target_width / target_height, position)
    return image.copy(rect).scaled(
        target_width,
        target_height,
        Qt.AspectRatioMode.IgnoreAspectRatio,  # already cropped to the exact ratio
        Qt.TransformationMode.SmoothTransformation,
    )


def output_directory() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    directory = Path(base) / "generated"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _prune_old_wallpapers(directory: Path, keep: int = _KEEP_GENERATED) -> None:
    generated = sorted(directory.glob("wallpaper_*.png"), key=lambda p: p.name, reverse=True)
    for stale in generated[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass  # still in use by the shell; it will be cleaned up next time


def save_wallpaper(image: QImage) -> Path:
    """Write *image* to a fresh file and return its path.

    Each call uses a new filename: Windows caches the desktop background by
    path, so overwriting one file in place often leaves the old image showing.
    """
    directory = output_directory()
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}_{time.time_ns() % 1000:03d}"
    destination = directory / f"wallpaper_{stamp}.png"
    if not image.save(str(destination), "PNG"):
        raise WallpaperError(f"Could not write wallpaper to {destination}")
    _prune_old_wallpapers(directory)
    return destination


def _apply_windows(path: Path) -> None:
    import ctypes
    import winreg

    # "Fill" (10), untiled. The image is already cropped to the exact monitor
    # ratio, so Fill is a no-op on the primary monitor and sensibly fills any
    # secondary monitor with a different shape.
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "10")
        winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SystemParametersInfoW.restype = ctypes.c_bool
    ok = user32.SystemParametersInfoW(
        _SPI_SETDESKWALLPAPER,
        0,
        str(path),
        _SPIF_UPDATEINIFILE | _SPIF_SENDWININICHANGE,
    )
    if not ok:
        raise WallpaperError(f"Windows rejected the wallpaper (error {ctypes.get_last_error()})")


def set_wallpaper(
    source: Path, target_width: int, target_height: int, position: float = CENTRED
) -> Path:
    """Crop *source* to the monitor's shape and make it the desktop wallpaper.

    Returns the path of the generated image that was applied.
    """
    if sys.platform != "win32":
        raise WallpaperError(f"Setting the wallpaper is not supported on {sys.platform} yet.")

    generated = save_wallpaper(render_wallpaper(source, target_width, target_height, position))
    _apply_windows(generated)
    return generated
