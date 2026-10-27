from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMainWindow

from wallpaper_manager.main_window import MainWindow, available_monitors
from wallpaper_manager.models import ResultsModel
from wallpaper_manager.scanning import ImageInfo


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
