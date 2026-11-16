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
5. **Apply to desktop** for monitor targets; **Copy cropped image** for phone and
   custom targets. **Save PNG…** works for every target. Double-click a library
   result to perform its primary action.

Scanning and preview decoding run on worker threads. The results list is
virtualized and has no image count cap. Rendering and export also run off the UI
thread. Unreadable files are skipped, EXIF rotations are honored, and common
JPEG, PNG, WebP, GIF (first frame), BMP, TIFF, ICO, PNM and TGA images are supported.
Folder, target and scan preferences, window geometry and panel widths persist
between launches. Existing Python/QSettings preferences are not migrated.

Windows application uses `SystemParametersInfoW` with Fill, a fresh PNG under
`%LOCALAPPDATA%\WallpaperManager\generated`, and retains the three newest
generated files. Saved exports are separate and never pruned. The chosen
monitor supplies the target dimensions; Windows applies the same image across
all monitors. Per-monitor wallpaper assignment is not implemented.

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
| `rust/src/core.rs` | Scanning, orientation, ranking, crop and render logic |
| `rust/src/platform.rs` | Windows monitors, desktop integration and PNG saving |
| `.github/workflows/rust-windows.yml` | Windows validation and executable artifact |

The prior Python implementation remains in `src/wallpaper_manager` for reference
and comparison. Its [original documentation](docs/legacy-python.md) describes
that version. Its build workflow is manual-only; Rust is the default build.

Licensed under the [MIT License](LICENSE). Dependencies retain their own licenses.
