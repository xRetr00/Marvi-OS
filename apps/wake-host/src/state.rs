//! Where the listener says it is alive.
//!
//! A file rather than a port, and not a new idea: the Python daemon wrote this
//! and the Gateway already reads it. Keeping the exact shape is the point --
//! the listener changes language, `/voice/wake` does not change at all, and no
//! surface has to learn a second way to ask the same question.
//!
//! The fields are load-bearing in a way that took a while to arrive at:
//! `heartbeat` is what separates *registered but crashed* from *registered and
//! starting*, which the status bar reported as one thing for days while a dead
//! wake word looked like a warming one.

use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

/// Written this often, comfortably inside the staleness window the Gateway
/// applies. A listener that stops writing is one that died.
pub const HEARTBEAT: std::time::Duration = std::time::Duration::from_secs(5);

/// One firing, kept so true and false ones can be told apart afterwards.
#[derive(Deserialize, Serialize, Default, Clone)]
pub struct Detection {
    pub at: f64,
    pub confidence: f32,
}

/// How many firings to remember. Enough to see a pattern over an evening,
/// small enough that the state file stays a state file.
pub const RECENT_DETECTIONS: usize = 30;

#[derive(Deserialize, Serialize, Default)]
pub struct State {
    pub pid: u32,
    pub running: bool,
    pub started_at: f64,
    pub heartbeat: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub heard_at: Option<f64>,
    /// How many times it has fired since this listener started.
    ///
    /// `heard_at` alone is the *last* detection, which cannot answer the only
    /// question anybody asks about a wake word: is it going off when nobody
    /// said its name. One timestamp reads identically whether it triggered
    /// once this morning or forty times since lunch, and "I think it is false
    /// arming" was unanswerable because of it.
    ///
    /// Counted since start rather than per day, because `started_at` is
    /// already here -- so a rate falls out of the two without this needing to
    /// know anything about calendars or where the person is.
    pub heard_total: u32,
    /// The score at the moment it fired, and the ones before it.
    ///
    /// `confidence` is overwritten on every hop, so by the time anybody reads
    /// the file it holds the score of the silence since -- 0.0058 while the
    /// detection that wrote `heard_at` had scored something entirely
    /// different. That made the one question worth asking unanswerable: what
    /// does a real "Hey Marvi" score, and what does the thing that fired in an
    /// empty room score? Without both numbers a threshold is a guess.
    ///
    /// Newest first, capped at `RECENT_DETECTIONS`, so a pattern is visible
    /// without keeping a log.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub heard_confidence: Option<f32>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub recent: Vec<Detection>,
    pub confidence: f32,
    #[serde(skip_serializing_if = "str::is_empty")]
    pub error: String,
    /// Every microphone this listener can open, for the settings picker.
    ///
    /// Written by the thing that does the opening, which is the only source
    /// that can be right. The Gateway enumerated with PortAudio and offered
    /// ten devices where cpal can open three -- so choosing the wrong seven
    /// set a name nothing matched, and the listener quietly fell back to the
    /// default microphone while Settings showed the one you picked.
    ///
    /// ponytail: written once at start. A microphone plugged in mid-session
    /// does not appear until the listener restarts; toggling it in Settings is
    /// a restart.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub devices: Vec<String>,
    /// Which of `devices` this opens when nothing is chosen.
    #[serde(skip_serializing_if = "str::is_empty")]
    pub default_device: String,
}

pub fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|since| since.as_secs_f64())
        .unwrap_or_default()
}

/// `%LOCALAPPDATA%\Marvi-OS\state\wake.json`, or wherever `MARVI_HOME` says.
///
/// Resolved the same way the daemon resolved it, because the Gateway looks in
/// exactly one place and a listener writing somewhere else is a listener that
/// reports as dead while running perfectly.
pub fn path() -> PathBuf {
    let root = std::env::var("MARVI_HOME")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            let base = std::env::var("LOCALAPPDATA")
                .or_else(|_| std::env::var("USERPROFILE"))
                .unwrap_or_else(|_| ".".into());
            PathBuf::from(base).join("Marvi-OS")
        });
    root.join("state").join("wake.json")
}

/// A small cross-process stop request used by the control center.
///
/// Removing the Run-key entry only affects the next login. The listener that
/// already owns the microphone needs a separate, deliberate stop signal, and
/// a file keeps that signal local without opening a network or renderer IPC
/// surface.
pub fn stop_path() -> PathBuf {
    path().with_file_name("wake.stop")
}

pub fn request_stop() -> bool {
    let target = stop_path();
    if let Some(parent) = target.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(target, std::process::id().to_string()).is_ok()
}

pub fn clear_stop_request() {
    let _ = std::fs::remove_file(stop_path());
}

pub fn stop_requested() -> bool {
    stop_path().is_file()
}

pub fn read() -> Option<State> {
    let text = std::fs::read_to_string(path()).ok()?;
    serde_json::from_str(&text).ok()
}

impl State {
    /// Never fails loudly. A listener that is working must not stop because
    /// the file describing it could not be written.
    pub fn write(&self) {
        let target = path();
        if let Some(parent) = target.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(text) = serde_json::to_string(self) {
            let _ = std::fs::write(target, text);
        }
    }
}
