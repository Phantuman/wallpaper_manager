# Wallpaper Studio

A native Rust wallpaper manager for Windows. Browse a ranked image library,
compose a crop in a large preview, and apply or export an image at the exact
resolution you need. The interface uses a charcoal palette, mint accents,
resizable library panels, and a draggable crop overlay.

## Run on Windows

Install the stable Rust toolchain from <https://rustup.rs>. On Windows, install
Visual Studio Build Tools with **Desktop development with C++** and the Windows
SDK, then run:

```powershell
cargo run --release
```

Build a standalone executable:

```powershell
cargo build --locked --release
```

Run `target\release\WallpaperManager.exe`. Python and Qt are not required.
The **Rust Windows executable** GitHub Actions workflow checks formatting, lints,
runs tests, and produces the `WallpaperManager-rust-windows-x64` artifact on
pull requests, main pushes, or manual dispatch.

## Compose your wallpaper

1. Choose a folder. Include subfolders and optionally require images at least as
   large as the target. Press **Scan collection**; cancel at any time to keep
   partial results.
2. Choose a detected Windows monitor, a phone preset, or custom dimensions
   (1–8192 pixels per axis). Target changes update the crop immediately; scan
   again to refresh ranking and size filtering.
3. Type in **Search filenames** to filter the ranked library instantly, ignoring
   letter case and surrounding spaces. The count shows matching and total images;
   **Clear** restores the full list. Select a result to preview it. Fit scores
   compare aspect ratios symmetrically; ties at six decimal places favor larger images.
4. Drag the preview to reposition the highlighted crop, use its position slider,
   or double-click the preview to centre it. The dimmed area is excluded.
5. **Apply to selected display** for monitor targets; **Copy cropped image** for phone and
   custom targets. **Save PNG…** works for every target. Double-click a library
   result to perform its primary action.

Scanning and preview decoding run on worker threads. The results list is
virtualized and has no image count cap. Rendering and export also run off the UI
thread. Unreadable files are skipped, EXIF rotations are honored, and common
JPEG, PNG, WebP, GIF (first frame), BMP, TIFF, ICO, PNM and TGA images are supported.
Folder, target and scan preferences, window geometry and panel widths persist
between launches. Existing Python/QSettings preferences are not migrated.

Open **Compositions · Displays · Playlists** in the header for these features:

- **Saved compositions:** crop positions are remembered per image and target resolution.
  Enter a name and save a preset to keep the image, dimensions and crop together.
  Click its name to restore it, including after restarting the app. Saving the same
  name replaces it; Delete removes it. Settings save periodically and on normal exit.
- **Independent displays:** choose a monitor, select and frame an image, then
  **Assign current crop**. Repeat for other monitors. **Preview crops** shows the
  rendered crops in the physical display layout; **Apply layout** applies all saved
  connected assignments. **Apply to selected display** changes only that display.
  Assignments use Windows device paths and survive monitor reordering. Refresh
  displays after connecting or disconnecting hardware. Disconnected assignments are
  retained and skipped; Forget removes them. An OS failure may partially apply a layout.
- **Scheduled playlists:** enter a name, choose images, and save. Load a saved
  playlist, select a monitor, set a 1–1440 minute interval and press **Start / Resume**.
  Rotation starts immediately and stays pinned to that display until another
  playlist is loaded. **Pause** and **Next** preserve the queue. Shuffle visits each
  image once per cycle without repeating at the cycle boundary (unless there is
  only one image). Rotations reuse saved crops for that display's resolution.
  Missing images, unreadable files and disconnected displays pause rotation with
  an error. The app must remain open; playlists start paused after relaunch.
  Interval changes take effect when the next image starts.

Windows desktop application uses `IDesktopWallpaper` (Windows 8 or later), with a
fresh PNG under `%LOCALAPPDATA%\WallpaperManager\displays`. After a successful
change, the previous generated file for that display is removed. Files still used
by other displays and exported PNGs are retained. Rendering stays on worker threads.

## Development

```powershell
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked --all-targets
```

Tests cover scoring, crop bounds and positions, ranking ties, recursive scans,
minimum dimensions, corrupt files, cancellation, and rendered crop pixels. Tests
never apply a wallpaper. Linux builds support scanning and export for development;
setting desktop wallpaper requires Windows. Clipboard handoff is intended for
Windows; persistence after clipboard ownership ends varies on other platforms.

| Source | Purpose |
| --- | --- |
| `rust/src/main.rs` | Native egui interface, workers, preferences and preview |
| `rust/src/collections.rs` | Saved compositions, assignments, playlists and shuffle queue |
| `rust/src/core.rs` | Scanning, orientation, ranking, crop and render logic |
| `rust/src/platform.rs` | Windows monitors, desktop integration and PNG saving |
| `.github/workflows/rust-windows.yml` | Windows validation and executable artifact |

The prior Python implementation remains in `src/wallpaper_manager` for reference
and comparison. Its [original documentation](docs/legacy-python.md) describes
that version. Its build workflow is manual-only; Rust is the default build.

Licensed under the [MIT License](LICENSE). Dependencies retain their own licenses.
