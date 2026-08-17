//! Small cross-cutting helpers: the current PID, timestamps, random temp
//! names, and running a command under a hard timeout.

use std::io::{BufRead, BufReader};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// How many trailing output lines a failure carries back.
///
/// A build that fails on line 4000 of `npm ci` is explained by the last few
/// lines; "npm exited with 1" explains nothing, which is what the installer
/// used to say.
const FAILURE_CONTEXT_LINES: usize = 25;

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

/// Run `program args` in `cwd` under a hard timeout, discarding output.
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
    run_reporting(program, args, cwd, timeout, &mut |_| {})
}

/// Same, but each line the command prints is handed to `progress`.
///
/// The installer showed "building" for fifteen minutes and then either finished
/// or said "npm exited with 1". Both are indistinguishable from a hang while
/// they are happening, and neither says what went wrong afterwards. Output is
/// the only thing that does, so it is forwarded live and the tail is kept for
/// the error message.
pub fn run_reporting(
    program: &str,
    args: &[&str],
    cwd: &std::path::Path,
    timeout: Duration,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let mut child = Command::new(program)
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("could not start {program}: {e}"))?;

    // Both pipes are drained on their own threads. A child that fills a pipe
    // nobody is reading blocks forever, and a build that produces megabytes of
    // output would do exactly that.
    let (tx, rx) = mpsc::channel::<String>();
    for stream in [
        child.stdout.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
        child.stderr.take().map(|s| Box::new(s) as Box<dyn std::io::Read + Send>),
    ]
    .into_iter()
    .flatten()
    {
        let tx = tx.clone();
        thread::spawn(move || {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
    }
    drop(tx);

    let mut tail: std::collections::VecDeque<String> = std::collections::VecDeque::new();
    let pump = |rx: &mpsc::Receiver<String>,
                    tail: &mut std::collections::VecDeque<String>,
                    progress: &mut dyn FnMut(&str)| {
        while let Ok(line) = rx.try_recv() {
            let line = line.trim_end().to_string();
            if line.is_empty() {
                continue;
            }
            progress(&line);
            tail.push_back(line);
            if tail.len() > FAILURE_CONTEXT_LINES {
                tail.pop_front();
            }
        }
    };

    let deadline = Instant::now() + timeout;
    let status = loop {
        pump(&rx, &mut tail, progress);
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {}
            Err(e) => return Err(format!("wait on {program} failed: {e}")),
        }
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return Err(format!("{program} timed out after {timeout:?}"));
        }
        thread::sleep(Duration::from_millis(100));
    };
    // The reader threads may still be finishing after the child exits.
    thread::sleep(Duration::from_millis(50));
    pump(&rx, &mut tail, progress);

    if status.success() {
        return Ok(());
    }
    let context: Vec<&str> = tail.iter().map(String::as_str).collect();
    if context.is_empty() {
        return Err(format!("{program} exited with {status}"));
    }
    Err(format!(
        "{program} exited with {status}:\n{}",
        context.join("\n")
    ))
}

/// Run a PowerShell script, forwarding its output.
///
/// Not routed through `cmd /d /s /c`: a PowerShell one-liner contains quotes,
/// and Rust's argument escaping targets the C runtime parser, which is not the
/// one `cmd` uses. The two disagree, the quoting arrives mangled, and the
/// command fails instantly. That is exactly what happened to the `uv`
/// installer — a failure nobody saw, because on a machine that already had
/// `uv` the code never ran.
#[cfg(windows)]
pub fn run_powershell(
    script: &str,
    cwd: &std::path::Path,
    timeout: Duration,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    // The system module path is put back first. A vendor install script that
    // calls a plain cmdlet - Astral's calls `Get-ExecutionPolicy` - fails with
    // "the module could not be loaded" wherever PSModulePath has been narrowed,
    // which is the case on a GitHub runner and on any machine where something
    // has rewritten it. Autoloading needs the path to be there; nothing else in
    // the script can compensate for it.
    let script = format!(
        r#"$env:PSModulePath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\Modules;$env:PSModulePath"; {script}"#
    );
    run_reporting(
        "powershell",
        &["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", &script],
        cwd,
        timeout,
        progress,
    )
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

/// `run_shell_with_timeout`, with the command's output forwarded live.
pub fn run_shell_reporting(
    command_line: &str,
    cwd: &std::path::Path,
    timeout: Duration,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let (program, args): (&str, Vec<&str>) = if cfg!(windows) {
        ("cmd", vec!["/d", "/s", "/c", command_line])
    } else {
        ("sh", vec!["-c", command_line])
    };
    run_reporting(program, &args, cwd, timeout, progress)
}

/// True when a Windows process id is still alive. Falls back to `tasklist`
/// via `cmd` so we depend on nothing but the OS.
#[cfg(windows)]
pub fn process_alive(pid: u32) -> bool {
    let filter = format!("PID eq {pid}");
    // CSV, because "any non-empty line" is wrong: when nothing matches,
    // tasklist prints "INFO: No tasks are running which match the specified
    // criteria." to *stdout*. Treating that as a match makes every dead process
    // look alive - which made `wait_for_exit` never return, so every update
    // aborted with "Marvi OS did not exit in time".
    let output = Command::new("tasklist")
        .args(["/FI", &filter, "/NH", "/FO", "CSV"])
        .output();
    match output {
        Ok(out) => {
            let text = String::from_utf8_lossy(&out.stdout);
            // A real row is quoted CSV and carries the pid as its own field.
            // The INFO line is neither.
            let needle = format!("\"{pid}\"");
            text.lines()
                .any(|line| line.trim_start().starts_with('"') && line.contains(&needle))
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
    fn this_process_is_alive() {
        assert!(process_alive(std::process::id()));
    }

    #[test]
    fn a_dead_pid_is_not_reported_alive() {
        // The regression that matters: tasklist prints "INFO: No tasks are
        // running..." to stdout, and counting that as a match made every dead
        // process look alive - so wait_for_exit never returned and every update
        // aborted with "Marvi OS did not exit in time".
        assert!(!process_alive(4_294_967_294));
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
