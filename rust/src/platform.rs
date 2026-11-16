use std::path::Path;

#[cfg(windows)]
pub fn monitors() -> Vec<(String, u32, u32)> {
    use windows_sys::Win32::{
        Foundation::{BOOL, LPARAM, RECT},
        Graphics::Gdi::*,
    };
    unsafe extern "system" fn collect(
        monitor: HMONITOR,
        _: HDC,
        _: *mut RECT,
        data: LPARAM,
    ) -> BOOL {
        let mut info: MONITORINFO = unsafe { std::mem::zeroed() };
        info.cbSize = std::mem::size_of::<MONITORINFO>() as u32;
        if unsafe { GetMonitorInfoW(monitor, &mut info) } != 0 {
            let list = unsafe { &mut *(data as *mut Vec<(String, u32, u32)>) };
            list.push((
                format!(
                    "Display {}{}",
                    list.len() + 1,
                    if info.dwFlags == 1 { " (primary)" } else { "" }
                ),
                (info.rcMonitor.right - info.rcMonitor.left) as u32,
                (info.rcMonitor.bottom - info.rcMonitor.top) as u32,
            ));
        }
        1
    }
    let mut list = Vec::new();
    unsafe {
        EnumDisplayMonitors(
            std::ptr::null_mut(),
            std::ptr::null(),
            Some(collect),
            &mut list as *mut _ as isize,
        );
    }
    list
}
#[cfg(not(windows))]
pub fn monitors() -> Vec<(String, u32, u32)> {
    vec![("Preview display".into(), 1920, 1080)]
}

#[cfg(windows)]
pub fn apply(image: &image::DynamicImage) -> Result<(), String> {
    use std::{
        os::windows::ffi::OsStrExt,
        time::{SystemTime, UNIX_EPOCH},
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::*;
    use winreg::{RegKey, enums::*};
    let folder = std::env::var_os("LOCALAPPDATA").ok_or("LOCALAPPDATA is unavailable")?;
    let folder = Path::new(&folder).join("WallpaperManager/generated");
    std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_nanos();
    let path = folder.join(format!("wallpaper_{stamp}.png"));
    image.save(&path).map_err(|e| e.to_string())?;
    let desktop = RegKey::predef(HKEY_CURRENT_USER)
        .open_subkey_with_flags("Control Panel\\Desktop", KEY_SET_VALUE)
        .map_err(|e| e.to_string())?;
    desktop
        .set_value("WallpaperStyle", &"10")
        .map_err(|e| e.to_string())?;
    desktop
        .set_value("TileWallpaper", &"0")
        .map_err(|e| e.to_string())?;
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    if unsafe {
        SystemParametersInfoW(
            SPI_SETDESKWALLPAPER,
            0,
            wide.as_ptr() as *mut _,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
    } == 0
    {
        return Err(std::io::Error::last_os_error().to_string());
    }
    let mut files: Vec<_> = std::fs::read_dir(&folder)
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .map(|e| e.path())
        .filter(|p| {
            p.file_name()
                .is_some_and(|n| n.to_string_lossy().starts_with("wallpaper_"))
                && p.extension().is_some_and(|e| e == "png")
        })
        .collect();
    files.sort();
    files.reverse();
    for stale in files.into_iter().skip(3) {
        let _ = std::fs::remove_file(stale);
    }
    Ok(())
}
#[cfg(not(windows))]
pub fn apply(_: &image::DynamicImage) -> Result<(), String> {
    Err("Setting desktop wallpaper requires Windows.".into())
}

pub fn save(image: &image::DynamicImage, path: &Path) -> Result<(), String> {
    image
        .save_with_format(path, image::ImageFormat::Png)
        .map_err(|e| e.to_string())
}
