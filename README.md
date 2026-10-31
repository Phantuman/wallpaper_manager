# Wallpaper Manager

Point it at a folder of images and it ranks them by how closely each one matches
your selected monitor, phone, or custom resolution's aspect ratio, best first.
Pick one, adjust the crop in the preview, then apply, copy, or save the wallpaper.

Built with [PySide6](https://doc.qt.io/qtforpython/) and managed with [uv](https://docs.astral.sh/uv/).

## How it works

**Target.** Choose Monitor to use a connected display's physical pixel size, Phone
to pick an iPhone, Samsung Galaxy, or Google Pixel preset, or Custom resolution to
enter width and height in pixels (1–8192 each). Phone presets use portrait dimensions.
Changing the target updates the preview without starting a scan. Press Scan to
update ranking and the “Only ≥ target size” filter for that resolution. Target controls are disabled
while a scan runs.

Preset dimensions come from manufacturer specifications: [iPhone 17](https://support.apple.com/en-us/125089),
[iPhone 16](https://support.apple.com/en-us/121029),
[16 Plus](https://support.apple.com/en-us/121030),
[16 Pro](https://support.apple.com/en-us/121031),
[16 Pro Max](https://support.apple.com/en-us/121032),
[iPhone 15](https://support.apple.com/en-us/111831),
[iPhone 14](https://support.apple.com/en-us/111850),
[Galaxy S25 / S25+](https://www.samsung.com/my/smartphones/galaxy-s25/specs/),
[S25 Ultra](https://www.samsung.com/in/business/smartphones/galaxy-s/galaxy-s25-ultra-sm-s938bztbins/),
[Galaxy A55](https://www.samsung.com/nz/smartphones/galaxy-a/galaxy-a55-5g-awesome-navy-256gb-sm-a556ezkcxnz/),
and [Pixel phones](https://support.google.com/pixelphone/answer/7158570?hl=en).

**Ranking.** Each image scores `min(image_ratio, target_ratio) / max(image_ratio, target_ratio)`,
shown as a percentage — 100% is a perfect shape match. The score is symmetric, so an image
that is twice too wide ranks the same as one twice too tall. Every image found is listed, with
no cap.

**Ties.** Images that fit equally well are ordered by megapixels, largest first. Scores are
rounded to 6 decimals before comparing, so 1920x1080 and 5120x2880 count as the same fit
rather than being split apart by floating-point noise.

**Scanning** reads only each file's header (via `QImageReader`), never decoding pixels, so
large folders scan quickly. It runs on a worker thread and can be cancelled; unreadable files
and inaccessible folders are skipped rather than aborting the scan. EXIF orientation is
honoured, so a rotated portrait photo is measured as portrait.

**Preview** shows the whole image with everything outside the crop region dimmed — that
highlighted rectangle is exactly what becomes your wallpaper. Selecting a row puts that
image's full path in the status bar; the image count sits on the right.

**Moving the crop.** Drag the preview with the left mouse button and the crop window follows
the cursor; double-click re-centres it. Only one axis ever has room to move — a too-tall image
slides up and down, a too-wide one left and right — so the cursor changes to show which, and an
exact ratio match is not draggable at all. The position is a fraction from 0.0 (flush
left/top) through 0.5 (centred) to 1.0 (flush right/bottom), and it feeds straight into
`set_wallpaper`, so what you drag to is what gets applied. Selecting a different image resets
it to centred.

**Applying** crops the image to the monitor's aspect ratio and scales it to the
monitor's real pixel size, so Windows never rescales it. The result is written to a fresh file
under `%LOCALAPPDATA%\WallpaperManager\generated\` (a new filename each time — Windows caches
the desktop background by path) and applied with `SystemParametersInfoW`. Only the last three
generated files are kept.

**Copying and saving.** For Phone and Custom resolution targets, the primary button
becomes “Copy to Clipboard (cropped)”: it copies the rendered image at the selected
size without changing the desktop background. Double-clicking a result uses that
same action. “Save Wallpaper…” is always shown for every target and lets you save
the current crop as a PNG at a location you choose. It is enabled after selecting
an image, when scanning is finished. Saved exports are separate from the generated
desktop wallpaper cache and are never pruned.

### Current limits

- Setting the wallpaper is Windows-only. The scanning, scoring and preview work anywhere;
  `set_wallpaper` raises `WallpaperError` on other platforms.
- The monitor dropdown chooses which monitor's *shape* to target. Windows then applies that
  one image across all monitors (style "Fill") — per-monitor wallpapers would need the
  `IDesktopWallpaper` COM interface.
- The crop can be repositioned but not resized — it is always the largest rectangle that fits.
- The crop position is not remembered per image; switching rows resets it to centred.

## Setup

Install dependencies (creates `.venv` automatically):

```bash
uv sync
```

## Run

```bash
uv run wallpaper-manager
```

Or as a module:

```bash
uv run python -m wallpaper_manager
```

## Windows executable

The **Build Windows executable** GitHub Actions workflow runs only on pushes to
the `master` branch.
It lints and tests the app on Windows with Python 3.12, then uses PyInstaller to
bundle the app, Python, Qt, and the app's resources into `WallpaperManager.exe`.
No Python installation is needed to run the executable.

To download it, open a successful workflow run under **Actions** and download the
`WallpaperManager-windows-x64` artifact. Extract the ZIP and run
`WallpaperManager.exe`. Artifacts are kept for 30 days.

To build the same executable locally on Windows after `uv sync`:

```powershell
uv run --locked --with pyinstaller==6.22.3 python -m PyInstaller --noconfirm --clean --onefile --windowed --name WallpaperManager --specpath build --collect-data wallpaper_manager src/wallpaper_manager/__main__.py
```

The output is `dist/WallpaperManager.exe`.

## Develop

Run the tests:

```bash
uv run pytest
```

Lint:

```bash
uv run ruff check --fix .
```

Format:

```bash
uv run ruff format .
```

Add a dependency:

```bash
uv add <package>
```

## Layout

| Path | Purpose |
| --- | --- |
| `src/wallpaper_manager/app.py` | Builds the `QApplication` and launches the main window |
| `src/wallpaper_manager/main_window.py` | `MainWindow` — controls, results table, scan thread, monitor detection |
| `src/wallpaper_manager/scanning.py` | Folder walking, header-only size reads, aspect scoring, `ScanWorker` |
| `src/wallpaper_manager/wallpaper.py` | Crop maths, rendering, and applying the wallpaper |
| `src/wallpaper_manager/preview.py` | Preview pane with the draggable crop overlay |
| `src/wallpaper_manager/models.py` | `ResultsModel` backing the results table |
| `src/wallpaper_manager/resources.py` | Bundled assets — loads the app icon |
| `src/wallpaper_manager/resources/icon.svg` | The application icon |
| `src/wallpaper_manager/__main__.py` | `python -m wallpaper_manager` entry point |
| `tests/` | pytest + pytest-qt tests |

Window geometry, splitter position and the last scanned folder are persisted via `QSettings`.

**The icon** is a single SVG, set on the `QApplication` so every window and dialog picks it up,
and re-rendered by Qt at whatever size is asked for. Qt implements SVG Tiny 1.2, so the file
avoids `clipPath` and other full-SVG features — edit it with that in mind. On Windows the app
also claims its own `AppUserModelID`, without which the taskbar would group the window under
`python.exe` and show the interpreter's icon.

> The tests never call `set_wallpaper` — it would change the desktop background of whoever
> runs the suite. Only the crop and render maths are exercised.

## License

Wallpaper Manager is licensed under the [MIT License](LICENSE).

PySide6, Qt, and other dependencies retain their own licenses. Distributing a
bundled application requires complying with the licenses of the Qt modules and
third-party components included; see [Qt's open-source licensing obligations](https://www.qt.io/development/open-source-lgpl-obligations).
