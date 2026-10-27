"""Preview pane showing an image with the region that would be cropped away."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QImageReader,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from wallpaper_manager.wallpaper import CENTRED, crop_rect

# Images are downscaled to this bound on load: the preview never needs more,
# and it keeps 50-megapixel files from stalling the UI thread.
_MAX_PREVIEW_EDGE = 1600

# Below this, an image is treated as an exact ratio match with nothing to drag.
_RATIO_EPSILON = 1e-9


class PreviewWidget(QWidget):
    """Draws the selected image, dimming everything outside the crop region.

    The crop can be dragged along whichever axis has slack; `position_changed`
    reports the new offset as a fraction between 0.0 and 1.0.
    """

    position_changed = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)  # so the cursor can hint at draggability
        self._pixmap: QPixmap | None = None
        self._source_size = QSize()
        self._target_ratio = 16 / 9
        self._position = CENTRED
        self._drag_origin: QPointF | None = None
        self._drag_start_position = CENTRED
        self._placeholder = "Select an image to preview"

    # ------------------------------------------------------------------ state

    @property
    def position(self) -> float:
        """Where the crop sits along its free axis: 0.0 to 1.0, 0.5 centred."""
        return self._position

    def clear(self, message: str = "Select an image to preview") -> None:
        self._pixmap = None
        self._drag_origin = None
        self._placeholder = message
        self._set_position(CENTRED)
        self.unsetCursor()
        self.update()

    def set_target_ratio(self, ratio: float) -> None:
        self._target_ratio = ratio
        self.update()

    def set_image(self, path: Path, target_ratio: float) -> None:
        self._target_ratio = target_ratio
        self._drag_origin = None

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if not size.isValid():
            self.clear(f"Could not read {path.name}")
            return

        self._source_size = size
        scaled = size.scaled(
            _MAX_PREVIEW_EDGE, _MAX_PREVIEW_EDGE, Qt.AspectRatioMode.KeepAspectRatio
        )
        if scaled.width() < size.width():
            reader.setScaledSize(scaled)

        image = reader.read()
        if image.isNull():
            self.clear(f"Could not read {path.name}")
            return

        self._pixmap = QPixmap.fromImage(image)
        # A new image starts centred rather than inheriting the last drag.
        self._set_position(CENTRED)
        self.update()

    def _set_position(self, position: float) -> None:
        position = min(1.0, max(0.0, position))
        if position != self._position:
            self._position = position
            self.position_changed.emit(position)

    # -------------------------------------------------------------- geometry

    def _drawn_rect(self) -> QRect:
        """Where the pixmap lands inside this widget, preserving its ratio."""
        assert self._pixmap is not None
        scaled = self._pixmap.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRect(
            (self.width() - scaled.width()) // 2,
            (self.height() - scaled.height()) // 2,
            scaled.width(),
            scaled.height(),
        )

    def _source_crop(self) -> QRect:
        return crop_rect(
            self._source_size.width(),
            self._source_size.height(),
            self._target_ratio,
            self._position,
        )

    def _crop_on_screen(self, drawn: QRect) -> QRect:
        """Map the crop rectangle from source pixels onto the drawn image."""
        crop = self._source_crop()
        scale_x = drawn.width() / self._source_size.width()
        scale_y = drawn.height() / self._source_size.height()
        return QRect(
            drawn.x() + round(crop.x() * scale_x),
            drawn.y() + round(crop.y() * scale_y),
            round(crop.width() * scale_x),
            round(crop.height() * scale_y),
        )

    def drag_axis(self) -> Qt.Orientation | None:
        """The axis the crop can slide along, or None if the fit is exact."""
        if self._pixmap is None or not self._source_size.isValid():
            return None
        ratio = self._source_size.width() / self._source_size.height()
        if abs(ratio - self._target_ratio) < _RATIO_EPSILON:
            return None
        return Qt.Orientation.Horizontal if ratio > self._target_ratio else Qt.Orientation.Vertical

    def _slack(self) -> tuple[Qt.Orientation, float] | None:
        """The free axis and how many widget pixels the crop can travel."""
        axis = self.drag_axis()
        if axis is None:
            return None
        drawn = self._drawn_rect()
        crop = self._crop_on_screen(drawn)
        travel = (
            drawn.width() - crop.width()
            if axis == Qt.Orientation.Horizontal
            else drawn.height() - crop.height()
        )
        if travel <= 0:
            return None  # rounding collapsed the slack at this preview size
        return axis, float(travel)

    # ----------------------------------------------------------------- mouse

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._slack() is not None:
            self._drag_origin = event.position()
            self._drag_start_position = self._position
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        slack = self._slack()

        if self._drag_origin is None:
            # Not dragging: hint that the crop can be moved.
            if slack is None:
                self.unsetCursor()
            else:
                self.setCursor(
                    Qt.CursorShape.SizeHorCursor
                    if slack[0] == Qt.Orientation.Horizontal
                    else Qt.CursorShape.SizeVerCursor
                )
            super().mouseMoveEvent(event)
            return

        if slack is None:
            return

        axis, travel = slack
        delta = event.position() - self._drag_origin
        moved = delta.x() if axis == Qt.Orientation.Horizontal else delta.y()
        self._set_position(self._drag_start_position + moved / travel)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Double-click re-centres the crop."""
        if event.button() == Qt.MouseButton.LeftButton and self._pixmap is not None:
            self._set_position(CENTRED)
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ----------------------------------------------------------------- paint

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().base())

        if self._pixmap is None:
            painter.setPen(self.palette().color(self.foregroundRole()))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._placeholder)
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        drawn = self._drawn_rect()
        painter.drawPixmap(drawn, self._pixmap)

        crop = self._crop_on_screen(drawn)
        shade = QColor(0, 0, 0, 140)
        for region in (
            QRect(drawn.x(), drawn.y(), drawn.width(), crop.y() - drawn.y()),
            QRect(drawn.x(), crop.bottom() + 1, drawn.width(), drawn.bottom() - crop.bottom()),
            QRect(drawn.x(), crop.y(), crop.x() - drawn.x(), crop.height()),
            QRect(crop.right() + 1, crop.y(), drawn.right() - crop.right(), crop.height()),
        ):
            if region.isValid():
                painter.fillRect(region, shade)

        painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.drawRect(crop.adjusted(0, 0, -1, -1))
