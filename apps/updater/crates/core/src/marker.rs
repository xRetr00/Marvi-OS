//! In-progress marker with liveness data.
//!
//! The updater writes `{ pid, started_at_ms }` before touching anything and
//! clears it on completion. The Electron side reads it to decide whether an
//! update is genuinely mid-flight: a marker whose process is dead, or that is
//! older than a threshold, is treated as stale and recoverable — fixing the
//! bug where a crashed updater left "UPDATE IN PROGRESS" on screen forever.

use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::util::{current_pid, epoch_ms};

pub const MARKER_FILE: &str = ".marvi-update-in-progress";

/// Maximum age (ms) after which a marker is considered stale even if its pid
/// is somehow still alive (a runaway updater that never finished its job).
pub const STALE_AFTER_MS: u64 = 2 * 60 * 60 * 1000;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Marker {
    pub pid: u32,
    pub started_at_ms: u64,
}

pub fn marker_path(state_dir: &Path) -> std::path::PathBuf {
    state_dir.join(MARKER_FILE)
}

/// Claim the marker for this process.
pub fn write_marker(state_dir: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(state_dir)?;
    let marker = Marker {
        pid: current_pid(),
        started_at_ms: epoch_ms(),
    };
    let json = serde_json::to_string(&marker).unwrap();
    write_utf8_no_bom(&marker_path(state_dir), &json)
}

/// Read the marker, if any.
pub fn read_marker(state_dir: &Path) -> Option<Marker> {
    let raw = std::fs::read_to_string(marker_path(state_dir)).ok()?;
    let text = strip_bom(&raw);
    serde_json::from_str(text).ok()
}

/// Clear the marker only if this process still owns it. A partner that
/// rewrote the marker keeps its own claim.
pub fn clear_marker(state_dir: &Path) {
    let path = marker_path(state_dir);
    let Some(marker) = read_marker(state_dir) else {
        return;
    };
    if marker.pid == current_pid() {
        let _ = std::fs::remove_file(path);
    }
}

/// Whether the marker represents a live, non-stale update.
///
/// `alive` is a function returning whether `pid` still runs, injected so this
/// stays testable without probing real processes.
pub fn is_active(marker: &Marker, now_ms: u64, alive: impl Fn(u32) -> bool) -> bool {
    let age_ms = now_ms.saturating_sub(marker.started_at_ms);
    age_ms < STALE_AFTER_MS && alive(marker.pid)
}

fn strip_bom(s: &str) -> &str {
    s.strip_prefix('\u{feff}').unwrap_or(s)
}

fn write_utf8_no_bom(path: &Path, contents: &str) -> std::io::Result<()> {
    // `std::fs::write` never emits a BOM, unlike PowerShell's `-Encoding utf8`.
    std::fs::write(path, contents)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn roundtrips_and_clears() {
        let dir = TempDir::new().unwrap();
        let state = dir.path();
        write_marker(state).unwrap();
        let marker = read_marker(state).unwrap();
        assert_eq!(marker.pid, current_pid());
        assert!(marker.started_at_ms > 0);

        clear_marker(state);
        assert!(read_marker(state).is_none());
    }

    #[test]
    fn liveness_checks_pid_and_age() {
        let fresh = Marker {
            pid: 1,
            started_at_ms: 1_000,
        };
        assert!(is_active(&fresh, 2_000, |_| true));
        assert!(!is_active(&fresh, 2_000, |_| false));

        let stale = Marker {
            pid: 1,
            started_at_ms: 1_000,
        };
        assert!(!is_active(&stale, STALE_AFTER_MS + 1_001, |_| true));
    }

    #[test]
    fn does_not_clear_a_marker_it_does_not_own() {
        let dir = TempDir::new().unwrap();
        let state = dir.path();
        let json = serde_json::to_string(&Marker {
            pid: current_pid().wrapping_add(1),
            started_at_ms: epoch_ms(),
        })
        .unwrap();
        write_utf8_no_bom(&marker_path(state), &json).unwrap();

        clear_marker(state);
        assert!(read_marker(state).is_some());
    }
}
