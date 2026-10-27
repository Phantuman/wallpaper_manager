"""Folder scanning and aspect-ratio scoring."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImageReader

# Scores are rounded to this many decimals before ranking, so images that match
# the monitor equally well group together as genuine ties and are then ordered
# by pixel count. Without it, float noise (1920x1080 vs 5120x2880) would split
# ties that are identical for any practical purpose.
_TIE_PRECISION = 6


@lru_cache(maxsize=1)
def supported_extensions() -> frozenset[str]:
    """Extensions Qt can actually read, as lowercase ``.ext`` strings.

    Derived from the Qt build rather than hardcoded, so formats provided by
    optional image plugins (webp, avif, tiff) are picked up automatically.
    """
    return frozenset(
        f".{bytes(fmt).decode('ascii').lower()}" for fmt in QImageReader.supportedImageFormats()
    )


@dataclass(frozen=True, slots=True)
class ImageInfo:
    path: Path
    width: int
    height: int
    score: float

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def megapixels(self) -> float:
        return self.pixels / 1_000_000

    @property
    def rank_key(self) -> tuple[float, int]:
        """Sort key: closest aspect match first, then most megapixels."""
        return (round(self.score, _TIE_PRECISION), self.pixels)


def aspect_score(image_ratio: float, target_ratio: float) -> float:
    """How closely two aspect ratios match: 1.0 is identical, ~0 is wildly off.

    Symmetric, so an image that is too wide and one that is too tall by the
    same factor score equally.
    """
    if image_ratio <= 0 or target_ratio <= 0:
        return 0.0
    return min(image_ratio, target_ratio) / max(image_ratio, target_ratio)


def read_dimensions(path: Path) -> tuple[int, int] | None:
    """Read an image's pixel size from its header without decoding it."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # honour EXIF rotation, so portrait stays portrait
    size = reader.size()
    if not size.isValid() or size.width() <= 0 or size.height() <= 0:
        return None
    return size.width(), size.height()


def iter_image_files(folder: Path, recursive: bool = True):
    """Yield image files under *folder*, skipping unreadable directories."""
    extensions = supported_extensions()
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue  # permission denied, vanished mid-scan, etc.
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive:
                        stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if os.path.splitext(entry.name)[1].lower() in extensions:
                        yield Path(entry.path)
            except OSError:
                continue


class ScanWorker(QObject):
    """Scans a folder on a worker thread and emits the best-matching images."""

    progress = Signal(int, int)  # files examined, images accepted
    finished = Signal(list)  # list[ImageInfo], best match first
    failed = Signal(str)

    def __init__(
        self,
        folder: Path,
        target_ratio: float,
        min_width: int = 0,
        min_height: int = 0,
        recursive: bool = True,
    ) -> None:
        super().__init__()
        self._folder = folder
        self._target_ratio = target_ratio
        self._min_width = min_width
        self._min_height = min_height
        self._recursive = recursive
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            results: list[ImageInfo] = []
            examined = 0
            for path in iter_image_files(self._folder, self._recursive):
                if self._cancelled:
                    break
                examined += 1
                dimensions = read_dimensions(path)
                if dimensions is not None:
                    width, height = dimensions
                    if width >= self._min_width and height >= self._min_height:
                        results.append(
                            ImageInfo(
                                path=path,
                                width=width,
                                height=height,
                                score=aspect_score(width / height, self._target_ratio),
                            )
                        )
                if examined % 25 == 0:
                    self.progress.emit(examined, len(results))

            self.progress.emit(examined, len(results))
            results.sort(key=lambda info: info.rank_key, reverse=True)
            self.finished.emit(results)
        except Exception as exc:  # noqa: BLE001 - worker must never die silently
            self.failed.emit(str(exc))
