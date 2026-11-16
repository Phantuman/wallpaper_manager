use std::path::Path;

#[derive(Clone, Debug)]
pub struct Monitor {
    pub id: String,
    pub name: String,
    pub width: u32,
    pub height: u32,
    pub rect: (i32, i32, i32, i32),
}

#[cfg(windows)]
fn desktop<T>(
    f: impl FnOnce(windows::Win32::UI::Shell::IDesktopWallpaper) -> Result<T, String>,
) -> Result<T, String> {
    use windows::Win32::{System::Com::*, UI::Shell::*};
    // Each call is made on its own short-lived thread/apartment by the caller.
    unsafe {
        CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            .ok()
            .map_err(|e| e.to_string())?;
        let result = CoCreateInstance(&DesktopWallpaper, None, CLSCTX_ALL)
            .map_err(|e| e.to_string())
            .and_then(f);
        CoUninitialize();
        result
    }
}
#[cfg(windows)]
pub fn monitors() -> Vec<Monitor> {
    std::thread::spawn(|| {
        desktop(|wallpaper| unsafe {
            use windows::{Win32::System::Com::CoTaskMemFree, core::PCWSTR};
            let mut result = Vec::new();
            for index in 0..wallpaper
                .GetMonitorDevicePathCount()
                .map_err(|e| e.to_string())?
            {
                let path = wallpaper
                    .GetMonitorDevicePathAt(index)
                    .map_err(|e| e.to_string())?;
                let rect = wallpaper.GetMonitorRECT(PCWSTR(path.0));
                let id = path.to_string();
                CoTaskMemFree(Some(path.0.cast()));
                let rect = rect.map_err(|e| e.to_string())?;
                result.push(Monitor {
                    id: id.map_err(|e| e.to_string())?,
                    name: format!("Display {}", index + 1),
                    width: (rect.right - rect.left) as u32,
                    height: (rect.bottom - rect.top) as u32,
                    rect: (rect.left, rect.top, rect.right, rect.bottom),
                });
            }
            Ok(result)
        })
    })
    .join()
    .ok()
    .and_then(Result::ok)
    .unwrap_or_default()
}
#[cfg(not(windows))]
pub fn monitors() -> Vec<Monitor> {
    vec![Monitor {
        id: "preview".into(),
        name: "Preview display".into(),
        width: 1920,
        height: 1080,
        rect: (0, 0, 1920, 1080),
    }]
}

#[cfg(windows)]
pub fn apply(image: &image::DynamicImage, monitor_id: &str) -> Result<(), String> {
    use std::{
        os::windows::ffi::OsStrExt,
        time::{SystemTime, UNIX_EPOCH},
    };
    use windows::core::PCWSTR;
    let folder = std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA is unavailable")?;
    let folder = Path::new(&folder).join("WallpaperManager/displays");
    std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let path = folder.join(format!("wallpaper_{stamp}.png"));
    save(image, &path)?;
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let id: Vec<u16> = monitor_id.encode_utf16().chain(Some(0)).collect();
    let result = desktop(|wallpaper| unsafe {
        // A disconnected device must not silently fall back to all monitors.
        let mut connected = false;
        let mut other_wallpapers = Vec::new();
        for i in 0..wallpaper
            .GetMonitorDevicePathCount()
            .map_err(|e| e.to_string())?
        {
            let device = wallpaper
                .GetMonitorDevicePathAt(i)
                .map_err(|e| e.to_string())?;
            if device.to_string().is_ok_and(|value| value == monitor_id) {
                connected = true;
            } else if let Ok(current) = wallpaper.GetWallpaper(PCWSTR(device.0)) {
                if let Ok(path) = current.to_string() {
                    other_wallpapers.push(std::path::PathBuf::from(path));
                }
                windows::Win32::System::Com::CoTaskMemFree(Some(current.0.cast()));
            }
            windows::Win32::System::Com::CoTaskMemFree(Some(device.0.cast()));
        }
        if !connected {
            return Err("The selected display is disconnected. Refresh displays.".into());
        }
        let old = wallpaper.GetWallpaper(PCWSTR(id.as_ptr())).ok();
        let old_path = old.and_then(|value| {
            let path = value.to_string().ok();
            windows::Win32::System::Com::CoTaskMemFree(Some(value.0.cast()));
            path
        });
        wallpaper
            .SetWallpaper(PCWSTR(id.as_ptr()), PCWSTR(wide.as_ptr()))
            .map_err(|e| e.to_string())?;
        if let Some(old) = old_path {
            let old = std::path::PathBuf::from(old);
            if old.parent() == Some(folder.as_path())
                && old != path
                && !other_wallpapers.contains(&old)
            {
                let _ = std::fs::remove_file(old);
            }
        }
        Ok(())
    });
    if result.is_err() {
        let _ = std::fs::remove_file(path);
    }
    result
}
#[cfg(not(windows))]
pub fn apply(_: &image::DynamicImage, _: &str) -> Result<(), String> {
    Err("Setting desktop wallpaper requires Windows.".into())
}
pub fn save(image: &image::DynamicImage, path: &Path) -> Result<(), String> {
    image
        .save_with_format(path, image::ImageFormat::Png)
        .map_err(|e| e.to_string())
}
