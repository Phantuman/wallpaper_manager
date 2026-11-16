use image::{DynamicImage, GenericImageView, imageops::FilterType};
use std::{
    path::{Path, PathBuf},
    sync::atomic::{AtomicBool, Ordering},
};

#[derive(Clone, Debug)]
pub struct Entry {
    pub path: PathBuf,
    pub width: u32,
    pub height: u32,
    pub score: f64,
}
pub fn score(w: u32, h: u32, tw: u32, th: u32) -> f64 {
    if [w, h, tw, th].contains(&0) {
        return 0.0;
    }
    let a = w as f64 / h as f64;
    let b = tw as f64 / th as f64;
    a.min(b) / a.max(b)
}
pub fn orientation(path: &Path) -> u32 {
    std::fs::File::open(path)
        .ok()
        .and_then(|file| {
            exif::Reader::new()
                .read_from_container(&mut std::io::BufReader::new(file))
                .ok()
        })
        .and_then(|exif| {
            exif.get_field(exif::Tag::Orientation, exif::In::PRIMARY)
                .and_then(|field| field.value.get_uint(0))
        })
        .unwrap_or(1)
}
pub fn dimensions(path: &Path) -> Option<(u32, u32)> {
    let (w, h) = image::image_dimensions(path).ok()?;
    if w == 0 || h == 0 {
        return None;
    }
    Some(if (5..=8).contains(&orientation(path)) {
        (h, w)
    } else {
        (w, h)
    })
}
pub fn load(path: &Path) -> Result<DynamicImage, String> {
    let image = image::open(path).map_err(|e| e.to_string())?;
    Ok(match orientation(path) {
        2 => image.fliph(),
        3 => image.rotate180(),
        4 => image.flipv(),
        5 => image.rotate90().fliph(),
        6 => image.rotate90(),
        7 => image.rotate90().flipv(),
        8 => image.rotate270(),
        _ => image,
    })
}
pub fn scan(
    folder: &Path,
    target: (u32, u32),
    recursive: bool,
    minimum: bool,
    cancel: &AtomicBool,
    mut progress: impl FnMut(usize),
) -> Vec<Entry> {
    let mut entries = Vec::new();
    let depth = if recursive { usize::MAX } else { 1 };
    for (count, item) in walkdir::WalkDir::new(folder)
        .follow_links(false)
        .max_depth(depth)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_file())
        .enumerate()
    {
        if cancel.load(Ordering::Relaxed) {
            break;
        }
        let path = item.path();
        if let Some((w, h)) = dimensions(path)
            && (!minimum || (w >= target.0 && h >= target.1))
        {
            entries.push(Entry {
                path: path.to_owned(),
                width: w,
                height: h,
                score: score(w, h, target.0, target.1),
            });
        }
        if count % 25 == 0 {
            progress(count + 1);
        }
    }
    entries.sort_by(|a, b| {
        (b.score * 1e6)
            .round()
            .total_cmp(&(a.score * 1e6).round())
            .then_with(|| {
                (b.width as u64 * b.height as u64).cmp(&(a.width as u64 * a.height as u64))
            })
            .then_with(|| a.path.cmp(&b.path))
    });
    entries
}
pub fn crop(w: u32, h: u32, target: (u32, u32), position: f32) -> (u32, u32, u32, u32) {
    assert!(w > 0 && h > 0 && target.0 > 0 && target.1 > 0);
    let ratio = target.0 as f64 / target.1 as f64;
    let (cw, ch) = if w as f64 / h as f64 > ratio {
        (((h as f64 * ratio).round() as u32).clamp(1, w), h)
    } else {
        (w, ((w as f64 / ratio).round() as u32).clamp(1, h))
    };
    let p = position.clamp(0.0, 1.0);
    (
        ((w - cw) as f32 * p).round() as u32,
        ((h - ch) as f32 * p).round() as u32,
        cw,
        ch,
    )
}
pub fn render(path: &Path, target: (u32, u32), position: f32) -> Result<DynamicImage, String> {
    if !(1..=8192).contains(&target.0) || !(1..=8192).contains(&target.1) {
        return Err("Target dimensions must be between 1 and 8192.".into());
    }
    let image = load(path)?;
    let (w, h) = image.dimensions();
    let (x, y, cw, ch) = crop(w, h, target, position);
    Ok(image
        .crop_imm(x, y, cw, ch)
        .resize_exact(target.0, target.1, FilterType::Lanczos3))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn symmetric_ranking() {
        assert_eq!(score(32, 9, 16, 9), score(16, 18, 16, 9));
        assert_eq!(score(0, 1, 1, 1), 0.0);
    }
    #[test]
    fn crop_edges_and_bounds() {
        assert_eq!(crop(400, 200, (1, 1), 0.0), (0, 0, 200, 200));
        assert_eq!(crop(400, 200, (1, 1), 1.0), (200, 0, 200, 200));
        assert_eq!(crop(200, 400, (1, 1), 0.5), (0, 100, 200, 200));
        assert_eq!(crop(200, 400, (1, 1), 2.0), (0, 200, 200, 200));
        for w in 1..40 {
            for h in 1..40 {
                let (x, y, cw, ch) = crop(w, h, (16, 9), 0.73);
                assert!(x + cw <= w && y + ch <= h && cw > 0 && ch > 0);
            }
        }
    }
    #[test]
    fn exif_rotation_and_invalid_targets() {
        let path = std::env::temp_dir().join(format!("wallpaper-exif-{}.jpg", std::process::id()));
        image::RgbImage::new(40, 20).save(&path).unwrap();
        let jpeg = std::fs::read(&path).unwrap();
        // Little-endian TIFF: one SHORT Orientation entry, value 6 (90° CW).
        let exif: &[u8] = &[
            0xff, 0xe1, 0, 34, b'E', b'x', b'i', b'f', 0, 0, b'I', b'I', 42, 0, 8, 0, 0, 0, 1, 0,
            0x12, 1, 3, 0, 1, 0, 0, 0, 6, 0, 0, 0, 0, 0, 0, 0,
        ];
        let mut oriented = jpeg[..2].to_vec();
        oriented.extend_from_slice(exif);
        oriented.extend_from_slice(&jpeg[2..]);
        std::fs::write(&path, oriented).unwrap();
        assert_eq!(dimensions(&path), Some((20, 40)));
        let decoded = load(&path).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (20, 40));
        assert!(render(&path, (0, 20), 0.5).is_err());
        assert!(render(&path, (8193, 20), 0.5).is_err());
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn scan_render_and_cancel() {
        let dir = std::env::temp_dir().join(format!("wallpaper-test-{}", std::process::id()));
        std::fs::create_dir_all(dir.join("nested")).unwrap();
        image::RgbImage::from_fn(40, 20, |x, _| image::Rgb([x as u8, 0, 0]))
            .save(dir.join("wide.png"))
            .unwrap();
        image::RgbImage::new(80, 40)
            .save(dir.join("nested/large.png"))
            .unwrap();
        std::fs::write(dir.join("bad.png"), b"broken").unwrap();
        let cancel = AtomicBool::new(false);
        let entries = scan(&dir, (2, 1), true, false, &cancel, |_| {});
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].width, 80);
        assert_eq!(scan(&dir, (2, 1), false, false, &cancel, |_| {}).len(), 1);
        assert!(scan(&dir, (100, 100), true, true, &cancel, |_| {}).is_empty());
        cancel.store(true, Ordering::Relaxed);
        assert!(scan(&dir, (2, 1), true, false, &cancel, |_| {}).is_empty());
        let left = render(&dir.join("wide.png"), (20, 20), 0.0)
            .unwrap()
            .to_rgb8();
        let right = render(&dir.join("wide.png"), (20, 20), 1.0)
            .unwrap()
            .to_rgb8();
        assert_eq!(left.dimensions(), (20, 20));
        assert!(left.get_pixel(0, 0)[0] < right.get_pixel(0, 0)[0]);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
