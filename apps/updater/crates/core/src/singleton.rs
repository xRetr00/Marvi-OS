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

use crate::util::{no_window, process_alive};

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
    let output = no_window(&mut Command::new("powershell"))
        .args([
            "-NoProfile",
            "-Command",
            // Three fields, because three are parsed. It emitted two --
            // ProcessId and CommandLine -- so the parser read the command line
            // as the executable path and left the command empty, and neither of
            // the checks below could match. `clear_install_root` had never
            // stopped a single process.
            "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)|$($_.ExecutablePath)|$($_.CommandLine)\" }",
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
    let self_pid = std::process::id();
    listing
        .lines()
        .filter_map(|line| classify(line, root.as_deref(), self_pid))
        .collect()
}

/// Decide whether one `pid|ExecutablePath|CommandLine` row is Marvi's.
///
/// Split out from the query so the matching can be tested against the real
/// shapes Windows produces -- which is where both bugs were. The query used to
/// emit two fields into a three-field parser, so the command line was read as
/// the executable path and the command was always empty; and the executable
/// check was anchored with `starts_with`, which a quoted command line can
/// never satisfy. Between them, `clear_install_root` had never stopped a
/// single process, and an update kept failing with EBUSY on a directory
/// nothing had been asked to release.
fn classify(line: &str, root: Option<&str>, self_pid: u32) -> Option<Stray> {
    let mut fields = line.splitn(3, '|');
    let pid = fields.next()?.trim().parse::<u32>().ok()?;
    if pid == self_pid {
        return None;
    }
    let executable = fields.next().unwrap_or("").trim().to_lowercase();
    let command = fields.next().unwrap_or("").trim();
    let lowered = command.to_lowercase();

    // A process whose executable lives under the install root is Marvi's by
    // definition, whatever it is called -- that is how Electron's helpers, the
    // ones holding dist\win-unpacked open, are caught.
    //
    // `starts_with` for the path, `contains` for the command line: Windows
    // reports ExecutablePath bare and CommandLine quoted, so
    //   "C:\...\win-unpacked\Marvi-OS.exe" --type=gpu-process
    // does not start with anything but a quote.
    let runs_from_install = root.is_some_and(|root| {
        (!executable.is_empty() && executable.starts_with(root))
            || (!lowered.is_empty() && lowered.contains(root))
    });

    // The services are launched by `uv`, so their executable is a Python
    // somewhere else entirely and only the command line identifies them.
    let named_service = ["marvi_gateway", "marvi_agent", "livekit-server"]
        .iter()
        .any(|needle| lowered.contains(needle))
        && root.is_none_or(|root| lowered.contains(root));

    if !runs_from_install && !named_service {
        return None;
    }
    Some(Stray {
        pid,
        command: if command.is_empty() {
            executable
        } else {
            command.to_string()
        },
    })
}

/// Terminate a process and everything it started.
///
/// Windows has no process groups, so the tree is walked with `taskkill /T`.
/// Without `/T` this only ends `uv` and leaves the Python that holds the files.
pub fn kill_tree(pid: u32) -> bool {
    if cfg!(windows) {
        no_window(&mut Command::new("taskkill"))
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .output()
            // 128 means it was already gone, which is the state we wanted.
            .map(|o| o.status.success() || o.status.code() == Some(128))
            .unwrap_or(false)
    } else {
        no_window(&mut Command::new("kill"))
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

#[cfg(test)]
mod stray_tests {
    use super::classify;

    const ROOT: &str = r"c:\users\x\appdata\local\marvi-os\install";

    /// The exact shape that destroyed an installation.
    ///
    /// Electron's helper processes run from inside the build output, holding
    /// `dist\win-unpacked` open after the main window has gone. They were
    /// never found, so nothing released the directory, so every update failed
    /// with EBUSY -- and one of those failures deleted the app.
    #[test]
    fn an_electron_helper_under_the_install_root_is_a_stray() {
        let line = format!(
            r#"1234|{ROOT}\apps\desktop\dist\win-unpacked\marvi-os.exe|"{ROOT}\apps\desktop\dist\win-unpacked\Marvi-OS.exe" --type=gpu-process"#
        );

        let stray = classify(&line, Some(ROOT), 1).expect("helper should be a stray");

        assert_eq!(stray.pid, 1234);
    }

    /// Windows reports CommandLine quoted, so anchoring to the start of it
    /// never matched. This is the same row with no ExecutablePath, which is
    /// what the query used to produce for every process.
    #[test]
    fn a_quoted_command_line_alone_is_still_matched() {
        let line = format!(
            r#"1234||"{ROOT}\apps\desktop\dist\win-unpacked\Marvi-OS.exe" --type=renderer"#
        );

        assert!(classify(&line, Some(ROOT), 1).is_some());
    }

    #[test]
    fn a_service_is_matched_by_its_command_line() {
        let line = format!(r#"99|c:\python\python.exe|python -m marvi_gateway --root {ROOT}"#);

        assert!(classify(&line, Some(ROOT), 1).is_some());
    }

    #[test]
    fn somebody_elses_process_is_left_alone() {
        let line = r#"77|c:\windows\explorer.exe|"C:\Windows\explorer.exe""#;

        assert!(classify(line, Some(ROOT), 1).is_none());
    }

    /// A different Marvi install on the same machine is not this one's to kill.
    #[test]
    fn an_install_somewhere_else_is_not_a_stray() {
        let line = r#"55|d:\other\marvi-os\install\app.exe|"D:\other\marvi-os\install\app.exe""#;

        assert!(classify(line, Some(ROOT), 1).is_none());
    }

    #[test]
    fn the_updater_does_not_report_itself() {
        let line = format!(r#"42|{ROOT}\marvi-bootstrap.exe|"{ROOT}\marvi-bootstrap.exe" update"#);

        assert!(classify(&line, Some(ROOT), 42).is_none());
    }

    #[test]
    fn a_row_with_no_command_line_still_parses() {
        let line = format!(r"7|{ROOT}\apps\desktop\dist\win-unpacked\marvi-os.exe|");

        let stray = classify(&line, Some(ROOT), 1).expect("path alone is enough");

        assert_eq!(stray.pid, 7);
    }

    #[test]
    fn a_system_row_with_neither_field_is_ignored() {
        assert!(classify("0||", Some(ROOT), 1).is_none());
        assert!(classify("not-a-pid|x|y", Some(ROOT), 1).is_none());
    }
}
