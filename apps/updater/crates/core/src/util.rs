//! Small cross-cutting helpers: the current PID, timestamps, random temp
//! names, and running a command under a hard timeout.

use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Current process id as `u32` (Windows pids fit; truncation is fine).
pub fn current_pid() -> u32 {
    std::process::id()
}

/// Milliseconds since the Unix epoch. Used for marker age checks, where a
/// monotonic-ish integer is easier to compare than an ISO string.
pub fn epoch_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// A compact UTC timestamp (RFC 3339, seconds precision) for display and
/// result files, produced without a date library.
pub fn iso8601_utc() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = secs / 86_400;
    let rem = secs % 86_400;
    let (h, rem) = (rem / 3_600, rem % 3_600);
    let (m, s) = (rem / 60, rem % 60);

    // Civil date from days since epoch (Howard Hinnant's algorithm).
    let z = days as i64 + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let mth = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if mth <= 2 { y + 1 } else { y };

    format!("{y:04}-{mth:02}-{d:02}T{h:02}:{m:02}:{s:02}Z")
}

/// A short random suffix for staging directories.
pub fn random_suffix() -> String {
    use std::collections::hash_map::RandomState;
    use std::hash::{BuildHasher, Hasher};
    let a = RandomState::new().build_hasher().finish();
    let b = RandomState::new().build_hasher().finish();
    format!("{a:016x}{b:016x}")
}

/// Run `program args` in `cwd` under a hard timeout, streaming nothing and
/// returning an error on timeout or non-zero exit.
///
/// On Windows, `.cmd`/`.bat` programs (like `npm`) must be run through
/// `cmd /d /s /c`; callers are expected to pass `cmd` with the full command
/// already wrapped, or a real `.exe` like `git`.
pub fn run_with_timeout(
    program: &str,
    args: &[&str],
    cwd: &std::path::Path,
    timeout: Duration,
) -> Result<(), String> {
    let mut child = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("could not start {program}: {e}"))?;

    let deadline = Instant::now() + timeout;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(status)) => {
                return Err(format!("{program} exited with {status}"));
            }
            Ok(None) => {}
            Err(e) => return Err(format!("wait on {program} failed: {e}")),
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("{program} timed out after {timeout:?}"));
        }
        thread::sleep(Duration::from_millis(100));
    }
}

/// Run a command whose full line (including a `.cmd` target) is known, e.g.
/// `npm ci`. Wraps it in `cmd /d /s /c` on Windows.
pub fn run_shell_with_timeout(
    command_line: &str,
    cwd: &std::path::Path,
    timeout: Duration,
) -> Result<(), String> {
    let (program, args): (&str, Vec<&str>) = if cfg!(windows) {
        (
            "cmd",
            vec!["/d", "/s", "/c", command_line],
        )
    } else {
        ("sh", vec!["-c", command_line])
    };
    run_with_timeout(program, &args, cwd, timeout)
}

/// True when a Windows process id is still alive. Falls back to `tasklist`
/// via `cmd` so we depend on nothing but the OS.
#[cfg(windows)]
pub fn process_alive(pid: u32) -> bool {
    let filter = format!("PID eq {pid}");
    let output = Command::new("tasklist").args(["/FI", &filter, "/NH"]).output();
    match output {
        Ok(out) => {
            let text = String::from_utf8_lossy(&out.stdout);
            // The header is suppressed with /NH, so any non-empty line means a
            // process matched the filter.
            text.lines().any(|l| !l.trim().is_empty())
        }
        Err(_) => true, // can't determine: treat as alive (fail closed)
    }
}

/// Non-Windows: signal 0 probes existence.
#[cfg(not(windows))]
pub fn process_alive(pid: u32) -> bool {
    #[allow(unsafe_code)]
    unsafe {
        extern "C" {
            fn kill(pid: i32, sig: i32) -> i32;
        }
        kill(pid as i32, 0) == 0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn epoch_ms_increases_or_is_zero() {
        assert!(epoch_ms() > 0);
    }

    #[test]
    fn iso_timestamp_is_well_formed() {
        let t = iso8601_utc();
        assert_eq!(t.len(), 20);
        assert!(t.ends_with('Z'));
        assert_eq!(&t[4..5], "-");
        assert_eq!(&t[7..8], "-");
        assert_eq!(&t[10..11], "T");
    }

    #[test]
    fn random_suffixes_differ() {
        assert_ne!(random_suffix(), random_suffix());
    }

    #[test]
    fn timeout_kills_a_slow_command() {
        let started = Instant::now();
        // `ping` sleeps ~5s on Windows with `-n 6`; a 1s timeout must cut it.
        let r = run_shell_with_timeout(
            if cfg!(windows) { "ping -n 6 127.0.0.1 > nul" } else { "sleep 6" },
            std::path::Path::new("."),
            Duration::from_millis(800),
        );
        assert!(r.is_err());
        assert!(started.elapsed() < Duration::from_secs(5));
    }
}
