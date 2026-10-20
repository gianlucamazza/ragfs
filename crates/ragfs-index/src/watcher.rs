//! File system watcher for detecting changes.

use notify_debouncer_full::notify::{RecommendedWatcher, RecursiveMode};
use notify_debouncer_full::{DebounceEventResult, Debouncer, RecommendedCache, new_debouncer};
use ragfs_core::FileEvent;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;
use std::time::Duration;
use tokio::sync::mpsc as tokio_mpsc;
use tracing::{debug, error, warn};

use crate::exclude::ExclusionMatcher;

/// File system watcher with debouncing.
pub struct FileWatcher {
    debouncer: Debouncer<RecommendedWatcher, RecommendedCache>,
}

impl FileWatcher {
    /// Create a new file watcher.
    pub fn new(
        event_tx: tokio_mpsc::Sender<FileEvent>,
        debounce_duration: Duration,
    ) -> Result<Self, notify::Error> {
        Self::with_pending(event_tx, debounce_duration, None)
    }

    /// Create a watcher that increments `pending` for each queued event.
    pub fn with_pending(
        event_tx: tokio_mpsc::Sender<FileEvent>,
        debounce_duration: Duration,
        pending: Option<Arc<AtomicUsize>>,
    ) -> Result<Self, notify::Error> {
        Self::with_filter(event_tx, debounce_duration, pending, None)
    }

    /// Create a watcher that filters events with the shared exclusion matcher.
    pub fn with_filter(
        event_tx: tokio_mpsc::Sender<FileEvent>,
        debounce_duration: Duration,
        pending: Option<Arc<AtomicUsize>>,
        matcher: Option<Arc<ExclusionMatcher>>,
    ) -> Result<Self, notify::Error> {
        let (tx, rx) = mpsc::channel();

        let event_tx_clone = event_tx.clone();
        std::thread::spawn(move || {
            while let Ok(result) = rx.recv() {
                if let Err(e) = handle_debounced_events(
                    result,
                    &event_tx_clone,
                    pending.as_deref(),
                    matcher.as_deref(),
                ) {
                    error!("Error handling file events: {e}");
                }
            }
        });

        let debouncer = new_debouncer(debounce_duration, None, move |result| {
            let _ = tx.send(result);
        })?;

        Ok(Self { debouncer })
    }

    /// Start watching a path.
    pub fn watch(&mut self, path: &Path) -> Result<(), notify_debouncer_full::notify::Error> {
        debug!("Starting to watch: {:?}", path);
        self.debouncer.watch(path, RecursiveMode::Recursive)?;
        Ok(())
    }

    /// Stop watching a path.
    pub fn unwatch(&mut self, path: &Path) -> Result<(), notify_debouncer_full::notify::Error> {
        debug!("Stopping watch: {:?}", path);
        self.debouncer.unwatch(path)?;
        Ok(())
    }
}

fn handle_debounced_events(
    result: DebounceEventResult,
    event_tx: &tokio_mpsc::Sender<FileEvent>,
    pending: Option<&AtomicUsize>,
    matcher: Option<&ExclusionMatcher>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    match result {
        Ok(events) => {
            for event in events {
                if let Some(file_event) = convert_event(&event, matcher) {
                    if let Some(pending) = pending {
                        pending.fetch_add(1, Ordering::SeqCst);
                    }
                    // Use blocking send since we're in a std thread
                    if event_tx.blocking_send(file_event).is_err() {
                        if let Some(pending) = pending {
                            pending.fetch_sub(1, Ordering::SeqCst);
                        }
                        warn!("Event channel closed");
                        break;
                    }
                }
            }
        }
        Err(errors) => {
            for error in errors {
                error!("Watch error: {error}");
            }
        }
    }
    Ok(())
}

fn convert_event(
    event: &notify_debouncer_full::DebouncedEvent,
    matcher: Option<&ExclusionMatcher>,
) -> Option<FileEvent> {
    use notify_debouncer_full::notify::EventKind;

    let path = event.paths.first()?.clone();

    if let Some(matcher) = matcher {
        if matcher.is_excluded(&path) {
            return None;
        }
    } else if path.components().any(|component| {
        let name = component.as_os_str().to_string_lossy();
        name.starts_with('.') && name != "." && name != ".."
    }) {
        // Fail-closed when no matcher is supplied.
        return None;
    }

    match &event.kind {
        EventKind::Create(_) => Some(FileEvent::Created(path)),
        EventKind::Modify(_) => Some(FileEvent::Modified(path)),
        EventKind::Remove(_) => Some(FileEvent::Deleted(path)),
        EventKind::Other => {
            // Handle rename as "other" event with two paths
            if event.paths.len() >= 2 {
                Some(FileEvent::Renamed {
                    from: event.paths[0].clone(),
                    to: event.paths[1].clone(),
                })
            } else {
                None
            }
        }
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::exclude::ExclusionOptions;
    use notify_debouncer_full::DebouncedEvent;
    use notify_debouncer_full::notify::EventKind;
    use notify_debouncer_full::notify::event::{CreateKind, ModifyKind, RemoveKind};
    use std::path::PathBuf;
    use std::time::Instant;

    fn make_event(kind: EventKind, paths: Vec<PathBuf>) -> DebouncedEvent {
        DebouncedEvent {
            event: notify_debouncer_full::notify::Event {
                kind,
                paths,
                attrs: Default::default(),
            },
            time: Instant::now(),
        }
    }

    #[test]
    fn test_convert_event_create() {
        let path = PathBuf::from("/tmp/test.txt");
        let event = make_event(EventKind::Create(CreateKind::File), vec![path.clone()]);

        let result = convert_event(&event, None);
        assert!(matches!(result, Some(FileEvent::Created(p)) if p == path));
    }

    #[test]
    fn test_convert_event_modify() {
        use notify_debouncer_full::notify::event::DataChange;
        let path = PathBuf::from("/tmp/test.txt");
        let event = make_event(
            EventKind::Modify(ModifyKind::Data(DataChange::Any)),
            vec![path.clone()],
        );

        let result = convert_event(&event, None);
        assert!(matches!(result, Some(FileEvent::Modified(p)) if p == path));
    }

    #[test]
    fn test_convert_event_delete() {
        let path = PathBuf::from("/tmp/test.txt");
        let event = make_event(EventKind::Remove(RemoveKind::File), vec![path.clone()]);

        let result = convert_event(&event, None);
        assert!(matches!(result, Some(FileEvent::Deleted(p)) if p == path));
    }

    #[test]
    fn test_hidden_files_skipped() {
        let path = PathBuf::from("/tmp/.hidden");
        let event = make_event(EventKind::Create(CreateKind::File), vec![path]);

        let result = convert_event(&event, None);
        assert!(result.is_none());
    }

    #[test]
    fn test_matcher_skips_secret_and_hidden_dir() {
        let matcher = ExclusionMatcher::new("/proj", ExclusionOptions::default());
        let secret = make_event(
            EventKind::Create(CreateKind::File),
            vec![PathBuf::from("/proj/server.pem")],
        );
        let hidden_dir = make_event(
            EventKind::Create(CreateKind::File),
            vec![PathBuf::from("/proj/.obsidian/x.md")],
        );
        let visible = make_event(
            EventKind::Create(CreateKind::File),
            vec![PathBuf::from("/proj/notes/keyboard.md")],
        );
        assert!(convert_event(&secret, Some(&matcher)).is_none());
        assert!(convert_event(&hidden_dir, Some(&matcher)).is_none());
        assert!(matches!(
            convert_event(&visible, Some(&matcher)),
            Some(FileEvent::Created(p)) if p.ends_with("keyboard.md")
        ));
    }
}
