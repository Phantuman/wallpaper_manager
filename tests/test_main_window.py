from pathlib import Path

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMainWindow

from wallpaper_manager.main_window import MainWindow, MonitorInfo, available_monitors
from wallpaper_manager.models import ResultsModel
from wallpaper_manager.scanning import ImageInfo, aspect_score


def test_window_opens(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert isinstance(window, QMainWindow)
    assert window.windowTitle() == "Wallpaper Manager"


def test_menus_present(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    titles = [action.text() for action in window.menuBar().actions()]
    assert titles == ["&File", "&Help"]


def test_monitors_are_reported_in_positive_pixels(qapp):
    monitors = available_monitors()
    assert monitors, "at least one screen should be detected"
    for monitor in monitors:
        assert monitor.width > 0 and monitor.height > 0
        assert monitor.ratio > 0


def test_apply_disabled_until_a_row_is_selected(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    assert not window._apply_button.isEnabled()
    assert not window._open_source_button.isEnabled()


def test_selecting_a_row_enables_apply_and_previews_it(qtbot, image_folder: Path):
    window = MainWindow()
    qtbot.addWidget(window)

    window._model.set_results(
        [ImageInfo(path=image_folder / "wide_16x9.png", width=1920, height=1080, score=1.0)]
    )
    window._table.selectRow(0)

    assert window._apply_button.isEnabled()
    assert window._open_source_button.isEnabled()
    assert "wide_16x9.png" in window._preview_label.full_text


def test_open_source_folder_opens_selected_images_parent(qtbot, image_folder: Path, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    path = image_folder / "nested" / "small_16x9.png"
    window._model.set_results([ImageInfo(path=path, width=640, height=360, score=1.0)])
    window._table.selectRow(0)
    opened_urls: list[QUrl] = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: not opened_urls.append(url))

    window._open_source_button.click()

    assert opened_urls == [QUrl.fromLocalFile(str(path.parent))]


def test_selecting_a_row_shows_its_full_path_in_the_status_bar(qtbot, image_folder: Path):
    window = MainWindow()
    qtbot.addWidget(window)

    path = image_folder / "nested" / "small_16x9.png"
    window._model.set_results([ImageInfo(path=path, width=640, height=360, score=1.0)])
    window._table.selectRow(0)

    assert window.statusBar().currentMessage() == str(path)


def test_clearing_the_selection_clears_the_status_bar(qtbot, image_folder: Path):
    window = MainWindow()
    qtbot.addWidget(window)

    window._model.set_results(
        [ImageInfo(path=image_folder / "wide_16x9.png", width=1920, height=1080, score=1.0)]
    )
    window._table.selectRow(0)
    window._table.clearSelection()

    assert window.statusBar().currentMessage() == ""


def test_model_formats_columns(qtbot, image_folder: Path):
    model = ResultsModel()
    model.set_results(
        [ImageInfo(path=image_folder / "wide_16x9.png", width=1920, height=1080, score=0.9876)]
    )

    def text(column: int) -> str:
        return model.data(model.index(0, column))

    assert text(ResultsModel.COLUMN_MATCH) == "98.8%"
    assert text(ResultsModel.COLUMN_FILE) == "wide_16x9.png"
    assert text(ResultsModel.COLUMN_RESOLUTION) == "1920 x 1080"
    assert text(ResultsModel.COLUMN_RATIO) == "1.778"
    assert text(ResultsModel.COLUMN_MEGAPIXELS) == "2.1"


@pytest.mark.parametrize("control", ["monitor", "phone", "width", "height"])
def test_target_change_reranks_without_scanning(qtbot, image_folder, monkeypatch, control):
    monkeypatch.setattr(
        "wallpaper_manager.main_window.available_monitors",
        lambda: [MonitorInfo("Wide", 1920, 1080), MonitorInfo("Portrait", 1080, 1920)],
    )
    window = MainWindow()
    qtbot.addWidget(window)
    if control in ("width", "height"):
        window._target_combo.setCurrentIndex(2)
        window._custom_width.setValue(1920)
        window._custom_height.setValue(1080)
    results = [
        ImageInfo(image_folder / "wide_16x9.png", 1920, 1080, 1.0),
        ImageInfo(image_folder / "portrait.png", 1080, 1920, 0.3),
        ImageInfo(image_folder / "square.png", 1000, 1000, 0.5),
    ]
    window._on_scan_finished(results)
    window._table.selectRow(2)  # Keep the same image selected as its row moves.
    selected = window._selected_info()
    assert selected is not None
    selected_path = selected.path

    def unexpected_scan():
        pytest.fail("Changing the target must not rescan")

    monkeypatch.setattr(window, "_start_scan", unexpected_scan)
    if control == "monitor":
        window._monitor_combo.setCurrentIndex(1)
    elif control == "phone":
        window._target_combo.setCurrentIndex(1)
        window._phone_combo.setCurrentIndex(10)
    elif control == "width":
        window._custom_width.setValue(608)
    else:
        window._custom_height.setValue(3400)

    first = window._model.info_at(0)
    assert first is not None
    assert first.path.name == "portrait.png"
    for row in range(window._model.rowCount()):
        info = window._model.info_at(row)
        assert info is not None
        assert info.score == aspect_score(info.aspect_ratio, window._current_target().ratio)
    selected = window._selected_info()
    assert selected is not None
    assert selected.path == selected_path
    assert window.statusBar().currentMessage() == str(selected_path)


def test_target_size_filter_reuses_all_scanned_images(qtbot, image_folder, monkeypatch):
    window = MainWindow()
    qtbot.addWidget(window)
    window._target_combo.setCurrentIndex(2)
    window._custom_width.setValue(1920)
    window._custom_height.setValue(1080)
    window._min_size_check.setChecked(True)
    window._folder = image_folder
    window._start_scan()
    qtbot.waitUntil(lambda: not window._is_scanning(), timeout=10000)
    assert window._model.rowCount() == 2

    def unexpected_scan():
        pytest.fail("Filtering cached images must not rescan")

    monkeypatch.setattr(window, "_start_scan", unexpected_scan)
    window._custom_width.setValue(8192)
    window._custom_height.setValue(8192)
    assert window._model.rowCount() == 0
    assert window._selected_info() is None
    assert not window._apply_button.isEnabled()
    assert window._preview_label.full_text == ""

    window._custom_width.setValue(640)
    window._custom_height.setValue(360)
    assert window._model.rowCount() == 5
    assert window._selected_info() is not None
    assert window._count_label.text() == "5 images, best match first"
    window._custom_width.setValue(1920)
    window._custom_height.setValue(1080)
    assert window._model.rowCount() == 2
    window._min_size_check.setChecked(False)
    assert window._model.rowCount() == 5
