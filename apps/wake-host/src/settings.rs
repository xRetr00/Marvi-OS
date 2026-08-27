//! Marvi's `providers.env`, read and written by the listener.
//!
//! One store, not two. The settings page writes this file and the Gateway
//! reads it; a listener keeping its own microphone choice somewhere else would
//! be a second answer to "which microphone", and the two would disagree the
//! first time either was changed.
//!
//! The format is what the control centre writes: `NAME=value`, one per line,
//! sorted, `#` comments. Values are not quoted and a microphone name contains
//! spaces and brackets, which is fine -- everything after the first `=` is the
//! value.
//!
//! Deliberately not a dotenv crate. This reads one key and writes one key.

use std::collections::BTreeMap;
use std::path::PathBuf;

/// `%LOCALAPPDATA%\Marvi-OS\providers.env`, resolved the way `state::path()`
/// resolves its own file so the two always agree about which install this is.
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
    root.join("providers.env")
}

fn read_all() -> BTreeMap<String, String> {
    let mut found = BTreeMap::new();
    let Ok(text) = std::fs::read_to_string(path()) else {
        return found;
    };
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((name, value)) = line.split_once('=') {
            found.insert(name.trim().to_string(), value.to_string());
        }
    }
    found
}

/// One setting, from the environment first and the file second.
///
/// The environment wins because that is how the desktop hands over a choice
/// when it starts the listener directly. The file is what a login-started
/// listener has instead -- it inherits nothing, and without this it opened the
/// default microphone however carefully the user had chosen another.
pub fn get(name: &str) -> String {
    match std::env::var(name) {
        Ok(value) if !value.trim().is_empty() => value,
        _ => read_all().get(name).cloned().unwrap_or_default(),
    }
}

/// Save one setting. An empty value removes it, which is how "system default"
/// is expressed -- the same convention the settings page uses.
///
/// Returns whether it was written. Never panics: a listener that is working
/// must not stop because a preference could not be saved.
pub fn set(name: &str, value: &str) -> bool {
    let mut all = read_all();
    if value.trim().is_empty() {
        all.remove(name);
    } else {
        all.insert(name.to_string(), value.to_string());
    }
    let mut body = String::from("# Marvi OS provider settings. Written by the control center.\n");
    for (key, saved) in &all {
        body.push_str(key);
        body.push('=');
        body.push_str(saved);
        body.push('\n');
    }
    let target = path();
    if let Some(parent) = target.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    // The process is also updated, so this listener acts on it without a
    // restart and without re-reading the file it just wrote.
    if value.trim().is_empty() {
        unsafe { std::env::remove_var(name) };
    } else {
        unsafe { std::env::set_var(name, value) };
    }
    std::fs::write(target, body).is_ok()
}
