//! A log of what the installer did, on disk.
//!
//! The window shows progress and then closes. When an install failed, that left
//! an empty install directory and nothing whatsoever to read — the user could
//! see that Marvi was not there and had no way to find out why. Reported as
//! "IDK what is that or what else is missing", which is the correct reaction to
//! a program that fails silently.
//!
//! So every line the window shows is also appended here, and the outcome is
//! written whether it succeeded or not. `update-result.json` only ever recorded
//! successes and updates; an install that died halfway wrote nothing at all.
//!
//! Deliberately plain text, appended, never rotated by size alone: an install
//! log is a few hundred lines and the last one is the one that matters.

use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use crate::util::iso8601_utc;

/// How many bytes of history to keep. Enough for several installs; small enough
/// that nobody has to think about it.
const MAX_BYTES: u64 = 2 * 1024 * 1024;

pub struct InstallLog {
    path: PathBuf,
    file: Option<File>,
}

impl InstallLog {
    /// Open (or create) `<state>/logs/installer.log`.
    ///
    /// Failing to open the log is not a reason to fail the install, so this
    /// always returns a usable value and simply writes nowhere if it cannot.
    pub fn open(state_dir: &Path, mode: &str) -> Self {
        let dir = state_dir.join("logs");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("installer.log");

        // Trimmed by starting over rather than by rotating: the previous log of
        // a successful install is not worth a second file.
        if std::fs::metadata(&path).map(|m| m.len()).unwrap_or(0) > MAX_BYTES {
            let _ = std::fs::remove_file(&path);
        }

        let file = OpenOptions::new().create(true).append(true).open(&path).ok();
        let mut log = Self { path, file };
        log.line(&format!("=== {mode} started ==="));
        log
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Append one timestamped line.
    pub fn line(&mut self, text: &str) {
        if let Some(file) = self.file.as_mut() {
            let _ = writeln!(file, "{} {}", iso8601_utc(), text);
            // Flushed every line on purpose: the interesting case is the one
            // where the process is about to die.
            let _ = file.flush();
        }
    }

    /// Record how it ended, successfully or not.
    pub fn finish(&mut self, status: &str, message: &str) {
        self.line(&format!("=== {status}: {message} ==="));
    }
}
