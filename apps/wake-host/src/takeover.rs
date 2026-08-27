//! One listener on the microphone, and the old one stopped.
//!
//! Two separate problems that both end as "Marvi joins twice when you say her
//! name once", and they need different answers.
//!
//! **Two of these.** Enabling from Settings starts one now *and* registers it
//! for login, so a machine that logged in with it already registered gets a
//! second. A named mutex settles that: the kernel decides, atomically, and the
//! loser exits before it opens anything.
//!
//! **The daemon this replaced.** `pythonw.exe -m marvi_agent.wake_daemon` may
//! still be holding the microphone from the last login, and overwriting the Run
//! key does not stop a process that is already running -- so the handover
//! looked complete in Settings while two things listened until the next reboot.
//! It is found the way it announced itself: it wrote its pid into the same
//! `wake.json` this writes, which is the one thing it is guaranteed to have
//! done.
//!
//! Deliberately *not* a search for python processes by name. Marvi's own
//! Gateway and Agent are python, and a wake word that kills interpreters by
//! pattern is one bad match away from stopping the assistant it wakes.

#[cfg(windows)]
mod windows {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_ALREADY_EXISTS, HANDLE};
    use windows_sys::Win32::System::Threading::{
        CreateMutexW, OpenProcess, TerminateProcess, PROCESS_TERMINATE,
    };

    /// Per-user, hence `Local\`. A global name would make one listener across
    /// every account on the machine, and two people logged in at once each
    /// want their own.
    const MUTEX: &str = r"Local\MarviWakeWordListener";

    /// The handle is deliberately leaked: it must live as long as the process,
    /// and Windows releases it on exit whether we do or not.
    pub fn only_instance() -> bool {
        let name: Vec<u16> = OsStr::new(MUTEX).encode_wide().chain(Some(0)).collect();
        let handle = unsafe { CreateMutexW(std::ptr::null(), 1, name.as_ptr()) };
        if handle.is_null() {
            // Could not ask. Listening is better than refusing to start over a
            // question that could not be put.
            return true;
        }
        unsafe { windows_sys::Win32::Foundation::GetLastError() != ERROR_ALREADY_EXISTS }
    }

    pub fn stop(pid: u32) -> bool {
        if pid == 0 || pid == std::process::id() {
            return false;
        }
        let handle: HANDLE = unsafe { OpenProcess(PROCESS_TERMINATE, 0, pid) };
        if handle.is_null() {
            // Already gone, or not ours to stop. Either way there is nothing
            // to hand over from.
            return false;
        }
        let stopped = unsafe { TerminateProcess(handle, 0) } != 0;
        unsafe { CloseHandle(handle) };
        stopped
    }
}

#[cfg(not(windows))]
mod windows {
    pub fn only_instance() -> bool {
        true
    }
    pub fn stop(_pid: u32) -> bool {
        false
    }
}

pub use windows::only_instance;

/// The pid of whatever was listening before this started, if it still is.
///
/// Read from `wake.json` rather than from the process list: the file is the
/// handover note the previous listener left, and its heartbeat is what says
/// whether the note is still true. A stale file from a listener that exited
/// cleanly names a pid the OS has since reused, and stopping that is stopping
/// something at random -- so a heartbeat older than the Gateway's own
/// staleness window is treated as nobody there.
pub const STALE: f64 = 15.0;

pub fn predecessor() -> Option<u32> {
    let text = std::fs::read_to_string(crate::state::path()).ok()?;
    let parsed: serde_json::Value = serde_json::from_str(&text).ok()?;
    if parsed.get("running")? != &serde_json::Value::Bool(true) {
        return None;
    }
    let beat = parsed.get("heartbeat")?.as_f64()?;
    if crate::state::now() - beat > STALE {
        return None;
    }
    let pid = parsed.get("pid")?.as_u64()? as u32;
    (pid != 0 && pid != std::process::id()).then_some(pid)
}

/// Take the microphone. Returns whether anything had to be stopped.
pub fn take() -> bool {
    match predecessor() {
        Some(pid) => windows::stop(pid),
        None => false,
    }
}
