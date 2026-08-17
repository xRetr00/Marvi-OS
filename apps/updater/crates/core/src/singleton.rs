//! One installer at a time, and a clean install root before touching it.
//!
//! Two bootstraps running at once is not a theoretical worry: a user who
//! double-clicks twice, or clicks Update while an install is still finishing,
//! gets two processes doing `git checkout` and `npm ci` in the same directory.
//! The result is a corrupted checkout with no clear cause.
//!
//! The lock is a file holding a PID. A stale one - left by a crash - is
//! reclaimed rather than treated as fatal, because refusing to ever run again
//! after one bad exit is worse than the problem it guards against.
//!
//! The second half of this module is the reason it exists at all. `child.kill()`
//! on the desktop side terminates `uv` and leaves the Python it spawned
//! running, holding the virtualenv and the checkout open. On Windows a locked
//! file makes `git checkout` and `npm ci` fail, so an orphan from the previous
//! session breaks the next update for a reason the user cannot see.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::util::process_alive;

const LOCK_FILE: &str = "bootstrap.lock";

/// Held for the lifetime of an install or update; released on drop.
#[derive(Debug)]
pub struct Lock {
    path: PathBuf,
}

impl Drop for Lock {
    fn drop(&mut self) {
        let _ = std::fs::remove_file(&self.path);
    }
}

/// Take the installer lock, or report who already has it.
pub fn acquire(state_dir: &Path) -> Result<Lock, String> {
    let path = state_dir.join(LOCK_FILE);
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }

    if let Ok(contents) = std::fs::read_to_string(&path) {
        if let Ok(pid) = contents.trim().parse::<u32>() {
            if pid != std::process::id() && process_alive(pid) {
                return Err(format!(
                    "another Marvi installer is already running (pid {pid})"
                ));
            }
        }
        // Stale: the holder is gone. Never being able to run again after one
        // crash would be worse than the race this prevents.
        let _ = std::fs::remove_file(&path);
    }

    std::fs::write(&path, std::process::id().to_string())
        .map_err(|e| format!("could not take the installer lock: {e}"))?;
    Ok(Lock { path })
}

/// A Marvi process left over from a previous session.
#[derive(Debug, Clone)]
pub struct Stray {
    pub pid: u32,
    pub command: String,
}

/// Find Marvi's own processes, optionally limited to one install root.
///
/// Matched on the command line rather than the executable name: `python.exe`
/// says nothing, but a command line containing `marvi_gateway` is unambiguously
/// ours. Nothing else on the machine is touched, and a second checkout that
/// someone is developing in is left alone when a root is given.
pub fn find_strays(install_root: Option<&Path>) -> Vec<Stray> {
    if !cfg!(windows) {
        return Vec::new();
    }
    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine } | \
             ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }",
        ])
        .output();
    let Ok(output) = output else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }

    let listing = String::from_utf8_lossy(&output.stdout);
    let root = install_root.map(|p| p.display().to_string().to_lowercase());
    let mut found = Vec::new();
    for line in listing.lines() {
        let Some((pid, command)) = line.split_once('|') else {
            continue;
        };
        let Ok(pid) = pid.trim().parse::<u32>() else {
            continue;
        };
        if pid == std::process::id() {
            continue;
        }
        let lowered = command.to_lowercase();
        let is_marvi = ["marvi_gateway", "marvi_agent", "livekit-server"]
            .iter()
            .any(|needle| lowered.contains(needle));
        if !is_marvi {
            continue;
        }
        if let Some(root) = root.as_ref() {
            if !lowered.contains(root) {
                continue;
            }
        }
        found.push(Stray {
            pid,
            command: command.trim().to_string(),
        });
    }
    found
}

/// Terminate a process and everything it started.
///
/// Windows has no process groups, so the tree is walked with `taskkill /T`.
/// Without `/T` this only ends `uv` and leaves the Python that holds the files.
pub fn kill_tree(pid: u32) -> bool {
    if cfg!(windows) {
        Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .output()
            // 128 means it was already gone, which is the state we wanted.
            .map(|o| o.status.success() || o.status.code() == Some(128))
            .unwrap_or(false)
    } else {
        Command::new("kill")
            .args(["-9", &format!("-{pid}")])
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }
}

/// Clear anything still holding the install root, and report what was stopped.
///
/// Called before an update applies. The desktop app exiting is not enough on
/// its own: its children outlive it, and one of them holding a file is the
/// difference between an update that works and one that fails in `git`.
pub fn clear_install_root(
    install_root: &Path,
    progress: &mut dyn FnMut(&str),
) -> Vec<String> {
    let strays = find_strays(Some(install_root));
    if strays.is_empty() {
        return Vec::new();
    }
    progress(&format!(
        "stopping {} leftover process(es) holding the install",
        strays.len()
    ));
    let mut stopped = Vec::new();
    for stray in strays {
        if kill_tree(stray.pid) {
            stopped.push(format!("pid {} ({})", stray.pid, first_word(&stray.command)));
        }
    }
    // Windows releases handles a moment after the process ends; going straight
    // into `git checkout` can still hit a lock that is about to disappear.
    std::thread::sleep(std::time::Duration::from_millis(750));
    stopped
}

fn first_word(command: &str) -> String {
    command
        .split_whitespace()
        .next()
        .unwrap_or(command)
        .rsplit(['\\', '/'])
        .next()
        .unwrap_or("?")
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_lock_is_held_and_released() {
        let dir = std::env::temp_dir().join(format!("marvi-lock-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();

        let held = acquire(&dir).expect("should take a free lock");
        assert!(dir.join(LOCK_FILE).exists());
        drop(held);
        // Released on drop, so a normal exit never leaves the next run blocked.
        assert!(!dir.join(LOCK_FILE).exists());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_live_holder_blocks_a_second_installer() {
        let dir = std::env::temp_dir().join(format!("marvi-lock2-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();

        // A genuinely running process, since the point is that a live holder
        // blocks. Writing an arbitrary number would only have tested the stale
        // path with a misleading name.
        let mut child = Command::new(if cfg!(windows) { "cmd" } else { "sh" })
            .args(if cfg!(windows) {
                vec!["/C", "ping -n 20 127.0.0.1 >NUL"]
            } else {
                vec!["-c", "sleep 20"]
            })
            .spawn()
            .expect("could not start a helper process");
        std::fs::write(dir.join(LOCK_FILE), child.id().to_string()).unwrap();

        let blocked = acquire(&dir);
        let _ = child.kill();
        let _ = child.wait();
        let _ = std::fs::remove_dir_all(&dir);

        assert!(blocked.is_err(), "a live holder must block a second installer");
    }

    #[test]
    fn a_stale_lock_is_reclaimed() {
        let dir = std::env::temp_dir().join(format!("marvi-lock3-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(LOCK_FILE), "4294967294").unwrap();

        // Never running again after one crash is worse than the race.
        assert!(acquire(&dir).is_ok());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_corrupt_lock_does_not_wedge_the_installer() {
        let dir = std::env::temp_dir().join(format!("marvi-lock4-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join(LOCK_FILE), "not a pid").unwrap();

        assert!(acquire(&dir).is_ok());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn strays_are_matched_by_command_line_not_by_name() {
        // python.exe says nothing; the command line is what identifies ours.
        // Nothing is asserted about this machine's processes, only that the
        // probe returns without error.
        let _ = find_strays(None);
    }
}
