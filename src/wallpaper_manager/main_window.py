"""The application's main window."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QItemSelection, QSettings, Qt, QThread, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QGuiApplication,
    QImageWriter,
    QKeySequence,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from wallpaper_manager.models import ResultsModel
from wallpaper_manager.preview import PreviewWidget
from wallpaper_manager.scanning import ImageInfo, ScanWorker, aspect_score
from wallpaper_manager.wallpaper import WallpaperError, render_wallpaper, set_wallpaper


class ElidedLabel(QLabel):
    """A label that shrinks long paths from the left instead of stretching."""

    def __init__(
        self,
        text: str = "",
        mode: Qt.TextElideMode = Qt.TextElideMode.ElideLeft,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._mode = mode
        self._full_text = ""
        self.setText(text)

    @property
    def full_text(self) -> str:
        """The unabbreviated text, regardless of how narrow the label is."""
        return self._full_text

    def setText(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._update_elided()

    def _update_elided(self) -> None:
        elided = self.fontMetrics().elidedText(
            self._full_text, self._mode, max(0, self.width() - 4)
        )
        super().setText(elided)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_elided()


@dataclass(frozen=True, slots=True)
class MonitorInfo:
    name: str
    width: int
    height: int

    @property
    def ratio(self) -> float:
        return self.width / self.height

    @property
    def label(self) -> str:
        return f"{self.name} — {self.width} x {self.height} ({self.ratio:.2f}:1)"


# Portrait display sizes from Apple, Samsung and Google technical specifications.
PHONE_PRESETS = (
    MonitorInfo("iPhone 17", 1206, 2622),
    MonitorInfo("iPhone 16", 1179, 2556),
    MonitorInfo("iPhone 16 Plus", 1290, 2796),
    MonitorInfo("iPhone 16 Pro", 1206, 2622),
    MonitorInfo("iPhone 16 Pro Max", 1320, 2868),
    MonitorInfo("iPhone 15", 1179, 2556),
    MonitorInfo("iPhone 14", 1170, 2532),
    MonitorInfo("Samsung Galaxy S25", 1080, 2340),
    MonitorInfo("Samsung Galaxy S25+ / S25 Ultra", 1440, 3120),
    MonitorInfo("Samsung Galaxy A55", 1080, 2340),
    MonitorInfo("Google Pixel 9", 1080, 2424),
    MonitorInfo("Google Pixel 9 Pro / Pixel 10 Pro", 1280, 2856),
)


def available_monitors() -> list[MonitorInfo]:
    """Every connected screen, in real (physical) pixels.

    Qt reports geometry in logical pixels, so a 3840x2160 monitor at 150%
    scaling would otherwise be read as 2560x1440. The aspect ratio is the same
    either way, but the wallpaper must be rendered at the physical size.
    """
    monitors: list[MonitorInfo] = []
    primary = QGuiApplication.primaryScreen()
    for screen in QGuiApplication.screens():
        geometry = screen.geometry()
        ratio = screen.devicePixelRatio()
        name = screen.name() or "Display"
        if screen is primary:
            name = f"{name} (primary)"
        monitors.append(
            MonitorInfo(
                name=name,
                width=max(1, round(geometry.width() * ratio)),
                height=max(1, round(geometry.height() * ratio)),
            )
        )
    return monitors


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wallpaper Manager")
        self.resize(1200, 760)

        self._folder: Path | None = None
        self._monitors = available_monitors()
        self._thread: QThread | None = None
        self._worker: ScanWorker | None = None
        self._scan_results: list[ImageInfo] = []

        self._model = ResultsModel(self)

        self._build_menus()
        self.setCentralWidget(self._build_central_widget())
        self._build_status_bar()

        self._restore_settings()
        self._update_actions()

    # ------------------------------------------------------------------ setup

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")

        self._open_action = QAction("&Choose Folder…", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._choose_folder)
        file_menu.addAction(self._open_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_central_widget(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addLayout(self._build_controls())
        layout.addLayout(self._build_target_controls())
        layout.addWidget(self._build_splitter(), 1)
        layout.addLayout(self._build_apply_row())
        return container

    def _build_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()

        choose_button = QPushButton("Choose Folder…")
        choose_button.clicked.connect(self._choose_folder)
        row.addWidget(choose_button)

        self._folder_label = ElidedLabel("No folder selected")
        row.addWidget(self._folder_label, 1)

        self._recursive_check = QCheckBox("Subfolders")
        self._recursive_check.setChecked(True)
        self._recursive_check.setToolTip("Scan subfolders as well")
        row.addWidget(self._recursive_check)

        self._min_size_check = QCheckBox("Only ≥ target size")
        self._min_size_check.setToolTip(
            "Skip images smaller than the selected resolution, which would have to be upscaled"
        )
        self._min_size_check.toggled.connect(self._refresh_results)
        row.addWidget(self._min_size_check)

        self._scan_button = QPushButton("Scan")
        self._scan_button.clicked.connect(self._toggle_scan)
        row.addWidget(self._scan_button)

        return row

    def _build_target_controls(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Wallpaper for:"))
        self._target_combo = QComboBox()
        self._target_combo.addItems(["Monitor", "Phone", "Custom resolution"])
        row.addWidget(self._target_combo)

        self._monitor_combo = QComboBox()
        for monitor in self._monitors:
            self._monitor_combo.addItem(monitor.label)
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        row.addWidget(self._monitor_combo)

        self._phone_combo = QComboBox()
        for phone in PHONE_PRESETS:
            self._phone_combo.addItem(phone.label)
        self._phone_combo.hide()
        row.addWidget(self._phone_combo)

        self._custom_controls = QWidget()
        custom_row = QHBoxLayout(self._custom_controls)
        custom_row.setContentsMargins(0, 0, 0, 0)
        self._custom_width = QSpinBox()
        self._custom_height = QSpinBox()
        for spin, label, value in (
            (self._custom_width, "Width", 1080),
            (self._custom_height, "Height", 1920),
        ):
            spin.setRange(1, 8192)
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            spin.setSuffix(" px")
            spin.setAccessibleName(label)
            spin.setToolTip(f"{label} in pixels (1–8192)")
            custom_row.addWidget(QLabel(f"{label}:"))
            custom_row.addWidget(spin)
            spin.valueChanged.connect(self._on_monitor_changed)
        self._custom_controls.hide()
        row.addWidget(self._custom_controls)
        row.addStretch(1)
        self._target_combo.currentIndexChanged.connect(self._on_monitor_changed)
        self._phone_combo.currentIndexChanged.connect(self._on_monitor_changed)

        return row

    def _build_splitter(self) -> QSplitter:
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)  # already ranked by match quality
        self._table.doubleClicked.connect(lambda _index: self._apply_wallpaper())
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(ResultsModel.COLUMN_FILE, QHeaderView.ResizeMode.Stretch)
        for column in (
            ResultsModel.COLUMN_MATCH,
            ResultsModel.COLUMN_RESOLUTION,
            ResultsModel.COLUMN_RATIO,
            ResultsModel.COLUMN_MEGAPIXELS,
        ):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)

        self._preview = PreviewWidget()
        self._preview.set_target_ratio(self._current_target().ratio)
        self._preview.position_changed.connect(self._on_crop_moved)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._table)
        splitter.addWidget(self._preview)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 5)
        self._splitter = splitter
        return splitter

    def _build_apply_row(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._preview_label = ElidedLabel("", Qt.TextElideMode.ElideRight)
        row.addWidget(self._preview_label, 1)

        self._open_source_button = QPushButton("Open Source Folder")
        self._open_source_button.setToolTip("Open the folder containing the selected image")
        self._open_source_button.clicked.connect(self._open_source_folder)
        row.addWidget(self._open_source_button)

        self._save_button = QPushButton("Save Wallpaper…")
        self._save_button.clicked.connect(self._save_wallpaper)
        row.addWidget(self._save_button)

        self._apply_button = QPushButton("Set as Wallpaper (cropped)")
        self._apply_button.setDefault(True)
        self._apply_button.clicked.connect(self._apply_wallpaper)
        row.addWidget(self._apply_button)

        return row

    def _build_status_bar(self) -> None:
        # The message area is reserved for the selected image's full path, so
        # the result count lives in a permanent widget that it cannot overwrite.
        self._count_label = QLabel("")
        self.statusBar().addPermanentWidget(self._count_label)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # indeterminate; total file count is unknown
        self._progress.setMaximumWidth(180)
        self._progress.hide()
        self.statusBar().addPermanentWidget(self._progress)

        self.statusBar().showMessage("Choose a folder to scan")

    # ----------------------------------------------------------------- helpers

    def _current_monitor(self) -> MonitorInfo:
        index = self._monitor_combo.currentIndex() if hasattr(self, "_monitor_combo") else 0
        if 0 <= index < len(self._monitors):
            return self._monitors[index]
        return MonitorInfo("Display", 1920, 1080)

    def _selected_info(self) -> ImageInfo | None:
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return None
        return self._model.info_at(indexes[0].row())

    def _current_target(self) -> MonitorInfo:
        mode = self._target_combo.currentIndex()
        if mode == 1:
            return PHONE_PRESETS[self._phone_combo.currentIndex()]
        if mode == 2:
            return MonitorInfo("Custom", self._custom_width.value(), self._custom_height.value())
        return self._current_monitor()

    def _is_scanning(self) -> bool:
        return self._thread is not None

    def _update_actions(self) -> None:
        scanning = self._is_scanning()
        self._scan_button.setText("Cancel" if scanning else "Scan")
        self._scan_button.setEnabled(self._folder is not None)
        has_selection = self._selected_info() is not None
        self._open_source_button.setEnabled(has_selection)
        self._apply_button.setEnabled(has_selection and not scanning)
        self._save_button.setEnabled(has_selection and not scanning)
        self._apply_button.setText(
            "Set as Wallpaper (cropped)"
            if self._target_combo.currentIndex() == 0
            else "Copy to Clipboard (cropped)"
        )
        for control in (
            self._target_combo,
            self._monitor_combo,
            self._phone_combo,
            self._custom_controls,
        ):
            control.setEnabled(not scanning)
        self._open_action.setEnabled(not scanning)

    # ------------------------------------------------------------------ slots

    def _choose_folder(self) -> None:
        start = str(self._folder) if self._folder else ""
        chosen = QFileDialog.getExistingDirectory(self, "Choose image folder", start)
        if not chosen:
            return
        self._folder = Path(chosen)
        self._folder_label.setText(str(self._folder))
        self._update_actions()
        self._start_scan()

    def _on_monitor_changed(self) -> None:
        mode = self._target_combo.currentIndex()
        self._monitor_combo.setVisible(mode == 0)
        self._phone_combo.setVisible(mode == 1)
        self._custom_controls.setVisible(mode == 2)
        monitor = self._current_target()
        self._preview.set_target_ratio(monitor.ratio)
        self._refresh_results()
        self._update_preview_caption()
        self._update_actions()

    def _refresh_results(self) -> None:
        """Rank and filter cached image dimensions for the current target."""
        selected = self._selected_info()
        target = self._current_target()
        results = [
            replace(info, score=aspect_score(info.aspect_ratio, target.ratio))
            for info in self._scan_results
            if not self._min_size_check.isChecked()
            or (info.width >= target.width and info.height >= target.height)
        ]
        results.sort(key=lambda info: info.rank_key, reverse=True)
        self._model.set_results(results)
        if results:
            plural = "" if len(results) == 1 else "s"
            self._count_label.setText(f"{len(results)} image{plural}, best match first")
            row = next(
                (i for i, info in enumerate(results) if selected and info.path == selected.path),
                0,
            )
            self._table.selectRow(row)
        else:
            self._count_label.setText("")
            self._on_selection_changed(QItemSelection(), QItemSelection())
            if self._scan_results:
                self.statusBar().showMessage("No images match the target size")

    def _on_selection_changed(self, _selected: QItemSelection, _deselected: QItemSelection) -> None:
        info = self._selected_info()
        if info is None:
            self._preview.clear()
            self.statusBar().clearMessage()
        else:
            self._preview.set_image(info.path, self._current_target().ratio)
            self.statusBar().showMessage(str(info.path))
        self._update_preview_caption()
        self._update_actions()

    def _on_crop_moved(self, _position: float) -> None:
        self._update_preview_caption()

    def _update_preview_caption(self) -> None:
        info = self._selected_info()
        if info is None:
            self._preview_label.setText("")
            return

        monitor = self._current_target()
        text = (
            f"{info.path.name} — {info.width} x {info.height}, "
            f"{aspect_score(info.aspect_ratio, monitor.ratio) * 100:.1f}% match. "
            f"Highlighted area will be cropped to {monitor.width} x {monitor.height}."
        )

        axis = self._preview.drag_axis()
        if axis is not None:
            direction = "left/right" if axis == Qt.Orientation.Horizontal else "up/down"
            text += f" Drag {direction} to reposition, double-click to re-centre."
        self._preview_label.setText(text)

    def _toggle_scan(self) -> None:
        if self._is_scanning():
            self._cancel_scan()
        else:
            self._start_scan()

    # ------------------------------------------------------------------ scanning

    def _start_scan(self) -> None:
        if self._folder is None or self._is_scanning():
            return

        monitor = self._current_target()
        self._scan_results = []
        self._model.set_results([])
        self._preview.clear()
        self._preview_label.setText("")
        self._count_label.setText("")

        self._thread = QThread(self)
        self._worker = ScanWorker(
            folder=self._folder,
            target_ratio=monitor.ratio,
            recursive=self._recursive_check.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_scan_progress)
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.failed.connect(self._on_scan_failed)

        self._progress.show()
        self.statusBar().showMessage("Scanning…")
        self._update_actions()
        self._thread.start()

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.statusBar().showMessage("Cancelling…")

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
        if self._worker is not None:
            self._worker.deleteLater()
        self._thread = None
        self._worker = None
        self._progress.hide()
        self._update_actions()

    def _on_scan_progress(self, examined: int, matched: int) -> None:
        self.statusBar().showMessage(f"Scanning… {examined} files examined, {matched} images found")

    def _on_scan_finished(self, results: list[ImageInfo]) -> None:
        self._teardown_thread()
        self._scan_results = results
        self._refresh_results()
        if self._model.rowCount():
            self._table.setFocus()
        elif not results:
            self.statusBar().showMessage("No images found in that folder")

    def _on_scan_failed(self, message: str) -> None:
        self._teardown_thread()
        self.statusBar().showMessage("Scan failed")
        QMessageBox.critical(self, "Scan failed", message)

    # ------------------------------------------------------------------ apply

    def _open_source_folder(self) -> None:
        info = self._selected_info()
        if info is None:
            return

        folder_url = QUrl.fromLocalFile(str(info.path.parent))
        if not QDesktopServices.openUrl(folder_url):
            QMessageBox.warning(
                self,
                "Could not open source folder",
                f"The folder could not be opened:\n{info.path.parent}",
            )

    def _apply_wallpaper(self) -> None:
        info = self._selected_info()
        if info is None or self._is_scanning():
            return

        monitor = self._current_target()
        copying = self._target_combo.currentIndex() != 0
        action = "copy wallpaper" if copying else "set wallpaper"
        self._apply_button.setEnabled(False)
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if copying:
                image = render_wallpaper(
                    info.path, monitor.width, monitor.height, self._preview.position
                )
                QGuiApplication.clipboard().setImage(image)
            else:
                set_wallpaper(info.path, monitor.width, monitor.height, self._preview.position)
        except (WallpaperError, OSError) as exc:
            QMessageBox.critical(self, f"Could not {action}", str(exc))
            self.statusBar().showMessage(f"Could not {action}")
        else:
            message = (
                f"Copied {monitor.width} x {monitor.height} wallpaper to clipboard"
                if copying
                else f"Wallpaper set from {info.path.name}"
            )
            self.statusBar().showMessage(message)
        finally:
            QGuiApplication.restoreOverrideCursor()
            self._update_actions()

    def _save_wallpaper(self) -> None:
        info = self._selected_info()
        if info is None or self._is_scanning():
            return
        target = self._current_target()
        filename = f"{info.path.stem}_{target.width}x{target.height}.png"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save wallpaper", str(info.path.parent / filename), "PNG image (*.png)"
        )
        if not chosen:
            return
        destination = Path(chosen)
        if not destination.suffix:
            destination = destination.with_suffix(".png")
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            image = render_wallpaper(info.path, target.width, target.height, self._preview.position)
            writer = QImageWriter(str(destination), QByteArray(b"png"))
            if not writer.write(image):
                raise WallpaperError(
                    f"Could not write wallpaper to {destination}: {writer.errorString()}"
                )
        except (WallpaperError, OSError) as exc:
            QMessageBox.critical(self, "Could not save wallpaper", str(exc))
            self.statusBar().showMessage("Could not save wallpaper")
        else:
            self.statusBar().showMessage(f"Wallpaper saved to {destination}")
        finally:
            QGuiApplication.restoreOverrideCursor()

    # --------------------------------------------------------------- lifecycle

    def _show_about(self) -> None:
        from wallpaper_manager import __version__

        monitor = self._current_target()
        QMessageBox.about(
            self,
            "About Wallpaper Manager",
            f"Wallpaper Manager {__version__}\n\n"
            f"Ranks images by how closely they match your target's shape.\n"
            f"Current target: {monitor.width} x {monitor.height}.",
        )

    def _restore_settings(self) -> None:
        settings = QSettings()

        geometry = settings.value("window/geometry")
        if isinstance(geometry, QByteArray) and not geometry.isEmpty():
            self.restoreGeometry(geometry)

        splitter_state = settings.value("window/splitter")
        if isinstance(splitter_state, QByteArray) and not splitter_state.isEmpty():
            self._splitter.restoreState(splitter_state)

        last_folder = settings.value("scan/folder")
        if isinstance(last_folder, str) and Path(last_folder).is_dir():
            self._folder = Path(last_folder)
            self._folder_label.setText(last_folder)
            self.statusBar().showMessage(f"Press Scan to search {last_folder}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._cancel_scan()
        self._teardown_thread()

        settings = QSettings()
        settings.setValue("window/geometry", self.saveGeometry())
        settings.setValue("window/splitter", self._splitter.saveState())
        if self._folder is not None:
            settings.setValue("scan/folder", str(self._folder))

        super().closeEvent(event)
