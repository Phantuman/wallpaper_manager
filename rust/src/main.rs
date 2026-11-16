#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]
mod collections;
mod core;
mod platform;
use eframe::egui::{self, Color32, RichText, Vec2};
use std::{
    path::PathBuf,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

const ACCENT: Color32 = Color32::from_rgb(109, 213, 191);
const PRESETS: &[(&str, u32, u32)] = &[
    ("iPhone 17", 1206, 2622),
    ("iPhone 16 / 15", 1179, 2556),
    ("iPhone 16 Plus", 1290, 2796),
    ("iPhone 16 Pro", 1206, 2622),
    ("iPhone 16 Pro Max", 1320, 2868),
    ("iPhone 14", 1170, 2532),
    ("Galaxy S25 / A55", 1080, 2340),
    ("Galaxy S25+ / Ultra", 1440, 3120),
    ("Pixel 9", 1080, 2424),
    ("Pixel 9 Pro / 10 Pro", 1280, 2856),
];
#[derive(serde::Serialize, serde::Deserialize)]
#[serde(default)]
struct Settings {
    folder: String,
    recursive: bool,
    minimum: bool,
    mode: usize,
    phone: usize,
    width: u32,
    height: u32,
    library: collections::Library,
    interval_minutes: u32,
    shuffle: bool,
}
impl Default for Settings {
    fn default() -> Self {
        Self {
            folder: String::new(),
            recursive: true,
            minimum: false,
            mode: 0,
            phone: 0,
            width: 1920,
            height: 1080,
            library: Default::default(),
            interval_minutes: 15,
            shuffle: false,
        }
    }
}
enum Event {
    Progress(usize),
    Scanned(Vec<core::Entry>, bool),
    Preview(usize, Result<(egui::ColorImage, (u32, u32)), String>),
    Action(Result<String, String>),
    LayoutPreview(Vec<(String, Result<egui::ColorImage, String>)>),
}
struct Studio {
    settings: Settings,
    monitors: Vec<platform::Monitor>,
    active_target: (u32, u32),
    collection_window: bool,
    preset_name: String,
    playlist_name: String,
    queue: collections::Queue,
    playlist_monitor: Option<platform::Monitor>,
    next_rotation: Option<Instant>,
    layout_textures: std::collections::BTreeMap<String, egui::TextureHandle>,
    monitor: usize,
    entries: Vec<core::Entry>,
    selected: Option<usize>,
    texture: Option<egui::TextureHandle>,
    original: (u32, u32),
    position: f32,
    query: String,
    status: String,
    failed: bool,
    scanning: bool,
    busy: bool,
    preview_id: usize,
    preview_pending: bool,
    cancel: Arc<AtomicBool>,
    tx: mpsc::Sender<Event>,
    rx: mpsc::Receiver<Event>,
}
impl Studio {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        let mut visuals = egui::Visuals::dark();
        visuals.panel_fill = Color32::from_rgb(20, 25, 34);
        visuals.window_fill = Color32::from_rgb(25, 31, 42);
        visuals.selection.bg_fill = Color32::from_rgb(38, 83, 80);
        visuals.selection.stroke = egui::Stroke::new(1.0_f32, ACCENT);
        cc.egui_ctx.set_visuals(visuals);
        cc.egui_ctx.style_mut(|s| {
            s.spacing.item_spacing = Vec2::new(10.0, 10.0);
            s.spacing.button_padding = Vec2::new(14.0, 9.0);
        });
        let settings = cc
            .storage
            .and_then(|s| eframe::get_value(s, "studio"))
            .unwrap_or_default();
        Self::from_settings(settings)
    }
    fn from_settings(settings: Settings) -> Self {
        let (tx, rx) = mpsc::channel();
        Self {
            settings,
            monitors: platform::monitors(),
            monitor: 0,
            active_target: (1920, 1080),
            collection_window: false,
            preset_name: String::new(),
            playlist_name: String::new(),
            queue: Default::default(),
            playlist_monitor: None,
            next_rotation: None,
            layout_textures: Default::default(),
            entries: vec![],
            selected: None,
            texture: None,
            original: (1, 1),
            position: 0.5,
            query: String::new(),
            status: "Choose an image folder to get started.".into(),
            failed: false,
            scanning: false,
            busy: false,
            preview_id: 0,
            preview_pending: false,
            cancel: Arc::new(AtomicBool::new(false)),
            tx,
            rx,
        }
    }
    fn target(&self) -> (u32, u32) {
        match self.settings.mode {
            0 => self
                .monitors
                .get(self.monitor)
                .map(|m| (m.width, m.height))
                .unwrap_or((1920, 1080)),
            1 => {
                let p = PRESETS[self.settings.phone.min(PRESETS.len() - 1)];
                (p.1, p.2)
            }
            _ => (
                self.settings.width.clamp(1, 8192),
                self.settings.height.clamp(1, 8192),
            ),
        }
    }
    fn scan(&mut self) {
        self.remember_crop();
        let folder = PathBuf::from(&self.settings.folder);
        let folder = folder.canonicalize().unwrap_or(folder);
        if !folder.is_dir() {
            self.status = "Choose an existing, readable folder.".into();
            self.failed = true;
            return;
        }
        self.scanning = true;
        self.failed = false;
        self.selected = None;
        self.texture = None;
        self.preview_id += 1;
        self.preview_pending = false;
        self.cancel = Arc::new(AtomicBool::new(false));
        let cancel = self.cancel.clone();
        let tx = self.tx.clone();
        let target = self.target();
        let recursive = self.settings.recursive;
        let minimum = self.settings.minimum;
        self.status = "Scanning image headers…".into();
        std::thread::spawn(move || {
            let entries = core::scan(&folder, target, recursive, minimum, &cancel, |count| {
                let _ = tx.send(Event::Progress(count));
            });
            let _ = tx.send(Event::Scanned(entries, cancel.load(Ordering::Relaxed)));
        });
    }
    fn select(&mut self, index: usize) {
        self.remember_crop();
        self.selected = Some(index);
        self.active_target = self.target();
        self.position = self
            .settings
            .library
            .position(&self.entries[index].path, self.target());
        self.texture = None;
        self.preview_id += 1;
        self.preview_pending = true;
        self.failed = false;
        let id = self.preview_id;
        let tx = self.tx.clone();
        let path = self.entries[index].path.clone();
        self.status = path.display().to_string();
        std::thread::spawn(move || {
            let result = core::load(&path).map(|image| {
                let size = (image.width(), image.height());
                let thumb = image.thumbnail(1600, 1200).to_rgba8();
                (
                    egui::ColorImage::from_rgba_unmultiplied(
                        [thumb.width() as usize, thumb.height() as usize],
                        thumb.as_raw(),
                    ),
                    size,
                )
            });
            let _ = tx.send(Event::Preview(id, result));
        });
    }
    fn action(&mut self, kind: u8) {
        let Some(index) = self.selected else { return };
        let destination = if kind == 2 {
            let Some(path) = rfd::FileDialog::new()
                .set_file_name("wallpaper.png")
                .add_filter("PNG image", &["png"])
                .save_file()
            else {
                return;
            };
            Some(path)
        } else {
            None
        };
        let path = self.entries[index].path.clone();
        let target = self.target();
        let monitor_id = self
            .monitors
            .get(self.monitor)
            .map(|m| m.id.clone())
            .unwrap_or_default();
        let position = self.position;
        let tx = self.tx.clone();
        self.busy = true;
        self.failed = false;
        self.status = "Rendering your wallpaper…".into();
        std::thread::spawn(move || {
            let result = core::render(&path, target, position).and_then(|image| match kind {
                0 => {
                    platform::apply(&image, &monitor_id)?;
                    Ok("Desktop wallpaper updated.".into())
                }
                1 => {
                    let rgba = image.to_rgba8();
                    let mut clipboard = arboard::Clipboard::new().map_err(|e| e.to_string())?;
                    clipboard
                        .set_image(arboard::ImageData {
                            width: rgba.width() as usize,
                            height: rgba.height() as usize,
                            bytes: std::borrow::Cow::Owned(rgba.into_raw()),
                        })
                        .map_err(|e| e.to_string())?;
                    Ok("Cropped wallpaper copied to clipboard.".into())
                }
                _ => {
                    let destination = destination.unwrap();
                    platform::save(&image, &destination)?;
                    Ok(format!("Saved {}", destination.display()))
                }
            });
            let _ = tx.send(Event::Action(result));
        });
    }
    fn events(&mut self, ctx: &egui::Context) {
        while let Ok(event) = self.rx.try_recv() {
            match event {
                Event::Progress(count) => self.status = format!("Examined {count} files…"),
                Event::Scanned(entries, cancelled) => {
                    self.scanning = false;
                    self.entries = entries;
                    self.status = format!(
                        "{} images · {}",
                        self.entries.len(),
                        if cancelled {
                            "Scan cancelled; partial results shown"
                        } else {
                            "Ranked by fit, then resolution"
                        }
                    );
                }
                Event::Preview(id, result) if id == self.preview_id => {
                    self.preview_pending = false;
                    match result {
                        Ok((image, size)) => {
                            self.original = size;
                            self.texture = Some(ctx.load_texture(
                                "preview",
                                image,
                                egui::TextureOptions::LINEAR,
                            ));
                        }
                        Err(e) => {
                            self.status = format!("Could not load preview: {e}");
                            self.failed = true;
                        }
                    }
                }
                Event::LayoutPreview(images) => {
                    self.busy = false;
                    self.layout_textures.clear();
                    for (id, result) in images {
                        match result {
                            Ok(image) => {
                                self.layout_textures.insert(
                                    id.clone(),
                                    ctx.load_texture(id, image, egui::TextureOptions::LINEAR),
                                );
                            }
                            Err(error) => {
                                self.failed = true;
                                self.status = error;
                            }
                        }
                    }
                }
                Event::Action(result) => {
                    self.busy = false;
                    self.failed = result.is_err();
                    if self.failed {
                        self.next_rotation = None;
                    }
                    self.status =
                        result.unwrap_or_else(|e| format!("Unable to complete action: {e}"));
                }
                _ => {}
            }
        }
    }
    fn remember_crop(&mut self) {
        if let Some(index) = self.selected
            && let Some(entry) = self.entries.get(index)
        {
            self.settings.library.remember(collections::Composition {
                path: entry.path.clone(),
                target: self.active_target,
                position: self.position,
            });
        }
    }
    fn composition(&self) -> Option<collections::Composition> {
        self.selected
            .and_then(|index| self.entries.get(index))
            .map(|entry| collections::Composition {
                path: entry.path.clone(),
                target: self.target(),
                position: self.position,
            })
    }
    fn load_composition(&mut self, composition: collections::Composition) {
        if !composition.path.is_file() {
            self.status = format!("Image is missing: {}", composition.path.display());
            self.failed = true;
            return;
        }
        self.remember_crop();
        self.selected = None;
        self.settings.mode = 2;
        (self.settings.width, self.settings.height) = composition.target;
        self.settings.library.remember(composition.clone());
        let index = self
            .entries
            .iter()
            .position(|e| e.path == composition.path)
            .unwrap_or_else(|| {
                self.entries.push(core::Entry {
                    path: composition.path,
                    width: 1,
                    height: 1,
                    score: 0.0,
                });
                self.entries.len() - 1
            });
        self.select(index);
    }
    fn playlist_next(&mut self) {
        if self.busy || self.scanning {
            return;
        }
        let Some(monitor) = self.playlist_monitor.clone() else {
            self.status = "Start a playlist on a monitor first.".into();
            return;
        };
        let Some(path) = self.queue.next(self.settings.shuffle) else {
            self.next_rotation = None;
            return;
        };
        let target = (monitor.width, monitor.height);
        let position = self.settings.library.position(&path, target);
        let tx = self.tx.clone();
        self.busy = true;
        if self.next_rotation.is_some() {
            self.next_rotation = Some(
                Instant::now()
                    + Duration::from_secs(
                        self.settings.interval_minutes.clamp(1, 1440) as u64 * 60,
                    ),
            );
        }
        std::thread::spawn(move || {
            let result = core::render(&path, target, position).and_then(|image| {
                platform::apply(&image, &monitor.id)?;
                Ok(format!("Playlist: {}", path.display()))
            });
            let _ = tx.send(Event::Action(result));
        });
    }
    fn layout_action(&mut self, preview: bool) {
        let assignments: Vec<_> = self
            .monitors
            .iter()
            .filter_map(|monitor| {
                self.settings
                    .library
                    .displays
                    .get(&monitor.id)
                    .map(|c| (monitor.clone(), c.clone()))
            })
            .collect();
        let tx = self.tx.clone();
        self.busy = true;
        self.failed = false;
        std::thread::spawn(move || {
            if preview {
                let images = assignments
                    .into_iter()
                    .map(|(m, c)| {
                        let result =
                            core::render(&c.path, (m.width, m.height), c.position).map(|image| {
                                let thumb = image.thumbnail(400, 240).to_rgba8();
                                egui::ColorImage::from_rgba_unmultiplied(
                                    [thumb.width() as usize, thumb.height() as usize],
                                    thumb.as_raw(),
                                )
                            });
                        (m.id, result)
                    })
                    .collect();
                let _ = tx.send(Event::LayoutPreview(images));
            } else {
                // Validate every source before applying any display. Keep at most one full image in memory.
                let result = (|| {
                    if assignments.is_empty() {
                        return Err(
                            "No connected display assignments. Assign an image first.".into()
                        );
                    }
                    for (m, c) in &assignments {
                        core::render(&c.path, (m.width, m.height), c.position)?;
                    }
                    for (m, c) in &assignments {
                        let image = core::render(&c.path, (m.width, m.height), c.position)?;
                        platform::apply(&image, &m.id)
                            .map_err(|e| format!("Layout partially applied; {}: {e}", m.name))?;
                    }
                    Ok(format!(
                        "Applied {} display assignments. Disconnected displays skipped.",
                        assignments.len()
                    ))
                })();
                let _ = tx.send(Event::Action(result));
            }
        });
    }
    fn collections_ui(&mut self, ctx: &egui::Context) {
        let mut open = self.collection_window;
        egui::Window::new("Compositions, displays and playlists").open(&mut open).default_width(600.0).vscroll(true).show(ctx, |ui| {
            ui.add_enabled_ui(!self.busy && !self.scanning, |ui| {
                ui.heading("Saved compositions");
                ui.label("Crops are remembered per image and resolution. Named presets also save the image and target.");
                ui.horizontal_wrapped(|ui| {
                    ui.text_edit_singleline(&mut self.preset_name);
                    if ui.add_enabled(self.selected.is_some() && !self.preset_name.trim().is_empty(), egui::Button::new("Save / replace preset")).clicked() && let Some(c) = self.composition() {
                        self.settings.library.presets.insert(self.preset_name.trim().into(), c);
                    }
                });
                for (name, composition) in self.settings.library.presets.clone() {
                    ui.horizontal_wrapped(|ui| {
                        if ui.button(&name).clicked() { self.load_composition(composition); }
                        if ui.small_button("Delete").clicked() { self.settings.library.presets.remove(&name); }
                    });
                }
                ui.separator(); ui.heading("Display layout");
                ui.label("Select a monitor and frame an image in the main window, then assign it here.");
                ui.horizontal_wrapped(|ui| {
                    if ui.button("Refresh displays").clicked() { self.monitors = platform::monitors(); self.monitor = 0; self.layout_textures.clear(); }
                    if ui.add_enabled(self.settings.mode == 0 && self.selected.is_some(), egui::Button::new("Assign current crop")).clicked() && let (Some(m), Some(c)) = (self.monitors.get(self.monitor), self.composition()) {
                        self.settings.library.displays.insert(m.id.clone(), c);
                        self.layout_textures.clear();
                    }
                    if ui.button("Preview crops").clicked() { self.layout_action(true); }
                    if ui.button("Apply layout").clicked() { self.layout_action(false); }
                });
                let (canvas, _) = ui.allocate_exact_size(Vec2::new(ui.available_width(), 220.0), egui::Sense::hover());
                let left = self.monitors.iter().map(|m| m.rect.0).min().unwrap_or(0);
                let top = self.monitors.iter().map(|m| m.rect.1).min().unwrap_or(0);
                let right = self.monitors.iter().map(|m| m.rect.2).max().unwrap_or(1);
                let bottom = self.monitors.iter().map(|m| m.rect.3).max().unwrap_or(1);
                let scale = (canvas.width() / (right - left).max(1) as f32).min(canvas.height() / (bottom - top).max(1) as f32);
                for monitor in &self.monitors {
                    let rect = egui::Rect::from_min_size(canvas.min + Vec2::new((monitor.rect.0-left) as f32, (monitor.rect.1-top) as f32)*scale, Vec2::new(monitor.width as f32, monitor.height as f32)*scale).shrink(3.0);
                    ui.painter().rect_filled(rect, 2.0, Color32::from_gray(50));
                    if let Some(texture) = self.layout_textures.get(&monitor.id) { ui.painter().image(texture.id(), rect, egui::Rect::from_min_max(egui::pos2(0.0,0.0),egui::pos2(1.0,1.0)), Color32::WHITE); }
                    ui.painter().text(rect.center(), egui::Align2::CENTER_CENTER, &monitor.name, egui::FontId::proportional(14.0), Color32::WHITE);
                }
                let mut clear_display = None;
                for monitor in &self.monitors {
                    ui.horizontal_wrapped(|ui| {
                    if let Some(c) = self.settings.library.displays.get(&monitor.id) { ui.label(format!("{}: {}", monitor.name, c.path.display())); }
                    else { ui.label(format!("{}: no assignment", monitor.name)); }
                    if ui.small_button("Clear assignment").clicked() { clear_display = Some(monitor.id.clone()); }
                    });
                }
                if let Some(id) = clear_display { self.settings.library.displays.remove(&id); self.layout_textures.remove(&id); }
                let disconnected: Vec<_> = self.settings.library.displays.keys().filter(|id| !self.monitors.iter().any(|m| &m.id == *id)).cloned().collect();
                for id in disconnected { ui.horizontal_wrapped(|ui| { ui.label("Saved disconnected display"); if ui.small_button("Forget").clicked() { self.settings.library.displays.remove(&id); } }); }
                ui.separator(); ui.heading("Scheduled playlists");
                ui.label("Runs while this app is open. Start pins rotation to the selected monitor. Errors pause rotation.");
                ui.text_edit_singleline(&mut self.playlist_name);
                ui.horizontal_wrapped(|ui| {
                    if ui.add_enabled(!self.playlist_name.trim().is_empty(), egui::Button::new("Choose images / save playlist…")).clicked() && let Some(paths) = rfd::FileDialog::new().add_filter("Images", &["png", "jpg", "jpeg", "webp", "bmp", "tiff", "gif"]).pick_files() {
                        self.settings.library.playlists.insert(self.playlist_name.trim().into(), paths.clone());
                        self.queue = collections::Queue::new(paths); self.next_rotation = None; self.playlist_monitor = None;
                    }
                    ui.add(egui::DragValue::new(&mut self.settings.interval_minutes).range(1..=1440).suffix(" minutes"));
                    ui.checkbox(&mut self.settings.shuffle, "Shuffle without repeats");
                });
                for (name, paths) in self.settings.library.playlists.clone() {
                    ui.horizontal_wrapped(|ui| {
                        if ui.button(format!("Load {name} ({} images)", paths.len())).clicked() { self.queue = collections::Queue::new(paths); self.next_rotation = None; self.playlist_monitor = None; }
                        if ui.small_button("Delete").clicked() { self.settings.library.playlists.remove(&name); }
                    });
                }
                ui.horizontal_wrapped(|ui| {
                    if self.next_rotation.is_some() { if ui.button("Pause").clicked() { self.next_rotation = None; } }
                    else if ui.add_enabled(!self.queue.paths.is_empty() && self.settings.mode == 0 && !self.monitors.is_empty(), egui::Button::new("Start / Resume")).clicked() {
                        if self.playlist_monitor.is_none() { self.playlist_monitor = self.monitors.get(self.monitor).cloned(); }
                        self.next_rotation = Some(Instant::now());
                    }
                    if ui.add_enabled(self.playlist_monitor.is_some(), egui::Button::new("Next")).clicked() { self.playlist_next(); }
                    ui.label(format!("{} images · {}", self.queue.paths.len(), if self.next_rotation.is_some() { "Running" } else { "Paused" }));
                    if let Some(m) = &self.playlist_monitor { ui.label(format!("On {}", m.name)); }
                });
            });
        });
        self.collection_window = open;
    }
    fn preview(&mut self, ui: &mut egui::Ui) {
        let size = Vec2::new(
            ui.available_width(),
            (ui.available_height() - 180.0).max(180.0),
        );
        let (canvas, response) = ui.allocate_exact_size(size, egui::Sense::click_and_drag());
        let painter = ui.painter();
        painter.rect_filled(canvas, 12.0, Color32::from_rgb(12, 16, 23));
        let Some(texture) = &self.texture else {
            painter.text(
                canvas.center(),
                egui::Align2::CENTER_CENTER,
                if self.preview_pending {
                    "Loading preview…"
                } else {
                    "Select an image to compose your wallpaper"
                },
                egui::FontId::proportional(17.0),
                Color32::GRAY,
            );
            return;
        };
        let source = Vec2::new(self.original.0 as f32, self.original.1 as f32);
        let scale = ((canvas.width() - 32.0) / source.x)
            .min((canvas.height() - 32.0) / source.y)
            .max(0.001);
        let rect = egui::Rect::from_center_size(canvas.center(), source * scale);
        if response.double_clicked() {
            self.position = 0.5;
        }
        if response.dragged()
            && let Some(pointer) = response.interact_pointer_pos()
        {
            let (_, _, cw, ch) = core::crop(
                self.original.0,
                self.original.1,
                self.target(),
                self.position,
            );
            let slack = source - Vec2::new(cw as f32, ch as f32);
            if slack.x > 0.0 {
                self.position = ((pointer.x - rect.left()) / scale - cw as f32 / 2.0) / slack.x;
            } else if slack.y > 0.0 {
                self.position = ((pointer.y - rect.top()) / scale - ch as f32 / 2.0) / slack.y;
            }
            self.position = self.position.clamp(0.0, 1.0);
        }
        let (x, y, cw, ch) = core::crop(
            self.original.0,
            self.original.1,
            self.target(),
            self.position,
        );
        let crop = egui::Rect::from_min_size(
            rect.min + Vec2::new(x as f32, y as f32) * scale,
            Vec2::new(cw as f32, ch as f32) * scale,
        );
        painter.image(
            texture.id(),
            rect,
            egui::Rect::from_min_max(egui::pos2(0.0, 0.0), egui::pos2(1.0, 1.0)),
            Color32::WHITE,
        );
        let shade = Color32::from_black_alpha(175);
        for r in [
            egui::Rect::from_min_max(rect.min, egui::pos2(crop.left(), rect.bottom())),
            egui::Rect::from_min_max(egui::pos2(crop.right(), rect.top()), rect.max),
            egui::Rect::from_min_max(
                egui::pos2(crop.left(), rect.top()),
                egui::pos2(crop.right(), crop.top()),
            ),
            egui::Rect::from_min_max(
                egui::pos2(crop.left(), crop.bottom()),
                egui::pos2(crop.right(), rect.bottom()),
            ),
        ] {
            painter.rect_filled(r, 0.0, shade);
        }
        painter.rect_stroke(
            crop,
            0.0,
            egui::Stroke::new(2.0_f32, ACCENT),
            egui::StrokeKind::Inside,
        );
        if response.hovered() {
            ui.ctx().set_cursor_icon(egui::CursorIcon::Grab);
        }
    }
}
impl eframe::App for Studio {
    fn save(&mut self, storage: &mut dyn eframe::Storage) {
        self.remember_crop();
        eframe::set_value(storage, "studio", &self.settings);
    }
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        self.events(ctx);
        if self.next_rotation.is_some_and(|due| Instant::now() >= due)
            && !self.busy
            && !self.scanning
        {
            self.playlist_next();
        }
        if let Some(due) = self.next_rotation {
            ctx.request_repaint_after(
                due.saturating_duration_since(Instant::now())
                    .max(Duration::from_millis(100)),
            );
        }
        self.collections_ui(ctx);
        if self.scanning || self.busy || self.preview_pending {
            ctx.request_repaint_after(Duration::from_millis(50));
        }
        egui::TopBottomPanel::top("header").show(ctx, |ui| {
            ui.add_space(12.0);
            ui.horizontal(|ui| {
                if ui.button("Compositions · Displays · Playlists").clicked() {
                    self.collection_window = true;
                }
                ui.label(RichText::new("◈").size(30.0).color(ACCENT));
                ui.vertical(|ui| {
                    ui.heading("Wallpaper Studio");
                    ui.label(
                        RichText::new("A better view, perfectly framed.").color(Color32::GRAY),
                    );
                });
            });
            ui.add_space(12.0);
        });
        egui::TopBottomPanel::bottom("status").show(ctx, |ui| {
            ui.horizontal(|ui| {
                if self.scanning || self.busy {
                    ui.spinner();
                }
                ui.label(RichText::new(&self.status).color(if self.failed {
                    Color32::LIGHT_RED
                } else {
                    Color32::GRAY
                }));
            });
        });
        egui::SidePanel::left("settings").default_width(240.0).width_range(210.0..=340.0).resizable(true).show(ctx,|ui| {
            ui.add_space(14.0);ui.label(RichText::new("YOUR COLLECTION").color(ACCENT).strong());
            ui.add_enabled_ui(!self.scanning && !self.busy,|ui| {
                ui.label("Image folder");ui.text_edit_singleline(&mut self.settings.folder);
                if ui.button("Choose folder…").clicked() && let Some(path)=rfd::FileDialog::new().pick_folder() {self.settings.folder=path.display().to_string();}
                ui.checkbox(&mut self.settings.recursive,"Include subfolders");
                ui.checkbox(&mut self.settings.minimum,"Only ≥ target size");
                ui.add_space(14.0); ui.separator();ui.add_space(10.0);
                ui.label(RichText::new("MAKE IT FIT").color(ACCENT).strong());
                ui.horizontal(|ui| {for (i,label) in ["Monitor","Phone","Custom"].iter().enumerate() {ui.selectable_value(&mut self.settings.mode,i,*label);}});
                match self.settings.mode {
                    0=>{egui::ComboBox::from_id_salt("monitor").selected_text(self.monitors.get(self.monitor).map(|m|m.name.as_str()).unwrap_or("Default display")).show_ui(ui,|ui|{
                        for (i,m) in self.monitors.iter().enumerate() {ui.selectable_value(&mut self.monitor,i,format!("{} · {} × {}",m.name,m.width,m.height));}
                    });},
                    1=>{self.settings.phone=self.settings.phone.min(PRESETS.len()-1);egui::ComboBox::from_id_salt("phone").selected_text(PRESETS[self.settings.phone].0).show_ui(ui,|ui|{
                        for (i,p) in PRESETS.iter().enumerate() {ui.selectable_value(&mut self.settings.phone,i,p.0);}
                    });},
                    _=>{ui.horizontal(|ui|{ui.add(egui::DragValue::new(&mut self.settings.width).range(1..=8192).prefix("W "));ui.add(egui::DragValue::new(&mut self.settings.height).range(1..=8192).prefix("H "));});},
                }
                let (w,h)=self.target(); ui.label(RichText::new(format!("{w} × {h} px")).size(24.0).strong());
                ui.label("Changing the target updates the crop. Scan again to refresh the ranking.");
                ui.add_space(14.0);
                if ui.add_sized([ui.available_width(),42.0],egui::Button::new(RichText::new("Scan collection").strong().color(Color32::BLACK)).fill(ACCENT)).clicked() {self.scan();}
            });
            if self.scanning && ui.button("Cancel scan").clicked() {self.cancel.store(true,Ordering::Relaxed);}
            ui.add_space(20.0);ui.separator();ui.label("COMPOSE WITH CONFIDENCE");ui.label("Drag the preview to move the crop. Double-click to centre it.");
            if self.settings.mode==0 {ui.small("Apply changes only the selected display. Save assignments to compose a layout.");}
        });
        if self.active_target != self.target() {
            self.remember_crop();
            self.active_target = self.target();
            if let Some(index) = self.selected {
                self.position = self
                    .settings
                    .library
                    .position(&self.entries[index].path, self.target());
            }
        }
        egui::SidePanel::left("library")
            .default_width(330.0)
            .width_range(240.0..=600.0)
            .resizable(true)
            .show(ctx, |ui| {
                ui.add_space(14.0);
                ui.heading("Library");
                ui.label("Search filenames");
                let mut search_changed = false;
                ui.horizontal(|ui| {
                    let clear_width = 65.0;
                    search_changed = ui
                        .add(
                            egui::TextEdit::singleline(&mut self.query)
                                .hint_text("Type to filter…")
                                .desired_width(ui.available_width() - clear_width),
                        )
                        .changed();
                    if ui
                        .add_enabled(!self.query.is_empty(), egui::Button::new("Clear"))
                        .clicked()
                    {
                        self.query.clear();
                        search_changed = true;
                    }
                });
                let query = self.query.trim().to_lowercase();
                let visible: Vec<usize> = self
                    .entries
                    .iter()
                    .enumerate()
                    .filter(|(_, e)| {
                        e.path
                            .file_name()
                            .unwrap_or_default()
                            .to_string_lossy()
                            .to_lowercase()
                            .contains(&query)
                    })
                    .map(|(i, _)| i)
                    .collect();
                ui.label(format!(
                    "{} of {} images",
                    visible.len(),
                    self.entries.len()
                ));
                ui.label(RichText::new("BEST FIT FIRST").small().color(Color32::GRAY));
                if visible.is_empty() {
                    ui.add_space(30.0);
                    ui.label(if self.entries.is_empty() {
                        "Your next wallpaper is waiting. Choose a folder and scan to begin."
                    } else {
                        "No images match your search."
                    });
                }
                let mut selection = None;
                let mut activate = false;
                let mut scroll = egui::ScrollArea::vertical();
                if search_changed {
                    scroll = scroll.vertical_scroll_offset(0.0);
                }
                scroll.show_rows(ui, 62.0, visible.len(), |ui, range| {
                    for row in range {
                        let i = visible[row];
                        let entry = &self.entries[i];
                        let name = entry.path.file_name().unwrap_or_default().to_string_lossy();
                        let response = ui.add_enabled(
                            !self.scanning && !self.busy,
                            egui::Button::new(format!(
                                "{}\n{} × {}   ·   {:.1}% fit",
                                name,
                                entry.width,
                                entry.height,
                                entry.score * 100.0
                            ))
                            .selected(self.selected == Some(i))
                            .min_size(Vec2::new(ui.available_width(), 54.0)),
                        );
                        let response = response.on_hover_text(entry.path.display().to_string());
                        if response.clicked() {
                            selection = Some(i);
                        }
                        if response.double_clicked() {
                            selection = Some(i);
                            activate = true;
                        }
                    }
                });
                if let Some(i) = selection {
                    self.select(i);
                }
                if activate {
                    self.action(if self.settings.mode == 0 { 0 } else { 1 });
                }
            });
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.add_space(14.0);
            ui.heading("The perfect frame");
            ui.label(RichText::new("What you frame is what you get.").color(Color32::GRAY));
            self.preview(ui);
            ui.add_enabled_ui(
                self.texture.is_some() && !self.scanning && !self.busy,
                |ui| {
                    ui.horizontal(|ui| {
                        ui.label("Crop position");
                        ui.add(egui::Slider::new(&mut self.position, 0.0..=1.0).show_value(false));
                        if ui.button("Centre").clicked() {
                            self.position = 0.5;
                        }
                    });
                    ui.horizontal(|ui| {
                        let label = if self.settings.mode == 0 {
                            "Apply to selected display"
                        } else {
                            "Copy cropped image"
                        };
                        if ui
                            .add(
                                egui::Button::new(
                                    RichText::new(label).color(Color32::BLACK).strong(),
                                )
                                .fill(ACCENT),
                            )
                            .clicked()
                        {
                            self.action(if self.settings.mode == 0 { 0 } else { 1 });
                        }
                        if ui.button("Save PNG…").clicked() {
                            self.action(2);
                        }
                    });
                },
            );
        });
        self.remember_crop();
    }
}
impl Drop for Studio {
    fn drop(&mut self) {
        self.cancel.store(true, Ordering::Relaxed);
    }
}
fn app_icon() -> egui::IconData {
    let mut rgba = Vec::with_capacity(64 * 64 * 4);
    for y in 0..64_i32 {
        for x in 0..64_i32 {
            let mountain = y > 22 + (x - 24).abs() && y < 53;
            let ridge = y > 30 + (x - 43).abs() && y < 53;
            let sun = (x - 45).pow(2) + (y - 17).pow(2) < 36;
            let color = if sun {
                [239, 215, 156, 255]
            } else if ridge {
                [76, 153, 145, 255]
            } else if mountain {
                [109, 213, 191, 255]
            } else {
                [20, 25, 34, 255]
            };
            rgba.extend_from_slice(&color);
        }
    }
    egui::IconData {
        rgba,
        width: 64,
        height: 64,
    }
}
fn main() -> eframe::Result {
    eframe::run_native(
        "Wallpaper Studio",
        eframe::NativeOptions {
            viewport: egui::ViewportBuilder::default()
                .with_icon(app_icon())
                .with_inner_size([1280.0, 820.0])
                .with_min_inner_size([1000.0, 680.0]),
            ..Default::default()
        },
        Box::new(|cc| Ok(Box::new(Studio::new(cc)))),
    )
}

#[cfg(test)]
mod studio_tests {
    use super::*;
    #[test]
    fn saved_crop_survives_selection_and_settings_round_trip() {
        let mut studio = Studio::from_settings(Settings::default());
        studio.entries = vec![
            core::Entry {
                path: "first.png".into(),
                width: 100,
                height: 200,
                score: 1.0,
            },
            core::Entry {
                path: "second.png".into(),
                width: 100,
                height: 200,
                score: 1.0,
            },
        ];
        studio.select(0);
        studio.position = 0.9;
        studio.select(1);
        assert_eq!(studio.position, 0.5);
        studio.select(0);
        assert_eq!(studio.position, 0.9);
        studio.remember_crop();
        let restored: Settings = ron::from_str(&ron::to_string(&studio.settings).unwrap()).unwrap();
        assert_eq!(
            restored
                .library
                .position(std::path::Path::new("first.png"), studio.target()),
            0.9
        );
    }
    #[test]
    fn old_preferences_load_with_new_defaults() {
        let settings: Settings = ron::from_str(
            "(folder: \"pictures\", recursive: false, mode: 2, width: 100, height: 200)",
        )
        .unwrap();
        assert_eq!(settings.folder, "pictures");
        assert!(settings.library.presets.is_empty());
        assert_eq!(settings.interval_minutes, 15);
    }
    #[test]
    fn failed_actions_pause_rotation() {
        let mut studio = Studio::from_settings(Settings::default());
        studio.next_rotation = Some(Instant::now());
        studio.busy = true;
        studio
            .tx
            .send(Event::Action(Err("Disconnected display".into())))
            .unwrap();
        studio.events(&egui::Context::default());
        assert!(!studio.busy);
        assert!(studio.failed);
        assert!(studio.next_rotation.is_none());
    }
}
