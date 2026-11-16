use rand::seq::SliceRandom;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Composition {
    pub path: PathBuf,
    pub target: (u32, u32),
    pub position: f32,
}
#[derive(Clone, Default, Serialize, Deserialize)]
#[serde(default)]
pub struct Library {
    pub crops: Vec<Composition>,
    pub presets: std::collections::BTreeMap<String, Composition>,
    pub displays: std::collections::BTreeMap<String, Composition>,
    pub playlists: std::collections::BTreeMap<String, Vec<PathBuf>>,
}
impl Library {
    pub fn position(&self, path: &Path, target: (u32, u32)) -> f32 {
        self.crops
            .iter()
            .find(|c| c.path == path && c.target == target)
            .map(|c| c.position)
            .filter(|p| p.is_finite())
            .unwrap_or(0.5)
            .clamp(0.0, 1.0)
    }
    pub fn remember(&mut self, composition: Composition) {
        self.crops
            .retain(|c| c.path != composition.path || c.target != composition.target);
        self.crops.push(composition);
    }
}
#[derive(Default)]
pub struct Queue {
    pub paths: Vec<PathBuf>,
    pending: Vec<PathBuf>,
    last: Option<PathBuf>,
}
impl Queue {
    pub fn new(paths: Vec<PathBuf>) -> Self {
        let mut unique = Vec::new();
        for path in paths {
            if !unique.contains(&path) {
                unique.push(path);
            }
        }
        Self {
            paths: unique,
            ..Self::default()
        }
    }
    pub fn next(&mut self, shuffle: bool) -> Option<PathBuf> {
        if self.pending.is_empty() {
            self.pending = self.paths.clone();
            if shuffle {
                self.pending.shuffle(&mut rand::rng());
                if self.pending.len() > 1 && self.pending.last() == self.last.as_ref() {
                    let end = self.pending.len() - 1;
                    self.pending.swap(0, end);
                }
            } else {
                self.pending.reverse();
            }
        }
        let path = self.pending.pop()?;
        self.last = Some(path.clone());
        Some(path)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn positions_are_scoped_to_image_and_resolution() {
        let mut library = Library::default();
        let composition = Composition {
            path: "a.png".into(),
            target: (100, 200),
            position: 0.8,
        };
        library.remember(composition.clone());
        assert_eq!(library.position(Path::new("a.png"), (100, 200)), 0.8);
        assert_eq!(library.position(Path::new("b.png"), (100, 200)), 0.5);
        assert_eq!(library.position(Path::new("a.png"), (200, 100)), 0.5);
        let encoded = ron::to_string(&library).unwrap();
        let restored: Library = ron::from_str(&encoded).unwrap();
        assert_eq!(restored.position(Path::new("a.png"), (100, 200)), 0.8);
    }
    #[test]
    fn shuffle_has_no_repeats_inside_or_between_cycles() {
        let mut queue = Queue::new(vec!["a".into(), "b".into(), "c".into(), "a".into()]);
        let mut last = None;
        for _ in 0..100 {
            let cycle: Vec<_> = (0..3).map(|_| queue.next(true).unwrap()).collect();
            assert_ne!(Some(&cycle[0]), last.as_ref());
            let unique: std::collections::HashSet<_> = cycle.iter().collect();
            assert_eq!(unique.len(), 3);
            last = cycle.last().cloned();
        }
    }
    #[test]
    fn ordered_queue_and_empty_queue() {
        let mut queue = Queue::new(vec!["a".into(), "b".into()]);
        let result: Vec<_> = (0..5).map(|_| queue.next(false).unwrap()).collect();
        assert_eq!(result, ["a", "b", "a", "b", "a"].map(PathBuf::from));
        assert!(Queue::default().next(true).is_none());
    }
}
