from pathlib import Path

import pytest

from wallpaper_manager.scanning import (
    ScanWorker,
    aspect_score,
    iter_image_files,
    read_dimensions,
)

SIXTEEN_NINE = 16 / 9


def test_identical_ratios_score_one():
    assert aspect_score(SIXTEEN_NINE, SIXTEEN_NINE) == pytest.approx(1.0)


def test_score_is_symmetric():
    """Too wide and too tall by the same factor must rank equally."""
    assert aspect_score(SIXTEEN_NINE * 2, SIXTEEN_NINE) == pytest.approx(
        aspect_score(SIXTEEN_NINE / 2, SIXTEEN_NINE)
    )


def test_closer_ratio_scores_higher():
    assert aspect_score(1.7, SIXTEEN_NINE) > aspect_score(1.0, SIXTEEN_NINE)


def test_degenerate_ratios_score_zero():
    assert aspect_score(0, SIXTEEN_NINE) == 0.0
    assert aspect_score(SIXTEEN_NINE, 0) == 0.0


def test_iter_skips_non_images(image_folder: Path):
    names = {path.name for path in iter_image_files(image_folder)}
    assert "notes.txt" not in names
    assert "small_16x9.png" in names, "should descend into subfolders"


def test_iter_non_recursive_stays_shallow(image_folder: Path):
    names = {path.name for path in iter_image_files(image_folder, recursive=False)}
    assert "small_16x9.png" not in names
    assert "wide_16x9.png" in names


def test_read_dimensions(image_folder: Path):
    assert read_dimensions(image_folder / "wide_16x9.png") == (1920, 1080)


def test_read_dimensions_returns_none_for_corrupt_file(image_folder: Path):
    assert read_dimensions(image_folder / "broken.png") is None


def _run_scan(**kwargs):
    worker = ScanWorker(**kwargs)
    captured = []
    worker.finished.connect(captured.append)
    worker.run()
    assert captured, "worker did not emit finished"
    return captured[0]


def test_scan_ranks_by_aspect_match(image_folder: Path):
    results = _run_scan(folder=image_folder, target_ratio=SIXTEEN_NINE)

    assert [info.path.name for info in results[:2]] == ["wide_16x9.png", "small_16x9.png"]
    assert results[0].score == pytest.approx(1.0)
    assert [info.score for info in results] == sorted(
        (info.score for info in results), reverse=True
    )


def test_ties_break_towards_higher_resolution(image_folder: Path):
    results = _run_scan(folder=image_folder, target_ratio=SIXTEEN_NINE)
    exact = [info for info in results if info.score == pytest.approx(1.0)]
    assert [info.width for info in exact] == [1920, 640]


def test_equally_shaped_images_are_ordered_by_megapixels(tmp_path: Path, make_image):
    """Every 16:9 image ties on fit, so pixel count alone decides the order."""
    folder = tmp_path / "16x9"
    folder.mkdir()
    for width, height in ((1280, 720), (3840, 2160), (1920, 1080), (5120, 2880)):
        make_image(folder / f"{width}x{height}.png", width, height)

    results = _run_scan(folder=folder, target_ratio=SIXTEEN_NINE)

    assert all(info.score == pytest.approx(1.0) for info in results)
    assert [info.width for info in results] == [5120, 3840, 1920, 1280]


def test_every_image_is_returned(tmp_path: Path, make_image):
    """The list is uncapped: a folder of 250 images yields 250 rows."""
    folder = tmp_path / "many"
    folder.mkdir()
    for index in range(250):
        make_image(folder / f"img_{index:03d}.png", 100 + index, 100)

    results = _run_scan(folder=folder, target_ratio=SIXTEEN_NINE)
    assert len(results) == 250


def test_scan_skips_undersized_images_when_asked(image_folder: Path):
    results = _run_scan(
        folder=image_folder, target_ratio=SIXTEEN_NINE, min_width=1920, min_height=1080
    )
    names = {info.path.name for info in results}
    assert "small_16x9.png" not in names
    assert "wide_16x9.png" in names


def test_corrupt_files_are_skipped_not_fatal(image_folder: Path):
    results = _run_scan(folder=image_folder, target_ratio=SIXTEEN_NINE)
    assert "broken.png" not in {info.path.name for info in results}


def test_missing_folder_yields_no_results(tmp_path: Path, qapp):
    results = _run_scan(folder=tmp_path / "does_not_exist", target_ratio=SIXTEEN_NINE)
    assert results == []
