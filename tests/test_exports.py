import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtWidgets import QFileDialog, QMessageBox

from wallpaper_manager.main_window import PHONE_PRESETS, MainWindow, MonitorInfo
from wallpaper_manager.scanning import ImageInfo
from wallpaper_manager.wallpaper import WallpaperError


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(
        "wallpaper_manager.main_window.available_monitors",
        lambda: [MonitorInfo("Test monitor", 80, 40)],
    )
    widget = MainWindow()
    widget._folder = None
    qtbot.addWidget(widget)
    yield widget
    widget._folder = None


def select_image(window, path, width=40, height=120):
    window._on_scan_finished([ImageInfo(path, width, height, 1.0)])
    window._table.selectRow(0)


@pytest.mark.parametrize("mode", [1, 2])
def test_phone_and_custom_copy_image_instead_of_applying(
    window, mode, tmp_path, make_split_image, monkeypatch
):
    def reject_apply(*args):
        pytest.fail("Phone and custom targets must never change the desktop")

    monkeypatch.setattr("wallpaper_manager.main_window.set_wallpaper", reject_apply)
    window._target_combo.setCurrentIndex(mode)
    window._custom_width.setValue(40)
    window._custom_height.setValue(20)
    select_image(window, make_split_image(tmp_path / "split.png", 40, 120))
    window._preview._set_position(1.0)
    clipboard = QGuiApplication.clipboard()
    clipboard.clear()

    window._apply_button.click()

    image = clipboard.image()
    target = window._current_target()
    assert (image.width(), image.height()) == (target.width, target.height)
    assert image.pixelColor(image.width() // 2, image.height() // 2).name() == "#0000ff"
    assert "Copy to Clipboard" in window._apply_button.text()
    assert "clipboard" in window.statusBar().currentMessage()
    clipboard.clear()


def test_switching_back_to_monitor_restores_desktop_action(
    window, tmp_path, make_image, monkeypatch
):
    calls = []
    monkeypatch.setattr("wallpaper_manager.main_window.set_wallpaper", lambda *a: calls.append(a))
    window._target_combo.setCurrentIndex(1)
    window._target_combo.setCurrentIndex(0)
    source = make_image(tmp_path / "image.png", 40, 120)
    select_image(window, source)
    window._apply_button.click()
    assert calls == [(source, 80, 40, 0.5)]
    assert "Set as Wallpaper" in window._apply_button.text()


@pytest.mark.parametrize("mode", [0, 1, 2])
def test_save_is_available_for_every_target_and_preserves_crop(
    window, mode, tmp_path, make_split_image, monkeypatch
):
    window._target_combo.setCurrentIndex(mode)
    window._custom_width.setValue(40)
    window._custom_height.setValue(20)
    assert not window._save_button.isHidden()
    assert not window._save_button.isEnabled()
    select_image(window, make_split_image(tmp_path / "source.png", 40, 120))
    window._preview._set_position(1.0)
    destination = tmp_path / "export"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(destination), ""))
    monkeypatch.setattr(
        "wallpaper_manager.main_window.set_wallpaper",
        lambda *a: pytest.fail("Saving must never change the desktop"),
    )

    window._save_button.click()

    saved = QImage(str(destination.with_suffix(".png")))
    target = window._current_target()
    assert (saved.width(), saved.height()) == (target.width, target.height)
    assert saved.pixelColor(saved.width() // 2, saved.height() // 2).name() == "#0000ff"


def test_cancel_save_does_not_render(window, tmp_path, make_image, monkeypatch):
    select_image(window, make_image(tmp_path / "source.png", 40, 120))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: ("", ""))
    monkeypatch.setattr(
        "wallpaper_manager.main_window.render_wallpaper",
        lambda *a: pytest.fail("Cancelling must not render an image"),
    )
    window._save_button.click()


@pytest.mark.parametrize("mode", [1, 2])
def test_scan_uses_target_for_ranking_and_minimum_size(window, image_folder, qtbot, mode):
    window._target_combo.setCurrentIndex(mode)
    window._phone_combo.setCurrentIndex(len(PHONE_PRESETS) - 1)
    window._custom_width.setValue(1280)
    window._custom_height.setValue(2856)
    window._folder = image_folder
    window._min_size_check.setChecked(True)
    window._start_scan()
    target = window._current_target()
    assert window._worker._target_ratio == target.ratio
    assert not window._target_combo.isEnabled()
    assert not window._save_button.isEnabled()
    qtbot.waitUntil(lambda: not window._is_scanning(), timeout=5000)
    # All fixture images are shorter than this phone's native resolution.
    assert window._model.rowCount() == 0
    window._min_size_check.setChecked(False)
    window._start_scan()
    qtbot.waitUntil(lambda: not window._is_scanning(), timeout=5000)
    assert window._selected_info().path.name == "portrait.png"
    assert window._preview.drag_axis() == Qt.Orientation.Horizontal


def test_custom_dimensions_change_preview_and_reject_zero(window, tmp_path, make_image):
    window._target_combo.setCurrentIndex(2)
    select_image(window, make_image(tmp_path / "image.png", 40, 120))
    window._custom_width.setValue(80)
    window._custom_height.setValue(40)
    assert window._preview.drag_axis() == Qt.Orientation.Vertical
    assert "80 x 40" in window._preview_label.full_text
    window._custom_width.setValue(0)
    assert window._current_target().width == 1


def test_target_changes_update_cached_results_without_scanning(window, image_folder, monkeypatch):
    window._folder = image_folder
    select_image(window, image_folder / "portrait.png", 1080, 1920)
    scans = []
    monkeypatch.setattr(window, "_start_scan", lambda: scans.append(window._current_target()))
    window._monitors.append(MonitorInfo("Second monitor", 1920, 1080))
    window._monitor_combo.addItem(window._monitors[-1].label)

    window._monitor_combo.setCurrentIndex(1)
    window._target_combo.setCurrentIndex(1)
    window._phone_combo.setCurrentIndex(1)
    window._target_combo.setCurrentIndex(2)
    window._custom_width.setValue(1080)
    window._custom_height.setValue(1920)

    assert scans == []
    assert window._selected_info() is not None
    assert "100.0% match" in window._preview_label.full_text
    assert window._model.data(window._model.index(0, 0)) == "100.0%"
    assert window.statusBar().currentMessage() == str(image_folder / "portrait.png")
    window._scan_button.click()
    assert scans == [MonitorInfo("Custom", 1080, 1920)]


@pytest.mark.parametrize("saving", [False, True])
def test_export_errors_restore_cursor_and_actions(
    window, tmp_path, make_image, monkeypatch, saving
):
    window._target_combo.setCurrentIndex(1)
    select_image(window, make_image(tmp_path / "image.png", 40, 120))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a))
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "saved.png"), "")
    )

    def fail_render(*args):
        raise WallpaperError("Unreadable source")

    monkeypatch.setattr("wallpaper_manager.main_window.render_wallpaper", fail_render)
    (window._save_button if saving else window._apply_button).click()
    assert errors
    assert QGuiApplication.overrideCursor() is None
    assert window._apply_button.isEnabled()
    assert window._save_button.isEnabled()


def test_failed_save_reports_error(window, tmp_path, make_image, monkeypatch):
    select_image(window, make_image(tmp_path / "image.png", 40, 120))
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: errors.append(a))
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a: (str(tmp_path / "missing" / "saved.png"), "")
    )
    window._save_button.click()
    assert errors
    assert "Could not write wallpaper" in errors[0][2]
    assert QGuiApplication.overrideCursor() is None
