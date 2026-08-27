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

use serde::Serialize;

/// Written this often, comfortably inside the staleness window the Gateway
/// applies. A listener that stops writing is one that died.
pub const HEARTBEAT: std::time::Duration = std::time::Duration::from_secs(5);

#[derive(Serialize, Default)]
pub struct State {
    pub pid: u32,
    pub running: bool,
    pub started_at: f64,
    pub heartbeat: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub heard_at: Option<f64>,
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
