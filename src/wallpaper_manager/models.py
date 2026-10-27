"""Table model backing the results list."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt

from wallpaper_manager.scanning import ImageInfo

_HEADERS = ("Match", "File", "Resolution", "Ratio", "MP")

# Qt's signature defaults these to an invalid index meaning "the root".
_ROOT = QModelIndex()


class ResultsModel(QAbstractTableModel):
    COLUMN_MATCH = 0
    COLUMN_FILE = 1
    COLUMN_RESOLUTION = 2
    COLUMN_RATIO = 3
    COLUMN_MEGAPIXELS = 4

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[ImageInfo] = []

    def set_results(self, results: list[ImageInfo]) -> None:
        self.beginResetModel()
        self._rows = results
        self.endResetModel()

    def info_at(self, row: int) -> ImageInfo | None:
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def rowCount(self, parent: QModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return _HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        info = self._rows[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == self.COLUMN_MATCH:
                return f"{info.score * 100:.1f}%"
            if column == self.COLUMN_FILE:
                return info.path.name
            if column == self.COLUMN_RESOLUTION:
                return f"{info.width} x {info.height}"
            if column == self.COLUMN_RATIO:
                return f"{info.aspect_ratio:.3f}"
            if column == self.COLUMN_MEGAPIXELS:
                return f"{info.megapixels:.1f}"

        if role == Qt.ItemDataRole.ToolTipRole:
            return str(info.path)

        if role == Qt.ItemDataRole.TextAlignmentRole and column != self.COLUMN_FILE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None
